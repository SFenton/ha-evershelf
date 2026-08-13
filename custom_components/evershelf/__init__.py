"""EverShelf Home Assistant integration."""
from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import logging
import math
from pathlib import Path
import time
import unicodedata

from homeassistant.components.todo import TodoListEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Context, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.storage import Store

from .const import (
    CONF_EXPIRY_DAYS,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_URL,
    DEFAULT_EXPIRY_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import (
    CAPABILITY_SUPPORTED,
    CAPABILITY_UNSUPPORTED,
    EverShelfCoordinator,
)
from .recipe_api import (
    RECIPE_FEEDBACK_TOKEN_PATTERN,
    RECIPE_GROCERY_MAX_SELECTIONS,
    RECIPE_IDEMPOTENCY_KEY_MAX_LENGTH,
    RECIPE_IDEMPOTENCY_KEY_PATTERN,
    RECIPE_INGREDIENT_ACTION_ORIGINS,
    RECIPE_INGREDIENT_DECISION_ACTIONS,
    RECIPE_INGREDIENT_KEY_MAX_LENGTH,
    RECIPE_INGREDIENT_KEY_PATTERN,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.TODO,
    Platform.CALENDAR,
    Platform.TEXT,
]

_INVENTORY_LOCATIONS = ("dispensa", "frigo", "freezer", "spice_rack", "cabinet", "altro")
_LOCATION_SUGGESTION_MODES = ("barcode", "manual")
_RECIPE_DETAIL_CAPABILITY = "recipe_detail_v1"
_RECIPE_GROCERY_CAPABILITY = "recipe_grocery_v1"
_RECIPE_INGREDIENT_FEEDBACK_CAPABILITY = (
    "recipe_ingredient_feedback_v1"
)
_RECIPE_INGREDIENT_DECISION_CAPABILITY = (
    "recipe_ingredient_feedback_v2"
)
_RECIPE_PLANNER_CAPABILITY = "recipe_planner_v1"
_DEFAULT_RECIPE_TODO_ENTITY_ID = "todo.shopping_list"
_MAX_RECIPE_MIRROR_REQUESTS = 256
_MAX_RECIPE_MIRROR_NAMES = RECIPE_GROCERY_MAX_SELECTIONS
_MAX_RECIPE_MIRROR_NAME_LENGTH = 200
_MAX_CONFIG_ENTRY_ID_LENGTH = 128
_RECIPE_MIRROR_TTL_SECONDS = 30 * 24 * 60 * 60
_RECIPE_MIRROR_LOAD_COOLDOWN_SECONDS = 30
_RECIPE_MIRROR_STORAGE_VERSION = 1
_RECIPE_MIRROR_STORAGE_KEY = f"{DOMAIN}.recipe_mirror_replay"
_MAX_RECIPE_ERROR_LENGTH = 500
_RECIPE_SERVICE_RUNTIME_KEY = f"{DOMAIN}_recipe_services"


@dataclass(slots=True)
class _MirrorReplayRecord:
    """One bounded persisted command outcome set."""

    config_entry_id: str
    todo_entity_id: str
    idempotency_key: str
    updated_at: float
    outcomes: dict[str, str]


@dataclass(slots=True)
class _RecipeServiceRuntime:
    """Runtime locks and persistent replay state for recipe todo mirroring."""

    store: Store | None = None
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    records: dict[tuple[str, str, str], _MirrorReplayRecord] = field(
        default_factory=dict
    )
    load_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    loaded: bool = False
    dirty: bool = False
    _load_last_attempt: float | None = None
    _load_clock: Callable[[], float] = time.monotonic

    def _load_is_due(self, now: float) -> bool:
        """Return whether another bounded storage load may start."""
        if self.loaded:
            return False
        if self._load_last_attempt is None:
            return True
        age = now - self._load_last_attempt
        return age < 0 or age >= _RECIPE_MIRROR_LOAD_COOLDOWN_SECONDS

    async def async_load(self) -> bool:
        """Load persisted replay outcomes when the retry cooldown permits."""
        if self.loaded:
            return True
        now = self._load_clock()
        if not self._load_is_due(now) and not self.load_lock.locked():
            return False

        async with self.load_lock:
            if self.loaded:
                return True
            now = self._load_clock()
            if not self._load_is_due(now):
                return False

            self._load_last_attempt = now
            payload: object = None
            if self.store is not None:
                try:
                    payload = await self.store.async_load()
                except Exception as err:
                    self.loaded = False
                    _LOGGER.warning(
                        "Could not load EverShelf recipe mirror replay state: %s",
                        type(err).__name__,
                    )
                    return False

            records, sanitized = _deserialize_mirror_records(
                payload,
                time.time(),
            )
            self.records = records
            self.dirty = sanitized
            self.loaded = True
            if self.dirty:
                async with self.write_lock:
                    await self._async_save_locked(time.time())
            return True

    def _prune_locked(self, now: float) -> None:
        """Prune expired and excess records in a deterministic order."""
        cutoff = now - _RECIPE_MIRROR_TTL_SECONDS
        expired: list[tuple[str, str, str]] = []
        for key, record in self.records.items():
            if record.updated_at > now:
                record.updated_at = now
                self.dirty = True
            if record.updated_at <= cutoff or not record.outcomes:
                expired.append(key)
        for key in expired:
            self.records.pop(key, None)
            self.dirty = True

        excess = len(self.records) - _MAX_RECIPE_MIRROR_REQUESTS
        if excess <= 0:
            return
        oldest = sorted(
            self.records,
            key=lambda key: (
                self.records[key].updated_at,
                key[0],
                key[1],
                key[2],
            ),
        )
        for key in oldest[:excess]:
            self.records.pop(key, None)
            self.dirty = True

    def _storage_payload_locked(self) -> dict[str, object]:
        """Return a deterministic, credential-free storage payload."""
        records = sorted(
            self.records.values(),
            key=lambda record: (
                record.updated_at,
                record.config_entry_id,
                record.todo_entity_id,
                record.idempotency_key,
            ),
        )
        return {
            "records": [
                {
                    "config_entry_id": record.config_entry_id,
                    "todo_entity_id": record.todo_entity_id,
                    "idempotency_key": record.idempotency_key,
                    "updated_at": record.updated_at,
                    "outcomes": [
                        {"name": name, "outcome": record.outcomes[name]}
                        for name in sorted(record.outcomes)
                    ],
                }
                for record in records
            ]
        }

    async def _async_save_locked(self, now: float) -> bool:
        """Save current replay state while the write lock is held."""
        if not self.loaded:
            return False
        self._prune_locked(now)
        if self.store is None:
            self.dirty = False
            return True
        payload = self._storage_payload_locked()
        try:
            await self.store.async_save(payload)
            persisted = await self.store.async_load()
        except Exception as err:
            self.dirty = True
            _LOGGER.warning(
                "Could not save EverShelf recipe mirror replay state: %s",
                type(err).__name__,
            )
            return False
        if persisted != payload:
            self.dirty = True
            _LOGGER.warning(
                "EverShelf recipe mirror replay state was not persisted"
            )
            return False
        self.dirty = False
        return True

    async def async_get_replay_outcomes(
        self,
        config_entry_id: str,
        todo_entity_id: str,
        idempotency_key: str,
    ) -> dict[str, str]:
        """Return successful outcomes for one replayed backend command."""
        if not await self.async_load():
            return {}
        async with self.write_lock:
            self._prune_locked(time.time())
            record = self.records.get(
                _mirror_record_key(
                    config_entry_id,
                    todo_entity_id,
                    idempotency_key,
                )
            )
            return dict(record.outcomes) if record is not None else {}

    async def async_record_outcomes(
        self,
        config_entry_id: str,
        todo_entity_id: str,
        idempotency_key: str,
        outcomes: Mapping[str, str],
    ) -> bool:
        """Merge successful normalized outcomes and persist them atomically."""
        if not await self.async_load():
            return False
        normalized_outcomes: dict[str, str] = {}
        for raw_name, outcome in outcomes.items():
            name = _normalize_todo_name(raw_name)[:_MAX_RECIPE_MIRROR_NAME_LENGTH]
            if name and outcome in ("added", "already_present"):
                normalized_outcomes[name] = outcome
        if not normalized_outcomes:
            return True

        async with self.write_lock:
            now = time.time()
            self._prune_locked(now)
            key = _mirror_record_key(
                config_entry_id,
                todo_entity_id,
                idempotency_key,
            )
            existing = self.records.get(key)
            merged = dict(existing.outcomes) if existing is not None else {}
            merged.update(normalized_outcomes)
            merged = {
                name: merged[name]
                for name in sorted(merged)[:_MAX_RECIPE_MIRROR_NAMES]
            }
            self.records[key] = _MirrorReplayRecord(
                config_entry_id=key[0],
                todo_entity_id=key[1],
                idempotency_key=key[2],
                updated_at=now,
                outcomes=merged,
            )
            self.dirty = True
            return await self._async_save_locked(now)

    async def async_flush(self) -> bool:
        """Finish any serialized write before the runtime is unloaded."""
        if not await self.async_load():
            return not self.dirty
        async with self.write_lock:
            if not self.dirty:
                return True
            return await self._async_save_locked(time.time())


def _strict_int(value: object) -> int:
    """Validate an integer without accepting booleans or numeric strings."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise vol.Invalid("value must be an integer")
    return value


def _todo_entity_id(value: object) -> str:
    """Validate one Home Assistant todo entity ID."""
    entity_id = cv.entity_id(value)
    if not entity_id.startswith("todo."):
        raise vol.Invalid("value must be a todo entity ID")
    return entity_id


_ADD_TO_SHOPPING_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("quantity", default=1): vol.All(vol.Coerce(float), vol.Range(min=0.001)),
        vol.Optional("unit"): cv.string,
    }
)

_MARK_USED_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("quantity"): vol.All(vol.Coerce(float), vol.Range(min=0.001)),
        vol.Optional("unit"): cv.string,
    }
)

_LIST_INVENTORY_SCHEMA = vol.Schema(
    {
        vol.Optional("location", default=""): vol.Any("", vol.In(_INVENTORY_LOCATIONS)),
        vol.Optional("q", default=""): cv.string,
        vol.Optional("search", default=""): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)

_RECIPE_QUERY_SCHEMA = vol.Schema(
    {
        vol.Required("kind"): vol.In(("browse", "recommendations")),
        vol.Optional("q", default=""): cv.string,
        vol.Optional("sort", default="availability"): vol.In(
            ("availability", "expiry", "alphabetical")
        ),
        vol.Optional("availability_weight", default=100): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
        vol.Optional("expiry_weight", default=25): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
        vol.Optional("minimum_coverage", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
        vol.Optional("expiring_within_days"): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=3650)
        ),
        vol.Optional("source", default=""): cv.string,
        vol.Optional("locale", default=""): cv.string,
        vol.Optional("limit"): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
        vol.Optional("cursor", default=""): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)

_RECIPE_HYDRATION_SCHEMA = vol.Schema(
    {
        vol.Optional("query", default=""): cv.string,
        vol.Optional("q", default=""): cv.string,
        vol.Optional("search_id", default=""): cv.string,
        vol.Optional("source", default="cookidoo"): cv.string,
        vol.Optional("locale", default=""): cv.string,
        vol.Optional("force", default=False): cv.boolean,
        vol.Optional("config_entry_id"): cv.string,
    }
)

_RECIPE_DETAIL_SCHEMA = vol.Schema(
    {
        vol.Required("recipe_id"): vol.All(_strict_int, vol.Range(min=1)),
        vol.Optional("config_entry_id"): cv.string,
    }
)

_RECIPE_GROCERY_SELECTION_SCHEMA = vol.Schema(
    {
        vol.Required("key"): vol.All(
            cv.string,
            str.strip,
            vol.Length(min=1, max=RECIPE_INGREDIENT_KEY_MAX_LENGTH),
            vol.Match(RECIPE_INGREDIENT_KEY_PATTERN.pattern),
        ),
        vol.Optional("position"): vol.All(_strict_int, vol.Range(min=0)),
    },
    extra=vol.PREVENT_EXTRA,
)

_RECIPE_GROCERY_ADD_SCHEMA = vol.Schema(
    {
        vol.Required("recipe_id"): vol.All(_strict_int, vol.Range(min=1)),
        vol.Required("selections"): vol.All(
            [_RECIPE_GROCERY_SELECTION_SCHEMA],
            vol.Length(min=1, max=RECIPE_GROCERY_MAX_SELECTIONS),
        ),
        vol.Required("idempotency_key"): vol.All(
            cv.string,
            str.strip,
            vol.Length(min=1, max=RECIPE_IDEMPOTENCY_KEY_MAX_LENGTH),
            vol.Match(RECIPE_IDEMPOTENCY_KEY_PATTERN.pattern),
        ),
        vol.Optional(
            "todo_entity_id",
            default=_DEFAULT_RECIPE_TODO_ENTITY_ID,
        ): _todo_entity_id,
        vol.Optional("config_entry_id"): cv.string,
    }
)

_RECIPE_INGREDIENT_FEEDBACK_BASE = {
    vol.Required("recipe_id"): vol.All(
        _strict_int,
        vol.Range(min=1),
    ),
    vol.Required("ingredient_key"): vol.All(
        cv.string,
        str.strip,
        vol.Length(min=1, max=RECIPE_INGREDIENT_KEY_MAX_LENGTH),
        vol.Match(RECIPE_INGREDIENT_KEY_PATTERN.pattern),
    ),
    vol.Required("position"): vol.All(
        _strict_int,
        vol.Range(min=0),
    ),
    vol.Required("feedback_token"): vol.All(
        cv.string,
        str.strip,
        vol.Match(RECIPE_FEEDBACK_TOKEN_PATTERN.pattern),
    ),
    vol.Required("idempotency_key"): vol.All(
        cv.string,
        str.strip,
        vol.Length(min=1, max=RECIPE_IDEMPOTENCY_KEY_MAX_LENGTH),
        vol.Match(RECIPE_IDEMPOTENCY_KEY_PATTERN.pattern),
    ),
    vol.Optional("config_entry_id"): cv.string,
}

_RECIPE_INGREDIENT_OVERRIDE_SCHEMA = vol.Schema(
    {
        **_RECIPE_INGREDIENT_FEEDBACK_BASE,
        vol.Required("availability"): vol.In(
            ("have", "missing", "clear")
        ),
    }
)

_RECIPE_IDENTITY_FEEDBACK_SCHEMA = vol.Schema(
    {
        **_RECIPE_INGREDIENT_FEEDBACK_BASE,
        vol.Required("verdict"): vol.In(("correct", "wrong")),
        vol.Required("target_kind"): vol.In(
            ("matched_product", "closest_match")
        ),
    }
)

_RECIPE_INGREDIENT_DECISION_SCHEMA = vol.Schema(
    {
        **_RECIPE_INGREDIENT_FEEDBACK_BASE,
        vol.Required("action"): vol.In(
            RECIPE_INGREDIENT_DECISION_ACTIONS
        ),
        vol.Optional("selected_product_id"): vol.All(
            _strict_int,
            vol.Range(min=1),
        ),
        vol.Optional("expected_target_product_id"): vol.All(
            _strict_int,
            vol.Range(min=1),
        ),
        vol.Optional(
            "action_origin",
            default="home_assistant",
        ): vol.In(RECIPE_INGREDIENT_ACTION_ORIGINS),
    }
)

_RECIPE_PLANNER_ADD_SCHEMA = vol.Schema(
    {
        vol.Required("recipe_id"): vol.All(
            _strict_int,
            vol.Range(min=1),
        ),
        vol.Required("date"): vol.All(
            cv.string,
            str.strip,
            vol.Match(r"^\d{4}-\d{2}-\d{2}$"),
        ),
        vol.Required("provider_action_token"): vol.All(
            cv.string,
            str.strip,
            vol.Match(RECIPE_FEEDBACK_TOKEN_PATTERN.pattern),
        ),
        vol.Required("idempotency_key"): vol.All(
            cv.string,
            str.strip,
            vol.Length(
                min=1,
                max=RECIPE_IDEMPOTENCY_KEY_MAX_LENGTH,
            ),
            vol.Match(RECIPE_IDEMPOTENCY_KEY_PATTERN.pattern),
        ),
        vol.Optional("config_entry_id"): cv.string,
    }
)

_DELETE_INVENTORY_SCHEMA = vol.Schema(
    {
        vol.Required("inventory_id"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("quantity"): vol.All(vol.Coerce(float), vol.Range(min=1)),
        vol.Optional("config_entry_id"): cv.string,
    }
)

_DELETE_INVENTORY_ITEM_SCHEMA = vol.Schema(
    {
        vol.Required("inventory_id"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("config_entry_id"): cv.string,
    }
)

_UPDATE_INVENTORY_ITEM_SCHEMA = vol.Schema(
    {
        vol.Required("inventory_id"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required("expiry_date"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)

_SET_INVENTORY_PREPARED_FOOD_SCHEMA = vol.Schema(
    {
        vol.Required("inventory_id"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required("prepared_food"): cv.boolean,
        vol.Optional("quantity"): vol.All(vol.Coerce(float), vol.Range(min=0.001)),
        vol.Optional("config_entry_id"): cv.string,
    }
)

_RESOLVE_BARCODE_SCHEMA = vol.Schema(
    {
        vol.Required("barcode"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)

_SUGGEST_LOCATION_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("mode", default="manual"): vol.In(_LOCATION_SUGGESTION_MODES),
        vol.Optional("barcode"): cv.string,
        vol.Optional("category"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)

_READ_EXPIRY_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Optional("image"): cv.string,
        vol.Optional("image_path"): cv.string,
        vol.Optional("camera_entity_id"): cv.entity_id,
        vol.Optional("config_entry_id"): cv.string,
    }
)

_ADD_SCANNED_ITEM_SCHEMA = vol.Schema(
    {
        vol.Optional("product_id"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required("name"): cv.string,
        vol.Optional("barcode"): cv.string,
        vol.Optional("brand"): cv.string,
        vol.Optional("category"): cv.string,
        vol.Optional("image_url"): cv.string,
        vol.Optional("unit"): cv.string,
        vol.Optional("default_quantity"): vol.Coerce(float),
        vol.Optional("notes"): cv.string,
        vol.Optional("package_unit"): cv.string,
        vol.Optional("package_size"): vol.Coerce(float),
        vol.Optional("shopping_name"): cv.string,
        vol.Optional("nutriments"): dict,
        vol.Optional("quantity", default=1): vol.All(
            vol.Coerce(float), vol.Range(min=0.001, max=100000)
        ),
        vol.Optional("location", default="dispensa"): vol.In(_INVENTORY_LOCATIONS),
        vol.Optional("expiry_date"): cv.string,
        vol.Optional("vacuum_sealed", default=False): cv.boolean,
        vol.Optional("expiry_user_set"): cv.boolean,
        vol.Optional("prepared_food", default=False): cv.boolean,
        vol.Optional("config_entry_id"): cv.string,
    }
)

_READ_EXPIRY_IMAGE_SOURCES = ("image", "image_path", "camera_entity_id")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EverShelf from a config entry."""
    coordinator = EverShelfCoordinator(
        hass,
        entry_id=entry.entry_id,
        url=entry.data[CONF_URL],
        token=entry.data.get(CONF_TOKEN, ""),
        scan_interval=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        expiry_days=entry.options.get(CONF_EXPIRY_DAYS, DEFAULT_EXPIRY_DAYS),
    )
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_load_capabilities()
    await _async_get_recipe_service_runtime(hass)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    # Register services once per HA instance
    if not hass.services.has_service(DOMAIN, "add_to_shopping"):

        async def _handle_add_to_shopping(call: ServiceCall) -> None:
            coord = _get_coordinator(hass, call)
            await coord.async_add_to_shopping(
                name=call.data["name"],
                quantity=call.data.get("quantity"),
                unit=call.data.get("unit"),
            )
            await coord.async_request_refresh()

        async def _handle_mark_used(call: ServiceCall) -> None:
            coord = _get_coordinator(hass, call)
            ok = await coord.async_mark_used(
                name=call.data["name"],
                quantity=float(call.data["quantity"]),
                unit=call.data.get("unit"),
            )
            if not ok:
                raise ServiceValidationError(
                    f"EverShelf: could not find or update item '{call.data['name']}'"
                )
            await coord.async_request_refresh()

        async def _handle_refresh(call: ServiceCall) -> None:
            coord = _get_coordinator(hass, call)
            await coord.async_request_refresh()

        async def _handle_suggest_recipe(call: ServiceCall) -> None:
            coord = _get_coordinator(hass, call)
            location = call.data.get("location", "")
            recipe = await coord.async_suggest_recipe(location=location)
            if recipe:
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": "EverShelf Recipe Suggestion",
                        "message": recipe,
                        "notification_id": "evershelf_recipe",
                    },
                )
            await coord.async_request_refresh()

        async def _handle_refresh_prices(call: ServiceCall) -> None:
            coord = _get_coordinator(hass, call)
            await coord.async_refresh_prices()
            await coord.async_request_refresh()

        async def _handle_clear_expired(call: ServiceCall) -> None:
            coord = _get_coordinator(hass, call)
            await coord.async_clear_expired()
            await coord.async_request_refresh()

        async def _handle_list_inventory(call: ServiceCall) -> dict:
            coord = _get_coordinator(hass, call)
            result = await coord.async_list_inventory(
                location=call.data.get("location", ""),
                search=call.data.get("q") or call.data.get("search", ""),
            )
            if result is None:
                raise ServiceValidationError("EverShelf: inventory list failed")
            return result

        async def _handle_recipe_query(call: ServiceCall) -> dict:
            coord = _get_coordinator(hass, call)
            if not coord.recipe_catalog_supported:
                raise ServiceValidationError(
                    "EverShelf: recipe catalog services require a backend with "
                    "the recipe_catalog_v2 capability"
                )
            data = dict(call.data)
            data.pop("config_entry_id", None)
            try:
                result = await coord.async_recipe_query(data)
            except ValueError as err:
                raise ServiceValidationError(f"EverShelf: {err}") from err
            if not result or result.get("success") is not True:
                message = (
                    result.get("message") or result.get("error")
                    if isinstance(result, dict)
                    else "recipe query failed"
                )
                raise ServiceValidationError(
                    f"EverShelf: {message or 'recipe query failed'}"
                )
            return result

        async def _handle_recipe_hydration(call: ServiceCall) -> dict:
            coord = _get_coordinator(hass, call)
            if not coord.recipe_catalog_supported:
                raise ServiceValidationError(
                    "EverShelf: recipe catalog services require a backend with "
                    "the recipe_catalog_v2 capability"
                )
            data = dict(call.data)
            data.pop("config_entry_id", None)
            try:
                result = await coord.async_recipe_hydration(data)
            except ValueError as err:
                raise ServiceValidationError(f"EverShelf: {err}") from err
            if not result or result.get("success") is not True:
                message = (
                    result.get("message") or result.get("error")
                    if isinstance(result, dict)
                    else "recipe hydration failed"
                )
                raise ServiceValidationError(
                    f"EverShelf: {message or 'recipe hydration failed'}"
                )
            return result

        async def _handle_recipe_detail(call: ServiceCall) -> dict[str, object]:
            return await _async_handle_recipe_detail(hass, call)

        async def _handle_recipe_ingredient_override(
            call: ServiceCall,
        ) -> dict[str, object]:
            return await _async_handle_recipe_ingredient_override(
                hass,
                call,
            )

        async def _handle_recipe_identity_feedback(
            call: ServiceCall,
        ) -> dict[str, object]:
            return await _async_handle_recipe_identity_feedback(
                hass,
                call,
            )

        async def _handle_recipe_ingredient_decision(
            call: ServiceCall,
        ) -> dict[str, object]:
            return await _async_handle_recipe_ingredient_decision(
                hass,
                call,
            )

        async def _handle_recipe_planner_add(
            call: ServiceCall,
        ) -> dict[str, object]:
            return await _async_handle_recipe_planner_add(
                hass,
                call,
            )

        async def _handle_recipe_grocery_add(
            call: ServiceCall,
        ) -> dict[str, object]:
            return await _async_handle_recipe_grocery_add(hass, call)

        async def _handle_delete_inventory(call: ServiceCall) -> dict:
            coord = _get_coordinator(hass, call)
            result = await coord.async_delete_inventory(
                int(call.data["inventory_id"]),
                call.data.get("quantity"),
            )
            if not result or result.get("success") is not True:
                message = (
                    result.get("error")
                    if isinstance(result, dict)
                    else "inventory delete failed"
                )
                raise ServiceValidationError(f"EverShelf: {message or 'inventory delete failed'}")
            await coord.async_request_refresh()
            return result

        async def _handle_delete_inventory_item(call: ServiceCall) -> dict:
            coord = _get_coordinator(hass, call)
            result = await coord.async_delete_inventory_item(int(call.data["inventory_id"]))
            if not result or result.get("success") is not True:
                message = (
                    result.get("error")
                    if isinstance(result, dict)
                    else "inventory item delete failed"
                )
                raise ServiceValidationError(f"EverShelf: {message or 'inventory item delete failed'}")
            await coord.async_request_refresh()
            return result

        async def _handle_update_inventory_item(call: ServiceCall) -> dict:
            coord = _get_coordinator(hass, call)
            result = await coord.async_update_inventory_item(
                int(call.data["inventory_id"]),
                call.data["expiry_date"],
            )
            if not result or result.get("success") is not True:
                message = (
                    result.get("error")
                    if isinstance(result, dict)
                    else "inventory item update failed"
                )
                raise ServiceValidationError(f"EverShelf: {message or 'inventory item update failed'}")
            await coord.async_request_refresh()
            return result

        async def _handle_set_inventory_prepared_food(call: ServiceCall) -> dict:
            coord = _get_coordinator(hass, call)
            result = await coord.async_set_inventory_prepared_food(
                int(call.data["inventory_id"]),
                bool(call.data["prepared_food"]),
                call.data.get("quantity"),
            )
            if not result or result.get("success") is not True:
                message = (
                    result.get("error")
                    if isinstance(result, dict)
                    else "prepared food update failed"
                )
                raise ServiceValidationError(f"EverShelf: {message or 'prepared food update failed'}")
            await coord.async_request_refresh()
            return result

        async def _handle_resolve_barcode(call: ServiceCall) -> dict:
            coord = _get_coordinator(hass, call)
            barcode = call.data["barcode"].strip()
            if not barcode:
                raise ServiceValidationError("EverShelf: barcode is required")
            result = await coord.async_resolve_barcode(barcode)
            if result is None:
                raise ServiceValidationError("EverShelf: barcode lookup failed")
            return result

        async def _handle_suggest_location(call: ServiceCall) -> dict:
            coord = _get_coordinator(hass, call)
            name = call.data["name"].strip()
            mode = call.data.get("mode", "manual")
            barcode = call.data.get("barcode", "").strip()
            if not name:
                raise ServiceValidationError("EverShelf: product name is required")
            if mode == "barcode" and not barcode:
                raise ServiceValidationError(
                    "EverShelf: barcode is required in barcode mode"
                )
            return await coord.async_suggest_location(
                mode=mode,
                name=name,
                barcode=barcode,
                category=call.data.get("category", "").strip(),
            )

        async def _handle_read_expiry_image(call: ServiceCall) -> dict:
            coord = _get_coordinator(hass, call)
            image_base64 = await _get_expiry_image_base64(hass, call)
            result = await coord.async_read_expiry_image(image_base64)
            if result is None:
                raise ServiceValidationError("EverShelf: expiry image read failed")
            return result

        async def _handle_add_scanned_item(call: ServiceCall) -> dict:
            coord = _get_coordinator(hass, call)
            item = dict(call.data)
            item.pop("config_entry_id", None)
            if not item["name"].strip():
                raise ServiceValidationError("EverShelf: product name is required")
            result = await coord.async_add_scanned_item(item)
            if not result or result.get("success") is not True:
                if isinstance(result, dict):
                    message = (
                        result.get("message")
                        or result.get("error")
                        or "scanned item add failed"
                    )
                else:
                    message = "scanned item add failed"
                raise ServiceValidationError(f"EverShelf: {message}")
            await coord.async_request_refresh()
            return result

        hass.services.async_register(
            DOMAIN, "add_to_shopping", _handle_add_to_shopping, schema=_ADD_TO_SHOPPING_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, "mark_used", _handle_mark_used, schema=_MARK_USED_SCHEMA
        )
        hass.services.async_register(DOMAIN, "refresh", _handle_refresh)
        hass.services.async_register(DOMAIN, "suggest_recipe", _handle_suggest_recipe)
        hass.services.async_register(DOMAIN, "refresh_prices", _handle_refresh_prices)
        hass.services.async_register(DOMAIN, "clear_expired", _handle_clear_expired)
        hass.services.async_register(
            DOMAIN,
            "list_inventory",
            _handle_list_inventory,
            schema=_LIST_INVENTORY_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        hass.services.async_register(
            DOMAIN,
            "recipe_query",
            _handle_recipe_query,
            schema=_RECIPE_QUERY_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "recipe_hydration",
            _handle_recipe_hydration,
            schema=_RECIPE_HYDRATION_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "recipe_detail",
            _handle_recipe_detail,
            schema=_RECIPE_DETAIL_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "recipe_ingredient_override",
            _handle_recipe_ingredient_override,
            schema=_RECIPE_INGREDIENT_OVERRIDE_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "recipe_identity_feedback",
            _handle_recipe_identity_feedback,
            schema=_RECIPE_IDENTITY_FEEDBACK_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "recipe_ingredient_decision",
            _handle_recipe_ingredient_decision,
            schema=_RECIPE_INGREDIENT_DECISION_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "recipe_planner_add",
            _handle_recipe_planner_add,
            schema=_RECIPE_PLANNER_ADD_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "recipe_grocery_add",
            _handle_recipe_grocery_add,
            schema=_RECIPE_GROCERY_ADD_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
        hass.services.async_register(
            DOMAIN,
            "delete_inventory",
            _handle_delete_inventory,
            schema=_DELETE_INVENTORY_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        hass.services.async_register(
            DOMAIN,
            "delete_inventory_item",
            _handle_delete_inventory_item,
            schema=_DELETE_INVENTORY_ITEM_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        hass.services.async_register(
            DOMAIN,
            "update_inventory_item",
            _handle_update_inventory_item,
            schema=_UPDATE_INVENTORY_ITEM_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        hass.services.async_register(
            DOMAIN,
            "set_inventory_prepared_food",
            _handle_set_inventory_prepared_food,
            schema=_SET_INVENTORY_PREPARED_FOOD_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        hass.services.async_register(
            DOMAIN,
            "resolve_barcode",
            _handle_resolve_barcode,
            schema=_RESOLVE_BARCODE_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        hass.services.async_register(
            DOMAIN,
            "suggest_location",
            _handle_suggest_location,
            schema=_SUGGEST_LOCATION_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        hass.services.async_register(
            DOMAIN,
            "read_expiry_image",
            _handle_read_expiry_image,
            schema=_READ_EXPIRY_IMAGE_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
        hass.services.async_register(
            DOMAIN,
            "add_scanned_item",
            _handle_add_scanned_item,
            schema=_ADD_SCANNED_ITEM_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an EverShelf config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    if not hass.data.get(DOMAIN):
        for svc in (
            "add_to_shopping",
            "mark_used",
            "refresh",
            "suggest_recipe",
            "refresh_prices",
            "clear_expired",
            "list_inventory",
            "recipe_query",
            "recipe_hydration",
            "recipe_detail",
            "recipe_ingredient_override",
            "recipe_identity_feedback",
            "recipe_ingredient_decision",
            "recipe_planner_add",
            "recipe_grocery_add",
            "delete_inventory",
            "delete_inventory_item",
            "update_inventory_item",
            "set_inventory_prepared_food",
            "resolve_barcode",
            "suggest_location",
            "read_expiry_image",
            "add_scanned_item",
        ):
            hass.services.async_remove(DOMAIN, svc)
        runtime = hass.data.get(_RECIPE_SERVICE_RUNTIME_KEY)
        if not isinstance(runtime, _RecipeServiceRuntime):
            hass.data.pop(_RECIPE_SERVICE_RUNTIME_KEY, None)
        elif await runtime.async_flush():
            hass.data.pop(_RECIPE_SERVICE_RUNTIME_KEY, None)
        else:
            _LOGGER.warning(
                "Retaining unsaved EverShelf recipe mirror state after unload"
            )

    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _get_coordinator(
    hass: HomeAssistant,
    call: ServiceCall,
    *,
    require_explicit_if_multiple: bool = False,
) -> EverShelfCoordinator:
    """Return the coordinator for a service call."""
    entries: dict[str, EverShelfCoordinator] = hass.data.get(DOMAIN, {})
    entry_id: str | None = call.data.get("config_entry_id")
    if entry_id:
        coord = entries.get(entry_id)
        if coord is None:
            raise ServiceValidationError(f"EverShelf: unknown config entry '{entry_id}'")
        return coord
    if not entries:
        raise ServiceValidationError("EverShelf: no instances configured")
    if require_explicit_if_multiple and len(entries) > 1:
        raise ServiceValidationError(
            "EverShelf: config_entry_id is required when multiple "
            "instances are configured"
        )
    return next(iter(entries.values()))


def _unsupported_capability_response(capability: str) -> dict[str, object]:
    """Return the structured response used for unsupported optional APIs."""
    return {
        "success": False,
        "error_kind": "unsupported",
        "error": "unsupported_capability",
        "required_capability": capability,
        "message": f"EverShelf backend does not advertise {capability}",
    }


def _unavailable_capability_response(capability: str) -> dict[str, object]:
    """Return a transient error when capability support cannot be confirmed."""
    return {
        "success": False,
        "error_kind": "unavailable",
        "error": "capability_probe_failed",
        "required_capability": capability,
        "message": (
            "Could not confirm whether the EverShelf backend advertises "
            f"{capability}"
        ),
    }


async def _async_capability_error(
    coordinator: EverShelfCoordinator,
    capability: str,
) -> dict[str, object] | None:
    """Return a structured capability error, or None when supported."""
    status = await coordinator.async_capability_status(capability)
    if status == CAPABILITY_SUPPORTED:
        return None
    if status == CAPABILITY_UNSUPPORTED:
        return _unsupported_capability_response(capability)
    return _unavailable_capability_response(capability)


def _effective_recipe_detail_response(
    result: Mapping[str, object],
    grocery_capability_status: str,
    ingredient_decision_status: str = CAPABILITY_SUPPORTED,
    planner_status: str = CAPABILITY_SUPPORTED,
) -> dict[str, object]:
    """Apply HA capability gates without changing backend-owned detail data."""
    response = dict(result)
    if result.get("success") is not True:
        return response

    detail = result.get("detail")
    if not isinstance(detail, Mapping):
        return response
    capabilities = detail.get("capabilities")
    if not isinstance(capabilities, Mapping):
        return response

    effective_capabilities = dict(capabilities)
    for key, status in (
        ("grocery_add", grocery_capability_status),
        ("ingredient_feedback_v2", ingredient_decision_status),
        ("planner", planner_status),
    ):
        if (
            effective_capabilities.get(key) is not True
            or status == CAPABILITY_SUPPORTED
        ):
            continue
        effective_capabilities[key] = False
        effective_capabilities[f"{key}_state"] = (
            "unsupported"
            if status == CAPABILITY_UNSUPPORTED
            else "unavailable"
        )
        effective_capabilities[f"{key}_reason"] = (
            "unsupported_capability"
            if status == CAPABILITY_UNSUPPORTED
            else "capability_probe_failed"
        )

    effective_detail = dict(detail)
    effective_detail["capabilities"] = effective_capabilities
    response["detail"] = effective_detail
    return response


async def _async_handle_recipe_detail(
    hass: HomeAssistant,
    call: ServiceCall,
) -> dict[str, object]:
    """Handle a bounded recipe detail response."""
    coordinator = _get_coordinator(hass, call)
    capability_error = await _async_capability_error(
        coordinator,
        _RECIPE_DETAIL_CAPABILITY,
    )
    if capability_error is not None:
        return capability_error

    try:
        result = await coordinator.async_recipe_detail(call.data["recipe_id"])
    except ValueError as err:
        raise ServiceValidationError(f"EverShelf: {err}") from err
    if result is None:
        raise ServiceValidationError("EverShelf: recipe detail request failed")

    detail = result.get("detail")
    capabilities = (
        detail.get("capabilities")
        if isinstance(detail, Mapping)
        else None
    )
    if result.get("success") is not True or not isinstance(
        capabilities,
        Mapping,
    ):
        return dict(result)

    grocery_capability_status = (
        await coordinator.async_capability_status(
            _RECIPE_GROCERY_CAPABILITY
        )
        if capabilities.get("grocery_add") is True
        else CAPABILITY_SUPPORTED
    )
    ingredient_decision_status = (
        await coordinator.async_capability_status(
            _RECIPE_INGREDIENT_DECISION_CAPABILITY
        )
        if capabilities.get("ingredient_feedback_v2") is True
        else CAPABILITY_SUPPORTED
    )
    planner_status = (
        await coordinator.async_capability_status(
            _RECIPE_PLANNER_CAPABILITY
        )
        if capabilities.get("planner") is True
        else CAPABILITY_SUPPORTED
    )
    return _effective_recipe_detail_response(
        result,
        grocery_capability_status,
        ingredient_decision_status,
        planner_status,
    )

async def _async_handle_recipe_ingredient_override(
    hass: HomeAssistant,
    call: ServiceCall,
) -> dict[str, object]:
    """Persist a display-only ingredient availability override."""
    coordinator = _get_coordinator(
        hass,
        call,
        require_explicit_if_multiple=True,
    )
    capability_error = await _async_capability_error(
        coordinator,
        _RECIPE_INGREDIENT_FEEDBACK_CAPABILITY,
    )
    if capability_error is not None:
        return capability_error
    data = dict(call.data)
    data.pop("config_entry_id", None)
    try:
        result = await coordinator.async_recipe_ingredient_override(
            data
        )
    except ValueError as err:
        raise ServiceValidationError(f"EverShelf: {err}") from err
    if result is None:
        raise ServiceValidationError(
            "EverShelf: ingredient override request failed"
        )
    return dict(result)


async def _async_handle_recipe_identity_feedback(
    hass: HomeAssistant,
    call: ServiceCall,
) -> dict[str, object]:
    """Record explicit ingredient identity feedback."""
    coordinator = _get_coordinator(
        hass,
        call,
        require_explicit_if_multiple=True,
    )
    capability_error = await _async_capability_error(
        coordinator,
        _RECIPE_INGREDIENT_FEEDBACK_CAPABILITY,
    )
    if capability_error is not None:
        return capability_error
    data = dict(call.data)
    data.pop("config_entry_id", None)
    try:
        result = await coordinator.async_recipe_identity_feedback(
            data
        )
    except ValueError as err:
        raise ServiceValidationError(f"EverShelf: {err}") from err
    if result is None:
        raise ServiceValidationError(
            "EverShelf: identity feedback request failed"
        )
    return dict(result)


async def _async_handle_recipe_ingredient_decision(
    hass: HomeAssistant,
    call: ServiceCall,
) -> dict[str, object]:
    """Submit one atomic ingredient decision v2 command."""
    coordinator = _get_coordinator(
        hass,
        call,
        require_explicit_if_multiple=True,
    )
    capability_error = await _async_capability_error(
        coordinator,
        _RECIPE_INGREDIENT_DECISION_CAPABILITY,
    )
    if capability_error is not None:
        return capability_error
    data = dict(call.data)
    data.pop("config_entry_id", None)
    try:
        result = await coordinator.async_recipe_ingredient_decision(
            data
        )
    except ValueError as err:
        raise ServiceValidationError(f"EverShelf: {err}") from err
    if result is None:
        raise ServiceValidationError(
            "EverShelf: ingredient decision request failed"
        )
    return dict(result)


async def _async_handle_recipe_planner_add(
    hass: HomeAssistant,
    call: ServiceCall,
) -> dict[str, object]:
    """Assign one Cookidoo recipe to an account-level My Week date."""
    coordinator = _get_coordinator(
        hass,
        call,
        require_explicit_if_multiple=True,
    )
    capability_error = await _async_capability_error(
        coordinator,
        _RECIPE_PLANNER_CAPABILITY,
    )
    if capability_error is not None:
        return capability_error
    data = dict(call.data)
    data.pop("config_entry_id", None)
    try:
        result = await coordinator.async_recipe_planner_add(data)
    except ValueError as err:
        raise ServiceValidationError(f"EverShelf: {err}") from err
    if result is None:
        raise ServiceValidationError(
            "EverShelf: recipe planner request failed"
        )
    return dict(result)


async def _async_handle_recipe_grocery_add(
    hass: HomeAssistant,
    call: ServiceCall,
) -> dict[str, object]:
    """Handle the backend mutation and the deduplicated HA todo mirror."""
    coordinator = _get_coordinator(
        hass,
        call,
        require_explicit_if_multiple=True,
    )
    runtime = await _async_get_recipe_service_runtime(hass)
    capability_error = await _async_capability_error(
        coordinator,
        _RECIPE_GROCERY_CAPABILITY,
    )
    if capability_error is not None:
        return capability_error

    todo_entity_id = _bounded_text(
        call.data.get(
            "todo_entity_id",
            _DEFAULT_RECIPE_TODO_ENTITY_ID,
        ),
        255,
    )
    try:
        await hass.services.async_call(
            "todo",
            "get_items",
            {"status": ["needs_action"]},
            target={"entity_id": todo_entity_id},
            blocking=True,
            context=call.context,
            return_response=True,
        )
    except HomeAssistantError as err:
        message = _bounded_text(
            str(err).strip(),
            _MAX_RECIPE_ERROR_LENGTH,
        )
        return _todo_read_failure(
            todo_entity_id,
            [],
            "todo_get_items_failed",
            message or "Could not read pending Home Assistant todo items",
        )

    backend_request: dict[str, object] = {
        "recipe_id": call.data["recipe_id"],
        "selections": call.data["selections"],
        "idempotency_key": call.data["idempotency_key"],
    }
    try:
        result = await coordinator.async_recipe_grocery_add(backend_request)
    except ValueError as err:
        raise ServiceValidationError(f"EverShelf: {err}") from err
    if result is None:
        raise ServiceValidationError("EverShelf: recipe grocery request failed")
    if result.get("success") is not True:
        return dict(result)

    await coordinator.async_request_refresh()
    if not isinstance(result.get("outcomes"), list):
        return {
            "success": False,
            "error_kind": "invalid_response",
            "error": "invalid_grocery_response",
            "message": "EverShelf returned no grocery outcome list",
        }
    backend_outcomes, outcomes_truncated = _bounded_backend_outcomes(result)
    backend_summary = _bounded_backend_summary(result, backend_outcomes)
    result_recipe_id = result.get("recipe_id")
    recipe_id = (
        result_recipe_id
        if (
            isinstance(result_recipe_id, int)
            and not isinstance(result_recipe_id, bool)
            and result_recipe_id > 0
        )
        else call.data["recipe_id"]
    )
    result_idempotency_key = _bounded_text(
        result.get("idempotency_key"),
        RECIPE_IDEMPOTENCY_KEY_MAX_LENGTH,
    )
    idempotency_key = (
        result_idempotency_key
        if RECIPE_IDEMPOTENCY_KEY_PATTERN.fullmatch(result_idempotency_key)
        else _bounded_text(
            call.data["idempotency_key"],
            RECIPE_IDEMPOTENCY_KEY_MAX_LENGTH,
        )
    )
    mirror = await _async_mirror_recipe_groceries(
        hass,
        coordinator,
        runtime,
        todo_entity_id,
        idempotency_key,
        result.get("replayed") is True,
        backend_outcomes,
        call.context,
    )
    mirror_summary = mirror["summary"]
    backend_failed = int(backend_summary["failed"])
    mirror_failed = int(mirror_summary["failed"])
    success = (
        not outcomes_truncated
        and backend_failed == 0
        and mirror_failed == 0
        and mirror["success"] is True
    )

    response: dict[str, object] = {
        "success": success,
        "recipe_id": recipe_id,
        "idempotency_key": idempotency_key,
        "replayed": result.get("replayed") is True,
        "outcomes": backend_outcomes,
        "ha_mirror": mirror,
        "summary": {
            "backend": backend_summary,
            "ha_mirror": mirror_summary,
        },
    }
    if outcomes_truncated:
        response["outcomes_truncated"] = True
    if not success:
        response["partial_failure"] = True
    return response


async def _async_get_recipe_service_runtime(
    hass: HomeAssistant,
) -> _RecipeServiceRuntime:
    """Return the per-HA runtime after one bounded replay-state load attempt."""
    runtime = hass.data.get(_RECIPE_SERVICE_RUNTIME_KEY)
    if not isinstance(runtime, _RecipeServiceRuntime):
        runtime = _RecipeServiceRuntime(
            store=Store(
                hass,
                _RECIPE_MIRROR_STORAGE_VERSION,
                _RECIPE_MIRROR_STORAGE_KEY,
            )
        )
        hass.data[_RECIPE_SERVICE_RUNTIME_KEY] = runtime
    await runtime.async_load()
    return runtime


def _mirror_record_key(
    config_entry_id: str,
    todo_entity_id: str,
    idempotency_key: str,
) -> tuple[str, str, str]:
    """Return one bounded persistent replay key."""
    return (
        config_entry_id[:_MAX_CONFIG_ENTRY_ID_LENGTH],
        todo_entity_id[:255],
        idempotency_key[:RECIPE_IDEMPOTENCY_KEY_MAX_LENGTH],
    )


def _deserialize_mirror_records(
    payload: object,
    now: float,
) -> tuple[dict[tuple[str, str, str], _MirrorReplayRecord], bool]:
    """Return sanitized, TTL-bounded records and whether cleanup was needed."""
    if payload is None:
        return {}, False
    if not isinstance(payload, Mapping):
        return {}, True
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        return {}, True

    records: dict[tuple[str, str, str], _MirrorReplayRecord] = {}
    sanitized = False
    cutoff = now - _RECIPE_MIRROR_TTL_SECONDS
    for raw_record in raw_records:
        if not isinstance(raw_record, Mapping):
            sanitized = True
            continue

        raw_entry_id = raw_record.get("config_entry_id")
        raw_todo_entity_id = raw_record.get("todo_entity_id")
        raw_idempotency_key = raw_record.get("idempotency_key")
        if not all(
            isinstance(value, str) and value
            for value in (
                raw_entry_id,
                raw_todo_entity_id,
                raw_idempotency_key,
            )
        ):
            sanitized = True
            continue
        key = _mirror_record_key(
            raw_entry_id,
            raw_todo_entity_id,
            raw_idempotency_key,
        )
        if (
            key
            != (
                raw_entry_id,
                raw_todo_entity_id,
                raw_idempotency_key,
            )
            or not key[1].startswith("todo.")
            or RECIPE_IDEMPOTENCY_KEY_PATTERN.fullmatch(key[2]) is None
        ):
            sanitized = True
            continue

        raw_updated_at = raw_record.get("updated_at")
        if (
            isinstance(raw_updated_at, bool)
            or not isinstance(raw_updated_at, (int, float))
            or not math.isfinite(float(raw_updated_at))
            or raw_updated_at <= 0
        ):
            sanitized = True
            continue
        updated_at = min(float(raw_updated_at), now)
        if updated_at != raw_updated_at:
            sanitized = True
        if updated_at <= cutoff:
            sanitized = True
            continue

        raw_outcomes = raw_record.get("outcomes")
        if not isinstance(raw_outcomes, list):
            sanitized = True
            continue
        outcomes: dict[str, str] = {}
        for raw_outcome in raw_outcomes:
            if not isinstance(raw_outcome, Mapping):
                sanitized = True
                continue
            raw_name = raw_outcome.get("name")
            outcome = raw_outcome.get("outcome")
            if (
                not isinstance(raw_name, str)
                or outcome not in ("added", "already_present")
            ):
                sanitized = True
                continue
            name = _normalize_todo_name(raw_name)[
                :_MAX_RECIPE_MIRROR_NAME_LENGTH
            ]
            if not name:
                sanitized = True
                continue
            if name != raw_name:
                sanitized = True
            if name in outcomes:
                sanitized = True
                outcomes[name] = min(outcomes[name], outcome)
            else:
                outcomes[name] = outcome

        if len(outcomes) > _MAX_RECIPE_MIRROR_NAMES:
            outcomes = {
                name: outcomes[name]
                for name in sorted(outcomes)[:_MAX_RECIPE_MIRROR_NAMES]
            }
            sanitized = True
        if not outcomes:
            sanitized = True
            continue

        record = _MirrorReplayRecord(
            config_entry_id=key[0],
            todo_entity_id=key[1],
            idempotency_key=key[2],
            updated_at=updated_at,
            outcomes=outcomes,
        )
        existing = records.get(key)
        if existing is None:
            records[key] = record
            continue
        sanitized = True
        existing_rank = (
            existing.updated_at,
            tuple(sorted(existing.outcomes.items())),
        )
        record_rank = (
            record.updated_at,
            tuple(sorted(record.outcomes.items())),
        )
        if record_rank > existing_rank:
            records[key] = record

    excess = len(records) - _MAX_RECIPE_MIRROR_REQUESTS
    if excess > 0:
        oldest = sorted(
            records,
            key=lambda key: (
                records[key].updated_at,
                key[0],
                key[1],
                key[2],
            ),
        )
        for key in oldest[:excess]:
            records.pop(key, None)
        sanitized = True
    return records, sanitized


def _bounded_text(value: object, maximum: int) -> str:
    """Return one bounded string value."""
    return value[:maximum] if isinstance(value, str) else ""


def _bounded_backend_outcomes(
    result: Mapping[str, object],
) -> tuple[list[dict[str, object]], bool]:
    """Copy only the documented bounded grocery outcome fields."""
    raw_outcomes = result.get("outcomes")
    if not isinstance(raw_outcomes, list):
        return [], False

    outcomes: list[dict[str, object]] = []
    for raw_outcome in raw_outcomes[:RECIPE_GROCERY_MAX_SELECTIONS]:
        if not isinstance(raw_outcome, Mapping):
            continue
        position = raw_outcome.get("position")
        bounded_position = (
            position
            if (
                isinstance(position, int)
                and not isinstance(position, bool)
                and position >= 0
            )
            else None
        )
        amount_text = raw_outcome.get("amount_text")
        outcomes.append(
            {
                "key": _bounded_text(
                    raw_outcome.get("key"),
                    RECIPE_INGREDIENT_KEY_MAX_LENGTH,
                ),
                "position": bounded_position,
                "outcome": _bounded_text(raw_outcome.get("outcome"), 32),
                "normalized_name": _bounded_text(
                    raw_outcome.get("normalized_name"),
                    200,
                ),
                "amount_text": (
                    _bounded_text(amount_text, 160)
                    if isinstance(amount_text, str)
                    else None
                ),
            }
        )
    return outcomes, len(raw_outcomes) > RECIPE_GROCERY_MAX_SELECTIONS


def _bounded_backend_summary(
    result: Mapping[str, object],
    outcomes: list[dict[str, object]],
) -> dict[str, int]:
    """Return the five documented bounded backend outcome counts."""
    names = ("added", "already_listed", "now_in_stock", "unresolved", "failed")
    counts = {name: 0 for name in names}
    for outcome in outcomes:
        name = outcome["outcome"]
        if isinstance(name, str) and name in counts:
            counts[name] += 1

    raw_summary = result.get("summary")
    if not isinstance(raw_summary, Mapping):
        return counts
    for name in names:
        value = raw_summary.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            counts[name] = min(value, RECIPE_GROCERY_MAX_SELECTIONS)
    return counts


def _normalize_todo_display_name(value: object) -> str:
    """Normalize Unicode and whitespace while preserving display casing."""
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split())


def _normalize_todo_name(value: object) -> str:
    """Normalize and case-fold one todo item name for deduplication."""
    return _normalize_todo_display_name(value).casefold()[
        :_MAX_RECIPE_MIRROR_NAME_LENGTH
    ]


def _todo_supports_description(
    hass: HomeAssistant,
    todo_entity_id: str,
) -> bool:
    """Return whether the target advertises safe todo description support."""
    state = hass.states.get(todo_entity_id)
    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, Mapping):
        return False
    supported_features = attributes.get("supported_features", 0)
    if isinstance(supported_features, bool) or not isinstance(
        supported_features,
        int,
    ):
        return False
    return bool(
        supported_features & int(TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM)
    )


def _extract_pending_todo_names(
    response: object,
    todo_entity_id: str,
) -> set[str]:
    """Extract normalized pending summaries from todo.get_items."""
    if not isinstance(response, Mapping):
        raise ValueError("todo.get_items returned an invalid response")
    entity_response = response.get(todo_entity_id)
    if not isinstance(entity_response, Mapping):
        raise ValueError("todo.get_items did not return the requested entity")
    items = entity_response.get("items")
    if not isinstance(items, list):
        raise ValueError("todo.get_items returned an invalid item list")

    pending: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        status = item.get("status")
        if isinstance(status, str) and status != "needs_action":
            continue
        name = _normalize_todo_name(item.get("summary"))
        if name:
            pending.add(name)
    return pending


def _base_mirror_outcome(
    backend_outcome: Mapping[str, object],
) -> dict[str, object]:
    """Return stable identity fields for one HA mirror outcome."""
    return {
        "key": backend_outcome.get("key", ""),
        "position": backend_outcome.get("position"),
        "name": backend_outcome.get("normalized_name", ""),
        "backend_outcome": backend_outcome.get("outcome", ""),
    }


def _mirror_summary(outcomes: list[dict[str, object]]) -> dict[str, int]:
    """Count bounded HA todo mirror outcomes."""
    counts = {"added": 0, "already_present": 0, "skipped": 0, "failed": 0}
    for outcome in outcomes:
        name = outcome.get("outcome")
        if isinstance(name, str) and name in counts:
            counts[name] += 1
    return counts


def _todo_read_failure(
    todo_entity_id: str,
    backend_outcomes: list[dict[str, object]],
    error: str,
    message: str,
) -> dict[str, object]:
    """Return per-item failures when the pending todo list cannot be read."""
    outcomes: list[dict[str, object]] = []
    for backend_outcome in backend_outcomes:
        outcome = _base_mirror_outcome(backend_outcome)
        if backend_outcome.get("outcome") in ("added", "already_listed"):
            outcome.update(
                {
                    "outcome": "failed",
                    "error": error,
                    "message": message,
                }
            )
        else:
            outcome.update(
                {
                    "outcome": "skipped",
                    "reason": f"backend_{backend_outcome.get('outcome') or 'unknown'}",
                }
            )
        outcomes.append(outcome)
    return {
        "success": False,
        "todo_entity_id": todo_entity_id,
        "error_kind": "unavailable",
        "error": error,
        "message": message,
        "outcomes": outcomes,
        "summary": _mirror_summary(outcomes),
    }


async def _async_mirror_recipe_groceries(
    hass: HomeAssistant,
    coordinator: EverShelfCoordinator,
    runtime: _RecipeServiceRuntime,
    todo_entity_id: str,
    idempotency_key: str,
    backend_replayed: bool,
    backend_outcomes: list[dict[str, object]],
    context: Context,
    todo_response: object | None = None,
) -> dict[str, object]:
    """Mirror eligible backend outcomes to one user-facing HA todo entity."""
    if not any(
        outcome.get("outcome") in ("added", "already_listed")
        for outcome in backend_outcomes
    ):
        outcomes: list[dict[str, object]] = []
        for backend_outcome in backend_outcomes:
            mirror_outcome = _base_mirror_outcome(backend_outcome)
            mirror_outcome.update(
                {
                    "outcome": "skipped",
                    "reason": (
                        f"backend_{backend_outcome.get('outcome') or 'unknown'}"
                    ),
                }
            )
            outcomes.append(mirror_outcome)
        return {
            "success": True,
            "todo_entity_id": todo_entity_id,
            "description_supported": _todo_supports_description(
                hass,
                todo_entity_id,
            ),
            "outcomes": outcomes,
            "summary": _mirror_summary(outcomes),
        }

    lock = runtime.locks.setdefault(todo_entity_id, asyncio.Lock())

    async with lock:
        replay_outcomes = (
            await runtime.async_get_replay_outcomes(
                coordinator.entry_id,
                todo_entity_id,
                idempotency_key,
            )
            if backend_replayed
            else {}
        )
        if todo_response is None:
            try:
                todo_response = await hass.services.async_call(
                    "todo",
                    "get_items",
                    {"status": ["needs_action"]},
                    target={"entity_id": todo_entity_id},
                    blocking=True,
                    context=context,
                    return_response=True,
                )
            except HomeAssistantError as err:
                message = _bounded_text(
                    str(err).strip(),
                    _MAX_RECIPE_ERROR_LENGTH,
                )
                return _todo_read_failure(
                    todo_entity_id,
                    backend_outcomes,
                    "todo_get_items_failed",
                    message
                    or "Could not read pending Home Assistant todo items",
                )

        try:
            pending_names = _extract_pending_todo_names(
                todo_response,
                todo_entity_id,
            )
        except ValueError as err:
            return _todo_read_failure(
                todo_entity_id,
                backend_outcomes,
                "todo_get_items_invalid_response",
                _bounded_text(str(err), _MAX_RECIPE_ERROR_LENGTH),
            )

        description_supported = _todo_supports_description(hass, todo_entity_id)
        outcomes: list[dict[str, object]] = []
        attempted: dict[str, dict[str, object]] = {}
        successful_outcomes: dict[str, str] = {}

        for backend_outcome in backend_outcomes:
            mirror_outcome = _base_mirror_outcome(backend_outcome)
            internal_outcome = backend_outcome.get("outcome")
            if internal_outcome not in ("added", "already_listed"):
                mirror_outcome.update(
                    {
                        "outcome": "skipped",
                        "reason": f"backend_{internal_outcome or 'unknown'}",
                    }
                )
                outcomes.append(mirror_outcome)
                continue

            display_name = _normalize_todo_display_name(
                _bounded_text(
                    backend_outcome.get("normalized_name"),
                    200,
                )
            )
            normalized_name = _normalize_todo_name(display_name)
            if not normalized_name:
                mirror_outcome.update(
                    {
                        "outcome": "failed",
                        "error": "invalid_backend_item_name",
                        "message": "EverShelf returned an empty grocery item name",
                    }
                )
                outcomes.append(mirror_outcome)
                continue

            if normalized_name in attempted:
                previous = attempted[normalized_name]
                previous_outcome = previous.get("outcome")
                if previous_outcome == "failed":
                    mirror_outcome.update(
                        {
                            "outcome": "failed",
                            "error": previous.get("error", "todo_add_item_failed"),
                            "message": previous.get(
                                "message",
                                "The matching todo add failed",
                            ),
                            "reason": "duplicate_selection",
                        }
                    )
                else:
                    mirror_outcome.update(
                        {
                            "outcome": "already_present",
                            "reason": "duplicate_selection",
                        }
                    )
                outcomes.append(mirror_outcome)
                continue

            persisted_outcome = replay_outcomes.get(normalized_name)
            if persisted_outcome is not None:
                mirror_outcome.update(
                    {
                        "outcome": "already_present",
                        "reason": "idempotent_replay",
                    }
                )
                successful_outcomes[normalized_name] = persisted_outcome
                attempted[normalized_name] = mirror_outcome
                outcomes.append(mirror_outcome)
                continue

            if normalized_name in pending_names:
                mirror_outcome.update(
                    {
                        "outcome": "already_present",
                        "reason": "pending_item_exists",
                    }
                )
                successful_outcomes[normalized_name] = "already_present"
                attempted[normalized_name] = mirror_outcome
                outcomes.append(mirror_outcome)
                continue

            service_data: dict[str, object] = {"item": display_name}
            amount_text = backend_outcome.get("amount_text")
            display_amount = _normalize_todo_display_name(amount_text)[:160]
            if (
                description_supported
                and display_amount
            ):
                service_data["description"] = (
                    f"Recipe source amount: {display_amount}"
                )

            try:
                await hass.services.async_call(
                    "todo",
                    "add_item",
                    service_data,
                    target={"entity_id": todo_entity_id},
                    blocking=True,
                    context=context,
                )
            except HomeAssistantError as err:
                message = _bounded_text(
                    str(err).strip(),
                    _MAX_RECIPE_ERROR_LENGTH,
                )
                mirror_outcome.update(
                    {
                        "outcome": "failed",
                        "error": "todo_add_item_failed",
                        "message": message or "Could not add Home Assistant todo item",
                    }
                )
            else:
                mirror_outcome["outcome"] = "added"
                pending_names.add(normalized_name)
                successful_outcomes[normalized_name] = "added"

            attempted[normalized_name] = mirror_outcome
            outcomes.append(mirror_outcome)

        persistence_ok = await runtime.async_record_outcomes(
            coordinator.entry_id,
            todo_entity_id,
            idempotency_key,
            successful_outcomes,
        )
        summary = _mirror_summary(outcomes)
        persistence_error = (
            None
            if persistence_ok
            else (
                "mirror_state_save_failed"
                if runtime.loaded
                else "mirror_state_load_failed"
            )
        )
        response: dict[str, object] = {
            "success": summary["failed"] == 0 and persistence_ok,
            "todo_entity_id": todo_entity_id,
            "description_supported": description_supported,
            "outcomes": outcomes,
            "summary": summary,
            "replay_persistence": {
                "status": "durable" if persistence_ok else "degraded",
                "durable": persistence_ok,
                **(
                    {"reason": persistence_error}
                    if persistence_error is not None
                    else {}
                ),
            },
        }
        if not persistence_ok:
            if runtime.dirty:
                hass.data.setdefault(_RECIPE_SERVICE_RUNTIME_KEY, runtime)
            response.update(
                {
                    "error_kind": "unavailable",
                    "error": persistence_error,
                    "message": (
                        "Todo items were processed with pending-list "
                        "deduplication, but durable replay safety is "
                        "temporarily unavailable"
                    ),
                }
            )
        return response


async def _get_expiry_image_base64(hass: HomeAssistant, call: ServiceCall) -> str:
    """Return base64 image data from exactly one supported service field."""
    provided = [
        source
        for source in _READ_EXPIRY_IMAGE_SOURCES
        if call.data.get(source)
    ]
    if len(provided) != 1:
        raise ServiceValidationError(
            "EverShelf: provide exactly one of image, image_path, or camera_entity_id"
        )

    source = provided[0]
    if source == "image":
        return _normalize_image_base64(call.data["image"])
    if source == "image_path":
        return await _image_path_to_base64(hass, call.data["image_path"])
    return await _camera_image_to_base64(hass, call.data["camera_entity_id"])


def _normalize_image_base64(value: str) -> str:
    """Accept plain base64 or a data URL and return normalized base64."""
    image = value.strip()
    if image.startswith("data:"):
        if "," not in image:
            raise ServiceValidationError("EverShelf: image data URL is malformed")
        image = image.split(",", 1)[1]

    image = "".join(image.split())
    if not image:
        raise ServiceValidationError("EverShelf: image is empty")

    try:
        decoded = base64.b64decode(image, validate=True)
    except binascii.Error as err:
        raise ServiceValidationError("EverShelf: image is not valid base64") from err
    if not decoded:
        raise ServiceValidationError("EverShelf: image is empty")

    return base64.b64encode(decoded).decode("ascii")


async def _image_path_to_base64(hass: HomeAssistant, image_path: str) -> str:
    """Read an allowlisted image path from the HA host and encode it."""
    path = Path(image_path)
    if not path.is_absolute():
        path = Path(hass.config.path(image_path))
    path = path.resolve()

    if not hass.config.is_allowed_path(str(path)):
        raise ServiceValidationError(
            f"EverShelf: image_path is not allowlisted by Home Assistant: {path}"
        )
    is_file = await hass.async_add_executor_job(path.is_file)
    if not is_file:
        raise ServiceValidationError(f"EverShelf: image_path does not exist: {path}")

    data = await hass.async_add_executor_job(path.read_bytes)
    if not data:
        raise ServiceValidationError(f"EverShelf: image_path is empty: {path}")

    return base64.b64encode(data).decode("ascii")


async def _camera_image_to_base64(hass: HomeAssistant, camera_entity_id: str) -> str:
    """Capture the current image from a HA camera entity and encode it."""
    from homeassistant.components import camera

    try:
        image = await camera.async_get_image(hass, camera_entity_id, timeout=10)
    except (HomeAssistantError, TimeoutError) as err:
        raise ServiceValidationError(
            f"EverShelf: could not capture camera image from {camera_entity_id}: {err}"
        ) from err

    content = image if isinstance(image, bytes) else getattr(image, "content", b"")
    if not content:
        raise ServiceValidationError(
            f"EverShelf: camera returned no image data: {camera_entity_id}"
        )

    return base64.b64encode(content).decode("ascii")
