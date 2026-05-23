"""DataUpdateCoordinator for EverShelf."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class EverShelfCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch pantry data from an EverShelf instance."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        url: str,
        token: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry_id}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.entry_id = entry_id
        self.url = url.rstrip("/")
        self.token = token

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _session(self) -> aiohttp.ClientSession:
        return async_get_clientsession(self.hass, verify_ssl=False)

    # ------------------------------------------------------------------
    # DataUpdateCoordinator
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the ha_sensor overview from EverShelf."""
        try:
            async with self._session().get(
                f"{self.url}/api/?action=ha_sensor",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    raise UpdateFailed(f"HTTP {resp.status} from EverShelf")
                raw: dict[str, Any] = await resp.json(content_type=None)
                attrs: dict[str, Any] = raw.get("attributes", {})
                return {
                    "state": raw.get("state", 0),
                    **attrs,
                }
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Cannot reach EverShelf: {err}") from err

    # ------------------------------------------------------------------
    # Connection test (called from config_flow)
    # ------------------------------------------------------------------

    async def async_test_connection(self) -> tuple[bool, str]:
        """Attempt a connection to EverShelf.

        Returns (True, friendly_info) on success or (False, error_key) on
        failure. The error_key is used as key in translations/errors.
        """
        try:
            async with self._session().get(
                f"{self.url}/api/?action=ha_sensor",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return True, "EverShelf"
                if resp.status == 401:
                    return False, "invalid_auth"
                return False, "cannot_connect"
        except aiohttp.ClientError:
            return False, "cannot_connect"

    # ------------------------------------------------------------------
    # HA Services
    # ------------------------------------------------------------------

    async def async_add_to_shopping(
        self,
        name: str,
        quantity: float | None,
        unit: str | None,
    ) -> bool:
        """Add a product to the EverShelf shopping list."""
        payload: dict[str, Any] = {"name": name}
        if quantity is not None:
            payload["quantity"] = quantity
        if unit:
            payload["unit"] = unit
        return await self._post("shopping_add", payload)

    async def async_mark_used(
        self,
        name: str,
        quantity: float,
        unit: str | None,
    ) -> bool:
        """Reduce the stock of an inventory item by *quantity*.

        Performs a two-step call:
        1. GET inventory_list  → find item by name (case-insensitive)
        2. POST update_inventory  → set new_qty = current_qty - quantity
        """
        session = self._session()
        try:
            async with session.get(
                f"{self.url}/api/?action=inventory_list",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("EverShelf inventory_list returned HTTP %s", resp.status)
                    return False
                data: dict[str, Any] = await resp.json(content_type=None)

            items: list[dict[str, Any]] = data.get("items", [])
            match = next(
                (i for i in items if i.get("name", "").lower() == name.lower()),
                None,
            )
            if not match:
                _LOGGER.warning("EverShelf: item '%s' not found in inventory", name)
                return False

            item_id = match["id"]
            current_qty = float(match.get("quantity", 0))
            new_qty = max(0.0, current_qty - quantity)

            async with session.post(
                f"{self.url}/api/?action=update_inventory",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"id": item_id, "quantity": new_qty},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp2:
                return resp2.status == 200

        except aiohttp.ClientError as err:
            _LOGGER.error("EverShelf mark_used error: %s", err)
            return False

    # ------------------------------------------------------------------
    # Internal POST helper
    # ------------------------------------------------------------------

    async def _post(self, action: str, payload: dict[str, Any]) -> bool:
        try:
            async with self._session().post(
                f"{self.url}/api/?action={action}",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                return resp.status == 200
        except aiohttp.ClientError as err:
            _LOGGER.error("EverShelf %s error: %s", action, err)
            return False
