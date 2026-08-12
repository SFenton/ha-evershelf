"""DataUpdateCoordinator for EverShelf."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import timedelta
import logging
import time
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_auth import evershelf_headers, evershelf_params
from .const import DEFAULT_EXPIRY_DAYS, DEFAULT_SCAN_INTERVAL, DOMAIN
from .recipe_api import (
    recipe_detail_request,
    recipe_grocery_add_request,
    recipe_hydration_request,
    recipe_query_request,
)

_LOGGER = logging.getLogger(__name__)

CAPABILITY_SUPPORTED = "supported"
CAPABILITY_UNSUPPORTED = "unsupported"
CAPABILITY_UNAVAILABLE = "unavailable"

_CAPABILITY_REFRESH_INTERVAL_SECONDS = 15 * 60
_CAPABILITY_PROBE_COOLDOWN_SECONDS = 30


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
        self.capabilities: frozenset[str] = frozenset()
        self.recipe_catalog_supported = False
        self.recipe_detail_supported = False
        self.recipe_grocery_supported = False
        self._capability_probe_lock = asyncio.Lock()
        self._capability_last_attempt: float | None = None
        self._capability_last_success: float | None = None
        self._capability_probe_failed = False
        self._capability_clock = time.monotonic

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        return evershelf_headers(self.token, json_body=json_body)

    def _params(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return evershelf_params(self.token, params)

    def _session(self) -> aiohttp.ClientSession:
        return async_get_clientsession(self.hass, verify_ssl=False)

    async def _decode_json_response(
        self,
        response: aiohttp.ClientResponse,
        action: str,
    ) -> dict[str, Any]:
        """Decode a JSON response while preserving structured HTTP errors."""
        data = await response.json(content_type=None)
        if not isinstance(data, dict):
            data = {"data": data}
        if response.status != 200:
            data.setdefault("success", False)
            data.setdefault("error", f"http_{response.status}")
            data["http_status"] = response.status
            _LOGGER.warning("EverShelf %s returned HTTP %s", action, response.status)
        return data

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

            await self.async_load_capabilities()
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
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
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

    async def async_get_info(self) -> dict[str, Any] | None:
        """Fetch ha_info from EverShelf (for zeroconf confirmation)."""
        try:
            async with self._session().get(
                f"{self.url}/api/index.php",
                params=self._params({"action": "ha_info"}),
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug(
                        "EverShelf capability probe returned HTTP %s",
                        resp.status,
                    )
                    return None
                info = await resp.json(content_type=None)
                if not isinstance(info, dict):
                    _LOGGER.warning(
                        "EverShelf capability probe returned an invalid response"
                    )
                    return None
                return info
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            _LOGGER.debug(
                "EverShelf capability probe failed: %s",
                type(err).__name__,
            )
        return None

    def _capability_snapshot_is_fresh(self, now: float) -> bool:
        """Return whether a successful capability probe is still authoritative."""
        if self._capability_last_success is None:
            return False
        age = now - self._capability_last_success
        return 0 <= age < _CAPABILITY_REFRESH_INTERVAL_SECONDS

    def _capability_probe_is_due(self, now: float) -> bool:
        """Return whether another bounded capability probe may start."""
        if self._capability_snapshot_is_fresh(now):
            return False
        if self._capability_last_attempt is None:
            return True
        age = now - self._capability_last_attempt
        return age < 0 or age >= _CAPABILITY_PROBE_COOLDOWN_SECONDS

    def _set_capabilities(self, capabilities: frozenset[str]) -> None:
        """Apply one successful capability snapshot."""
        self.capabilities = capabilities
        self.recipe_catalog_supported = "recipe_catalog_v2" in self.capabilities
        self.recipe_detail_supported = "recipe_detail_v1" in self.capabilities
        self.recipe_grocery_supported = "recipe_grocery_v1" in self.capabilities

    async def async_load_capabilities(self) -> bool:
        """Refresh capabilities without downgrading on transient probe errors."""
        now = self._capability_clock()
        if not self._capability_probe_is_due(now):
            return self._capability_snapshot_is_fresh(now)

        async with self._capability_probe_lock:
            now = self._capability_clock()
            if not self._capability_probe_is_due(now):
                return self._capability_snapshot_is_fresh(now)

            self._capability_last_attempt = now
            try:
                info = await self.async_get_info()
            except Exception as err:
                _LOGGER.warning(
                    "EverShelf capability probe failed unexpectedly: %s",
                    type(err).__name__,
                )
                info = None

            if not isinstance(info, Mapping):
                self._capability_probe_failed = True
                return False
            if info.get("success") is False:
                self._capability_probe_failed = True
                return False

            raw_capabilities = info.get("capabilities", [])
            if not isinstance(raw_capabilities, list):
                _LOGGER.warning(
                    "EverShelf capability probe returned an invalid capability list"
                )
                self._capability_probe_failed = True
                return False

            capabilities = frozenset(
                capability
                for capability in raw_capabilities
                if isinstance(capability, str) and capability
            )
            self._set_capabilities(capabilities)
            self._capability_last_success = self._capability_clock()
            self._capability_probe_failed = False
            return True

    async def async_capability_status(self, capability: str) -> str:
        """Return supported, unsupported, or temporarily unavailable."""
        await self.async_load_capabilities()
        if capability in self.capabilities:
            return CAPABILITY_SUPPORTED
        if self._capability_snapshot_is_fresh(self._capability_clock()):
            return CAPABILITY_UNSUPPORTED
        return CAPABILITY_UNAVAILABLE

    @property
    def capabilities_known(self) -> bool:
        """Return whether any capability probe has completed successfully."""
        return self._capability_last_success is not None

    @property
    def capability_probe_failed(self) -> bool:
        """Return whether the most recent attempted capability probe failed."""
        return self._capability_probe_failed

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
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error("EverShelf %s error: %s", action, err)
            return False

    async def _post_json(
        self,
        action: str,
        payload: dict[str, Any],
        timeout: int = 15,
        preserve_errors: bool = False,
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
                data = await self._decode_json_response(resp, action)
                return data if resp.status == 200 or preserve_errors else None
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            _LOGGER.error("EverShelf %s error: %s", action, err)
        return None

    async def _get_json(
        self,
        action: str,
        params: dict | None = None,
        timeout: int = 15,
        preserve_errors: bool = False,
    ) -> dict[str, Any] | None:
        """GET request returning parsed JSON or None on error."""
        try:
            p = self._params({"action": action, **(params or {})})
            async with self._session().get(
                f"{self.url}/api/index.php",
                params=p,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                data = await self._decode_json_response(resp, action)
                return data if resp.status == 200 or preserve_errors else None
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
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

    async def async_list_inventory(
        self,
        location: str = "",
        search: str = "",
    ) -> dict[str, Any] | None:
        """Return EverShelf inventory rows, optionally filtered by location/search."""
        query = search.strip()
        if query:
            params: dict[str, Any] = {"sensor": "product", "name": query}
            if location:
                params["location"] = location
            data = await self._get_json("ha_sensor", params)
            if data is None:
                return None
            return {
                "inventory": data.get("items", []),
                "count": data.get("state", 0),
                "search": query,
                "location": location,
                "source": "ha_sensor_product_search",
            }

        params = {"location": location} if location else None
        return await self._get_json("inventory_list", params)

    async def async_recipe_query(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Return compact recipe browse or recommendation results."""
        action, params = recipe_query_request(data)
        return await self._get_json(
            action,
            params,
            timeout=30,
            preserve_errors=True,
        )

    async def async_recipe_hydration(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Enqueue an idempotent remote recipe search or read its status."""
        method, action, request = recipe_hydration_request(data)
        if method == "GET":
            return await self._get_json(
                action,
                request,
                timeout=30,
                preserve_errors=True,
            )

        discovery = await self._post_json(
            action,
            request,
            timeout=30,
            preserve_errors=True,
        )
        if not discovery or discovery.get("success") is not True:
            return discovery
        if discovery.get("connector_enabled") is False:
            return {
                "success": False,
                "error": "cookidoo_connector_disabled",
            }
        search_id = str(discovery.get("search_id", "")).strip()
        if not search_id:
            return discovery
        status = await self._get_json(
            "recipe_jobs_status",
            {"search_id": search_id},
            timeout=30,
            preserve_errors=True,
        )
        return status or {
            "success": True,
            "search_id": search_id,
            "status": "queued",
            "imported_count": 0,
            "updated_count": 0,
            "pages_scanned": 0,
            "remote_has_more": False,
            "remote_exhausted": False,
            "queue_position": None,
            "next_poll_ms": 15000,
            "new_items": [],
            "error": None,
        }

    async def async_recipe_detail(
        self,
        recipe_id: int,
    ) -> dict[str, Any] | None:
        """Return the bounded detail projection for one recipe."""
        method, action, params = recipe_detail_request({"recipe_id": recipe_id})
        if method != "GET":
            raise ValueError("recipe detail request must use GET")
        return await self._get_json(
            action,
            params,
            timeout=30,
            preserve_errors=True,
        )

    async def async_recipe_grocery_add(
        self,
        data: Mapping[str, object],
    ) -> dict[str, Any] | None:
        """Add selected missing ingredients to EverShelf's internal list."""
        method, action, payload = recipe_grocery_add_request(data)
        if method != "POST":
            raise ValueError("recipe grocery request must use POST")
        return await self._post_json(
            action,
            payload,
            timeout=30,
            preserve_errors=True,
        )

    async def async_delete_inventory(
        self,
        inventory_id: int,
        quantity: float | None = None,
    ) -> dict[str, Any] | None:
        """Delete all or part of an EverShelf inventory row by inventory ID."""
        payload: dict[str, Any] = {"id": inventory_id}
        if quantity is not None:
            payload["quantity"] = quantity
        return await self._post_json("inventory_delete", payload, timeout=30)

    async def async_delete_inventory_item(self, inventory_id: int) -> dict[str, Any] | None:
        """Delete one item from an EverShelf inventory row."""
        return await self._post_json("inventory_delete_one", {"id": inventory_id}, timeout=30)

    async def async_update_inventory_item(
        self,
        inventory_id: int,
        expiry_date: str,
    ) -> dict[str, Any] | None:
        """Update one item from an EverShelf inventory row, splitting the row if needed."""
        return await self._post_json(
            "inventory_update_one",
            {"id": inventory_id, "expiry_date": expiry_date},
            timeout=30,
        )

    async def async_resolve_barcode(self, barcode: str) -> dict[str, Any] | None:
        """Resolve a barcode through EverShelf's local DB and external lookup chain."""
        return await self._get_json(
            "resolve_barcode",
            {"barcode": barcode},
            timeout=45,
        )

    async def async_suggest_location(
        self,
        *,
        mode: str,
        name: str,
        barcode: str = "",
        category: str = "",
    ) -> dict[str, Any]:
        """Return EverShelf's history-first storage-location suggestion."""
        payload: dict[str, Any] = {"mode": mode, "name": name}
        if barcode:
            payload["barcode"] = barcode
        if category:
            payload["category"] = category

        try:
            async with self._session().post(
                f"{self.url}/api/index.php",
                params=self._params({"action": "location_suggestion"}),
                headers=self._headers(json_body=True),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200:
                    return data
                _LOGGER.warning(
                    "EverShelf location_suggestion returned HTTP %s",
                    resp.status,
                )
                return {
                    "success": False,
                    "error_kind": "unavailable",
                    "http_code": resp.status,
                    "error": data.get("error", "location suggestion failed")
                    if isinstance(data, dict)
                    else "location suggestion failed",
                }
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            _LOGGER.error("EverShelf location_suggestion error: %s", err)
            return {
                "success": False,
                "error_kind": "unavailable",
                "error": str(err) or "location suggestion failed",
            }

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

    async def async_set_prepared_food(self, product_id: int, prepared: bool) -> dict[str, Any] | None:
        """Flag an existing product as prepared food and re-queue its taxonomy grouping."""
        return await self._post_json(
            "product_set_prepared_food",
            {"id": int(product_id), "prepared_food": bool(prepared)},
            timeout=30,
        )

    async def async_set_inventory_prepared_food(
        self, inventory_id: int, prepared: bool, quantity: float | None = None
    ) -> dict[str, Any] | None:
        """Flag some or all units of an inventory row as prepared food."""
        payload: dict[str, Any] = {"inventory_id": int(inventory_id), "prepared_food": bool(prepared)}
        if quantity is not None:
            payload["quantity"] = float(quantity)
        return await self._post_json("inventory_set_prepared_food", payload, timeout=30)

    async def async_add_scanned_item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Save a scanned product when needed, then add it to a matching inventory batch."""
        product_id = item.get("product_id")
        product_response: dict[str, Any] | None = None
        prepared_food = bool(item.get("prepared_food"))

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
            if prepared_food:
                product_payload["prepared_food"] = True
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
        elif prepared_food:
            # Existing product: product_save rewrites every column from its input, so the
            # flag is set through the dedicated endpoint instead of a partial save.
            await self.async_set_prepared_food(int(product_id), True)

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
