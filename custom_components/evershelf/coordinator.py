"""DataUpdateCoordinator for EverShelf."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_auth import evershelf_headers, evershelf_params
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

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        return evershelf_headers(self.token, json_body=json_body)

    def _params(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return evershelf_params(self.token, params)

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
                params=self._params(
                    {"action": "ha_sensor", "expiry_days": self.expiry_days}
                ),
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 401:
                    raise UpdateFailed("EverShelf API token invalid or missing")
                if resp.status != 200:
                    raise UpdateFailed(f"HTTP {resp.status} from EverShelf")
                raw: dict[str, Any] = await resp.json(content_type=None)
                attrs: dict[str, Any] = raw.get("attributes", {})
                result: dict[str, Any] = {
                    "state": raw.get("state", 0),
                    "shopping_list": [],
                    **attrs,
                }
                # Safety-net: ensure total_items is always set even if the PHP
                # response structure changes. Uses state value as fallback when
                # the sensor=total variant is called directly.
                result.setdefault("total_items", result["state"])

            # Fetch shopping list (non-fatal if it fails)
            try:
                async with session.get(
                    f"{self.url}/api/index.php",
                    params=self._params({"action": "ha_shopping_items"}),
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
                params=self._params({"action": "ha_info"}),
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    info = await resp.json(content_type=None)
                    if info.get("api_token_required") and not self.token:
                        return False, "token_required"
                    return True, info.get("name", info.get("instance", "EverShelf"))
                if resp.status in (401, 403):
                    return False, "invalid_auth"
        except aiohttp.ClientError:
            pass

        # Fallback to ha_sensor (older EverShelf versions)
        try:
            async with self._session().get(
                f"{self.url}/api/index.php",
                params=self._params({"action": "ha_sensor"}),
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
                params=self._params({"action": "ha_info"}),
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
                params=self._params({"action": "inventory_list"}),
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
                params=self._params({"action": "update_inventory"}),
                headers=self._headers(json_body=True),
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
                params=self._params({"action": action}),
                headers=self._headers(json_body=True),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                return resp.status == 200
        except aiohttp.ClientError as err:
            _LOGGER.error("EverShelf %s error: %s", action, err)
            return False

    async def _post_json(
        self,
        action: str,
        payload: dict[str, Any],
        timeout: int = 15,
    ) -> dict[str, Any] | None:
        """POST request returning parsed JSON or None on error."""
        try:
            async with self._session().post(
                f"{self.url}/api/index.php",
                params=self._params({"action": action}),
                headers=self._headers(json_body=True),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                _LOGGER.warning("EverShelf %s returned HTTP %s", action, resp.status)
        except aiohttp.ClientError as err:
            _LOGGER.error("EverShelf %s error: %s", action, err)
        return None

    async def _get_json(self, action: str, params: dict | None = None, timeout: int = 15) -> dict[str, Any] | None:
        """GET request returning parsed JSON or None on error."""
        try:
            p = self._params({"action": action, **(params or {})})
            async with self._session().get(
                f"{self.url}/api/index.php",
                params=p,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                _LOGGER.warning("EverShelf %s returned HTTP %s", action, resp.status)
        except aiohttp.ClientError as err:
            _LOGGER.error("EverShelf %s error: %s", action, err)
        return None

    # ------------------------------------------------------------------
    # Action methods (called by button/service entities)
    # ------------------------------------------------------------------

    async def async_refresh_prices(self) -> dict[str, Any] | None:
        """Compute shopping total from existing price cache (no AI calls)."""
        return await self._get_json("ha_refresh_prices")

    async def async_suggest_recipe(self, location: str = "") -> str | None:
        """Ask EverShelf AI for a recipe using items expiring soonest."""
        params = {}
        if location:
            params["location"] = location
        data = await self._get_json("ha_suggest_recipe", params, timeout=35)
        if data:
            return data.get("recipe")
        return None

    async def async_sync_smart_shopping(self) -> bool:
        """Trigger smart shopping AI sync."""
        return await self._post("smart_shopping", {})

    async def async_clear_expired(self) -> dict[str, Any] | None:
        """Remove expired zero-stock inventory rows."""
        return await self._get_json("ha_clear_expired")

    async def async_list_inventory(self, location: str = "") -> dict[str, Any] | None:
        """Return EverShelf inventory rows, optionally filtered by location."""
        params = {"location": location} if location else None
        return await self._get_json("inventory_list", params)

    async def async_resolve_barcode(self, barcode: str) -> dict[str, Any] | None:
        """Resolve a barcode through EverShelf's local DB and external lookup chain."""
        return await self._get_json(
            "resolve_barcode",
            {"barcode": barcode},
            timeout=45,
        )

    async def async_read_expiry_image(self, image_base64: str) -> dict[str, Any] | None:
        """Read an expiry date from a base64-encoded image via EverShelf."""
        return await self._post_json(
            "gemini_expiry",
            {"image": image_base64},
            timeout=60,
        )

    async def async_save_product(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Create or update an EverShelf product and return the API response."""
        return await self._post_json("product_save", payload, timeout=30)

    async def async_add_inventory(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Add quantity to an EverShelf inventory expiry batch and return the API response."""
        return await self._post_json("inventory_add", payload, timeout=30)

    async def async_add_scanned_item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Save a scanned product when needed, then add it to a matching inventory batch."""
        product_id = item.get("product_id")
        product_response: dict[str, Any] | None = None

        if product_id is None:
            product_payload: dict[str, Any] = {}
            for key in (
                "name",
                "barcode",
                "brand",
                "category",
                "image_url",
                "unit",
                "notes",
                "package_unit",
                "shopping_name",
            ):
                value = item.get(key)
                if isinstance(value, str):
                    value = value.strip()
                if value not in (None, ""):
                    product_payload[key] = value
            for key in ("default_quantity",):
                value = item.get(key)
                if value is not None:
                    product_payload[key] = value
            if isinstance(item.get("nutriments"), dict):
                product_payload["nutriments"] = item["nutriments"]

            product_response = await self.async_save_product(product_payload)
            if product_response is None:
                return {
                    "success": False,
                    "stage": "product_save",
                    "error": "product_save_failed",
                    "message": "Could not save the scanned product.",
                }
            if product_response.get("success") is not True or not product_response.get("id"):
                return {
                    "success": False,
                    "stage": "product_save",
                    "error": product_response.get("error", "product_save_failed"),
                    "message": product_response.get("message", "Could not save the scanned product."),
                    "product": product_response,
                }
            product_id = product_response["id"]

        inventory_payload: dict[str, Any] = {
            "product_id": int(product_id),
            "quantity": item.get("quantity", 1),
            "location": item.get("location", "dispensa"),
        }
        for key in (
            "expiry_date",
            "unit",
            "package_unit",
            "package_size",
            "vacuum_sealed",
            "expiry_user_set",
        ):
            value = item.get(key)
            if isinstance(value, str):
                value = value.strip()
            if value not in (None, ""):
                inventory_payload[key] = value

        inventory_response = await self.async_add_inventory(inventory_payload)
        if inventory_response is None:
            return {
                "success": False,
                "stage": "inventory_add",
                "error": "inventory_add_failed",
                "message": "Could not add the scanned product to inventory.",
                "product_id": int(product_id),
                "product": product_response,
            }
        if inventory_response.get("success") is not True:
            return {
                "success": False,
                "stage": "inventory_add",
                "error": inventory_response.get("error", "inventory_add_failed"),
                "message": inventory_response.get("message", "Could not add the scanned product to inventory."),
                "product_id": int(product_id),
                "product": product_response,
                "inventory": inventory_response,
            }

        return {
            "success": True,
            "product_id": int(product_id),
            "product": product_response,
            "inventory": inventory_response,
        }

    async def async_get_calendar_events(self) -> list[dict[str, Any]]:
        """Fetch all expiry events from EverShelf for the calendar entity."""
        data = await self._get_json("ha_calendar")
        if data:
            return data.get("events", [])
        return []
