"""The MySmartBike WebAPI."""
from __future__ import annotations

from datetime import datetime
import logging
import traceback
from typing import Any

from aiohttp import ClientResponseError, ClientSession
from aiohttp.client_exceptions import ClientError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_BASE_URI,
    API_USER_AGENT,
    API_X_APP,
    API_X_PLATFORM,
    API_X_THEME,
    API_X_VERSION,
    SYSTEM_PROXY,
    VERIFY_SSL,
)
from .device import MySmartBikeDevice
from .exceptions import MySmartBikeAuthException

LOGGER = logging.getLogger(__name__)


class MySmartBikeWebApi:
    """Define the WebAPI object."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: ClientSession,
        username: str,
        password: str,
    ) -> None:
        """Initialize."""
        self._session: ClientSession = session
        self._username: str = username
        self._password: str = password
        self.initialized: bool = False
        self.token: str = ""
        self.hass: HomeAssistant = hass

    async def login(self) -> bool:
        """Get the login token from MySmartBike cloud."""
        LOGGER.debug("login: Start")

        data = f"password={self._password}&contents_id=&email={self._username}"

        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}

        login_response = await self._request(
            "post", "/api/v1/users/login", data=data, headers=headers
        )

        if login_response and login_response.get("status") and login_response.get("status") == 200:
            LOGGER.debug("login: Success")
            self.token = login_response.get("data").get("token")
            return True

        if login_response and login_response.get("status"):
            LOGGER.warning("login: auth error -  %s", login_response)
            raise MySmartBikeAuthException(login_response)

        return False

    async def get_device_list(self) -> dict[str, MySmartBikeDevice]:
        """Pull bikes and generate device list."""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

        _response = await self._request("get", "/api/v1/objects/me?limit=5", headers=headers)
        if _response and _response.get("status") and _response.get("status") == 200:
            # LOGGER.debug("get_device_list: %s", _response)

            return await self._build_device_list(_response)

        LOGGER.debug("get_device_list: other error -  %s")
        return {}

    async def _request(
        self,
        method: str,
        endpoint: str,
        ignore_errors: bool = False,
        **kwargs,
    ) -> Any:
        """Make a request against the API."""

        url = f"{API_BASE_URI}{endpoint}"

        if "headers" not in kwargs:
            kwargs.setdefault("headers", {})

        kwargs.setdefault("proxy", SYSTEM_PROXY)

        kwargs["headers"].update(
            {
                "Accept": "application/json",
                "User-Agent": API_USER_AGENT,
                "Accept-Language": "de-DE",
                "X-Theme": API_X_THEME,
                "X-App": API_X_APP,
                "X-Platform": API_X_PLATFORM,
                "X-Version": API_X_VERSION,
            }
        )

        if not self._session or self._session.closed:
            self._session = async_get_clientsession(self.hass, VERIFY_SSL)

        try:
            if "url" in kwargs:
                async with self._session.request(method, **kwargs) as resp:
                    # resp.raise_for_status()
                    return await resp.json(content_type=None)
            else:
                async with self._session.request(method, url, **kwargs) as resp:
                    resp.raise_for_status()
                    return await resp.json(content_type=None)

        except ClientResponseError as err:
            LOGGER.debug(traceback.format_exc())
            if not ignore_errors:
                raise MySmartBikeAuthException from err
            return None
        except ClientError as err:
            LOGGER.debug(traceback.format_exc())
            if not ignore_errors:
                raise ClientError from err
            return None
        except Exception:
            LOGGER.debug(traceback.format_exc())

    async def _build_device_list(self, data) -> dict[str, MySmartBikeDevice]:
        root_objects: dict[str, MySmartBikeDevice] = {}
        for rbike in data["data"]:
            state_of_charge: int | None = None
            remaining_capacity: int | None = None

            for obj in rbike["object_tree"]:
                if "state_of_charge" in obj:
                    state_of_charge = obj["state_of_charge"]
                if "remaining_capacity" in obj:
                    remaining_capacity = obj["remaining_capacity"]

            root_object = MySmartBikeDevice(
                rbike["serial"],
                rbike["odometry"],
                rbike["object_model"]["brand"]["alias"],
                rbike.get("object_model").get("model_name"),
                rbike.get("longitude"),
                rbike.get("latitude"),
                datetime.strptime(rbike.get("last_position_date"), "%Y-%m-%d %H:%M:%S"),
                state_of_charge,
                remaining_capacity,
            )

            root_objects[root_object.serial] = root_object
        return root_objects
