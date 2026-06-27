"""EverShelf Home Assistant integration."""
from __future__ import annotations

import base64
import binascii
import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_EXPIRY_DAYS,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_URL,
    DEFAULT_EXPIRY_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import EverShelfCoordinator

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
        vol.Optional("config_entry_id"): cv.string,
    }
)

_RESOLVE_BARCODE_SCHEMA = vol.Schema(
    {
        vol.Required("barcode"): cv.string,
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
            result = await coord.async_list_inventory(call.data.get("location", ""))
            if result is None:
                raise ServiceValidationError("EverShelf: inventory list failed")
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
            "resolve_barcode",
            _handle_resolve_barcode,
            schema=_RESOLVE_BARCODE_SCHEMA,
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
            "resolve_barcode",
            "read_expiry_image",
            "add_scanned_item",
        ):
            hass.services.async_remove(DOMAIN, svc)

    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _get_coordinator(hass: HomeAssistant, call: ServiceCall) -> EverShelfCoordinator:
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
    return next(iter(entries.values()))


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
