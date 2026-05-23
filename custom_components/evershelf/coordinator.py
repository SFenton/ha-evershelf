"""DataUpdateCoordinator for EverShelf."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_EXPIRY_DAYS, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class EverShelfCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch pantry data from an EverShelf instance."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        url: str,
        token: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        expiry_days: int = DEFAULT_EXPIRY_DAYS,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry_id}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.entry_id = entry_id
        self.url = url.rstrip("/")
        self.token = token
        self.expiry_days = expiry_days

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
        """Fetch sensor overview and shopping list from EverShelf."""
        try:
            session = self._session()

            # Fetch sensor/inventory data
            async with session.get(
                f"{self.url}/api/index.php",
                params={"action": "ha_sensor", "expiry_days": self.expiry_days},
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    raise UpdateFailed(f"HTTP {resp.status} from EverShelf")
                raw: dict[str, Any] = await resp.json(content_type=None)
                attrs: dict[str, Any] = raw.get("attributes", {})
                result: dict[str, Any] = {
                    "state": raw.get("state", 0),
                    "shopping_list": [],
                    **attrs,
                }

            # Fetch shopping list (non-fatal if it fails)
            try:
                async with session.get(
                    f"{self.url}/api/index.php",
                    params={"action": "ha_shopping_items"},
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp2:
                    if resp2.status == 200:
                        shopping_data = await resp2.json(content_type=None)
                        result["shopping_list"] = shopping_data.get("items", [])
            except aiohttp.ClientError:
                pass  # shopping list failure is non-fatal

            return result

        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Cannot reach EverShelf: {err}") from err

    # ------------------------------------------------------------------
    # Connection test (called from config_flow)
    # ------------------------------------------------------------------

    async def async_test_connection(self) -> tuple[bool, str]:
        """Test connection. Returns (True, info_text) or (False, error_key)."""
        # Try ha_info first (richer response with instance name)
        try:
            async with self._session().get(
                f"{self.url}/api/index.php",
                params={"action": "ha_info"},
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    info = await resp.json(content_type=None)
                    return True, info.get("instance", "EverShelf")
                if resp.status in (401, 403):
                    return False, "invalid_auth"
        except aiohttp.ClientError:
            pass

        # Fallback to ha_sensor (older EverShelf versions)
        try:
            async with self._session().get(
                f"{self.url}/api/index.php",
                params={"action": "ha_sensor"},
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return True, "EverShelf"
                if resp.status in (401, 403):
                    return False, "invalid_auth"
        except aiohttp.ClientError:
            pass

        return False, "cannot_connect"

    async def async_get_info(self) -> dict[str, Any]:
        """Fetch ha_info from EverShelf (for zeroconf confirmation)."""
        try:
            async with self._session().get(
                f"{self.url}/api/index.php",
                params={"action": "ha_info"},
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
        except aiohttp.ClientError:
            pass
        return {}

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
        item: dict[str, Any] = {"name": name}
        if quantity is not None:
            item["quantity"] = quantity
        if unit:
            item["unit"] = unit
        return await self._post("shopping_add", {"items": [item]})

    async def async_remove_from_shopping(self, name: str) -> bool:
        """Remove a product from the EverShelf shopping list by name or uid."""
        return await self._post("shopping_remove", {"name": name})

    async def async_mark_used(
        self,
        name: str,
        quantity: float,
        unit: str | None,
    ) -> bool:
        """Reduce the stock of an inventory item by *quantity*."""
        session = self._session()
        try:
            async with session.get(
                f"{self.url}/api/index.php",
                params={"action": "inventory_list"},
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
                f"{self.url}/api/index.php",
                params={"action": "update_inventory"},
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
                f"{self.url}/api/index.php",
                params={"action": action},
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                return resp.status == 200
        except aiohttp.ClientError as err:
            _LOGGER.error("EverShelf %s error: %s", action, err)
            return False
