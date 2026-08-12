import asyncio
import copy
import importlib.util
from enum import Enum, IntFlag
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace

import pytest
import voluptuous as vol


def _install_homeassistant_stubs() -> type[Exception]:
    homeassistant = ModuleType("homeassistant")
    homeassistant.__path__ = []
    components = ModuleType("homeassistant.components")
    components.__path__ = []
    todo = ModuleType("homeassistant.components.todo")
    config_entries = ModuleType("homeassistant.config_entries")
    const = ModuleType("homeassistant.const")
    core = ModuleType("homeassistant.core")
    exceptions = ModuleType("homeassistant.exceptions")
    helpers = ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    config_validation = ModuleType("homeassistant.helpers.config_validation")
    aiohttp_client = ModuleType("homeassistant.helpers.aiohttp_client")
    storage = ModuleType("homeassistant.helpers.storage")
    update_coordinator = ModuleType("homeassistant.helpers.update_coordinator")

    class TodoListEntityFeature(IntFlag):
        CREATE_TODO_ITEM = 1
        DELETE_TODO_ITEM = 2
        UPDATE_TODO_ITEM = 4
        MOVE_TODO_ITEM = 8
        SET_DUE_DATE_ON_ITEM = 16
        SET_DUE_DATETIME_ON_ITEM = 32
        SET_DESCRIPTION_ON_ITEM = 64

    class Platform(Enum):
        SENSOR = "sensor"
        BINARY_SENSOR = "binary_sensor"
        BUTTON = "button"
        TODO = "todo"
        CALENDAR = "calendar"
        TEXT = "text"

    class SupportsResponse(Enum):
        NONE = "none"
        OPTIONAL = "optional"
        ONLY = "only"

    class HomeAssistantError(Exception):
        pass

    class ServiceValidationError(HomeAssistantError):
        pass

    class ServiceCall:
        def __init__(self, data):
            self.data = data
            self.context = Context()

    class HomeAssistant:
        pass

    class Context:
        pass

    class ConfigEntry:
        pass

    class DataUpdateCoordinator:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, hass, *_args, **_kwargs):
            self.hass = hass

    class UpdateFailed(Exception):
        pass

    class Store:
        def __init__(self, hass, version, key):
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self):
            self.hass.storage_load_calls += 1
            if self.hass.storage_load_error is not None:
                raise self.hass.storage_load_error
            return copy.deepcopy(self.hass.storage.get(self.key))

        async def async_save(self, data):
            self.hass.storage_save_calls += 1
            if self.hass.storage_save_error is not None:
                raise self.hass.storage_save_error
            self.hass.storage[self.key] = copy.deepcopy(data)

    def string(value):
        if not isinstance(value, str):
            raise vol.Invalid("expected string")
        return value

    def boolean(value):
        return vol.Boolean()(value)

    def entity_id(value):
        value = string(value)
        if re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", value) is None:
            raise vol.Invalid("invalid entity ID")
        return value

    todo.TodoListEntityFeature = TodoListEntityFeature
    config_entries.ConfigEntry = ConfigEntry
    const.Platform = Platform
    core.HomeAssistant = HomeAssistant
    core.Context = Context
    core.ServiceCall = ServiceCall
    core.SupportsResponse = SupportsResponse
    exceptions.HomeAssistantError = HomeAssistantError
    exceptions.ServiceValidationError = ServiceValidationError
    config_validation.string = string
    config_validation.boolean = boolean
    config_validation.entity_id = entity_id
    aiohttp_client.async_get_clientsession = lambda *_args, **_kwargs: None
    storage.Store = Store
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = UpdateFailed

    modules = {
        "homeassistant": homeassistant,
        "homeassistant.components": components,
        "homeassistant.components.todo": todo,
        "homeassistant.config_entries": config_entries,
        "homeassistant.const": const,
        "homeassistant.core": core,
        "homeassistant.exceptions": exceptions,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.config_validation": config_validation,
        "homeassistant.helpers.aiohttp_client": aiohttp_client,
        "homeassistant.helpers.storage": storage,
        "homeassistant.helpers.update_coordinator": update_coordinator,
    }
    sys.modules.update(modules)
    return HomeAssistantError


HOME_ASSISTANT_ERROR = _install_homeassistant_stubs()


def _load_integration():
    directory = (
        Path(__file__).parents[1] / "custom_components" / "evershelf"
    )
    spec = importlib.util.spec_from_file_location(
        "evershelf_recipe_service_tests",
        directory / "__init__.py",
        submodule_search_locations=[str(directory)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


integration = _load_integration()


class FakeStateMachine:
    def __init__(self, supported_features=0):
        self.supported_features = supported_features

    def get(self, _entity_id):
        return SimpleNamespace(
            attributes={"supported_features": self.supported_features}
        )


class FakeServices:
    def __init__(self):
        self.registered = {}
        self.todo_items = []
        self.add_calls = []
        self.events = []
        self.fail_add_names = set()
        self.get_error = None

    def has_service(self, domain, service):
        return (domain, service) in self.registered

    def async_register(
        self,
        domain,
        service,
        handler,
        schema=None,
        supports_response=None,
    ):
        self.registered[(domain, service)] = SimpleNamespace(
            handler=handler,
            schema=schema,
            supports_response=supports_response,
        )

    def async_remove(self, domain, service):
        self.registered.pop((domain, service), None)

    async def async_call(
        self,
        domain,
        service,
        data=None,
        *,
        target=None,
        blocking=False,
        context=None,
        return_response=False,
    ):
        data = data or {}
        self.events.append((domain, service))
        if domain == "todo" and service == "get_items":
            if self.get_error is not None:
                raise self.get_error
            entity_id = target["entity_id"]
            return {entity_id: {"items": list(self.todo_items)}}
        if domain == "todo" and service == "add_item":
            if data["item"] in self.fail_add_names:
                raise HOME_ASSISTANT_ERROR(f"failed to add {data['item']}")
            self.add_calls.append(
                {
                    "data": dict(data),
                    "target": dict(target),
                    "blocking": blocking,
                    "context": context,
                }
            )
            self.todo_items.append(
                {"summary": data["item"], "status": "needs_action"}
            )
            return None

        registration = self.registered[(domain, service)]
        validated = registration.schema(data) if registration.schema else data
        return await registration.handler(integration.ServiceCall(validated))


class FakeConfigEntries:
    def __init__(self):
        self.forwarded = []
        self.unloaded = []

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry.entry_id, list(platforms)))

    async def async_unload_platforms(self, entry, platforms):
        self.unloaded.append((entry.entry_id, list(platforms)))
        return True

    async def async_reload(self, _entry_id):
        return None


class FakeHass:
    def __init__(self, supported_features=0, storage=None):
        self.data = {}
        self.services = FakeServices()
        self.states = FakeStateMachine(supported_features)
        self.config_entries = FakeConfigEntries()
        self.storage = storage if storage is not None else {}
        self.storage_load_error = None
        self.storage_save_error = None
        self.storage_load_calls = 0
        self.storage_save_calls = 0


class FakeEntry:
    def __init__(self, entry_id="entry-1"):
        self.entry_id = entry_id
        self.data = {"url": "http://evershelf.local", "token": "secret"}
        self.options = {}
        self.unload_callbacks = []

    def add_update_listener(self, listener):
        return listener

    def async_on_unload(self, callback):
        self.unload_callbacks.append(callback)


class FakeCoordinator:
    def __init__(
        self,
        hass,
        entry_id="entry-1",
        url="http://evershelf.local",
        token="",
        **_kwargs,
    ):
        self.hass = hass
        self.entry_id = entry_id
        self.url = url
        self.token = token
        self.recipe_catalog_supported = True
        self.recipe_detail_supported = True
        self.recipe_grocery_supported = True
        self.capability_statuses = {}
        self.detail_response = {
            "success": True,
            "detail": {"schema_version": "recipe_detail_v1", "id": 7},
        }
        self.grocery_response = {
            "success": True,
            "recipe_id": 7,
            "idempotency_key": "command-7",
            "replayed": False,
            "outcomes": [],
            "summary": {
                "added": 0,
                "already_listed": 0,
                "now_in_stock": 0,
                "unresolved": 0,
                "failed": 0,
            },
        }
        self.events = []
        self.grocery_requests = []

    async def async_config_entry_first_refresh(self):
        return None

    async def async_load_capabilities(self):
        return None

    async def async_capability_status(self, capability):
        if capability in self.capability_statuses:
            return self.capability_statuses[capability]
        supported = {
            "recipe_catalog_v2": self.recipe_catalog_supported,
            "recipe_detail_v1": self.recipe_detail_supported,
            "recipe_grocery_v1": self.recipe_grocery_supported,
        }.get(capability, False)
        return "supported" if supported else "unsupported"

    async def async_recipe_detail(self, recipe_id):
        self.events.append(("backend_detail", recipe_id))
        return self.detail_response

    async def async_recipe_grocery_add(self, request):
        self.events.append(("backend_grocery", request["recipe_id"]))
        self.hass.services.events.append(("evershelf", "backend_grocery"))
        self.grocery_requests.append(dict(request))
        return self.grocery_response

    async def async_request_refresh(self):
        self.events.append(("refresh", None))
        self.hass.services.events.append(("evershelf", "refresh"))


def _service_call(data):
    return integration.ServiceCall(data)


def _backend_outcome(name, outcome, position, amount_text=None):
    return {
        "key": f"ri:{position}:{position:016x}",
        "position": position,
        "outcome": outcome,
        "normalized_name": name,
        "amount_text": amount_text,
    }


def _grocery_response(outcomes, *, replayed=False):
    summary = {
        "added": 0,
        "already_listed": 0,
        "now_in_stock": 0,
        "unresolved": 0,
        "failed": 0,
    }
    for outcome in outcomes:
        summary[outcome["outcome"]] += 1
    return {
        "success": True,
        "recipe_id": 7,
        "idempotency_key": "command-7",
        "replayed": replayed,
        "outcomes": outcomes,
        "summary": summary,
    }


def _rich_detail_response():
    return {
        "success": True,
        "detail": {
            "schema_version": "recipe_detail_v1",
            "id": 7,
            "title": "Tomato soup",
            "capabilities": {
                "grocery_add": True,
                "external_instructions": True,
            },
            "grocery": {
                "state": "missing",
                "ingredient_count": 2,
                "complete_count": 2,
                "missing_count": 1,
            },
            "ingredients": [
                {
                    "key": "ri:0:0123456789abcdef",
                    "position": 0,
                    "display_name": "Tomatoes",
                    "source_text": "400 g tomatoes",
                    "closest_match": {
                        "name": "Tomatoes",
                        "inventory_id": 12,
                    },
                },
                {
                    "key": "ri:1:fedcba9876543210",
                    "position": 1,
                    "display_name": "Vegetable stock",
                    "source_text": "500 ml vegetable stock",
                },
            ],
        },
    }


def test_recipe_service_schemas_are_strict() -> None:
    assert integration._RECIPE_DETAIL_SCHEMA({"recipe_id": 7}) == {
        "recipe_id": 7
    }
    valid = integration._RECIPE_GROCERY_ADD_SCHEMA(
        {
            "recipe_id": 7,
            "selections": [
                {"key": "ri:2:0123456789abcdef", "position": 2}
            ],
            "idempotency_key": "command-7",
        }
    )
    assert valid["todo_entity_id"] == "todo.shopping_list"

    invalid_payloads = (
        {"recipe_id": "7"},
        {"recipe_id": True},
        {
            "recipe_id": 7,
            "selections": [],
            "idempotency_key": "command-7",
        },
        {
            "recipe_id": 7,
            "selections": [{"key": "invalid"}],
            "idempotency_key": "command-7",
        },
        {
            "recipe_id": 7,
            "selections": [
                {
                    "key": "ri:2:0123456789abcdef",
                    "position": 2,
                    "extra": True,
                }
            ],
            "idempotency_key": "command-7",
        },
        {
            "recipe_id": 7,
            "selections": [{"key": "ri:2:0123456789abcdef"}],
            "idempotency_key": "bad key",
        },
        {
            "recipe_id": 7,
            "selections": [{"key": "ri:2:0123456789abcdef"}],
            "idempotency_key": "a" * 129,
        },
        {
            "recipe_id": 7,
            "selections": [{"key": "ri:2:0123456789abcdef"}],
            "idempotency_key": "command-7",
            "todo_entity_id": "sensor.not_a_todo",
        },
    )
    for payload in invalid_payloads:
        schema = (
            integration._RECIPE_DETAIL_SCHEMA
            if set(payload) == {"recipe_id"}
            else integration._RECIPE_GROCERY_ADD_SCHEMA
        )
        with pytest.raises(vol.Invalid):
            schema(payload)

    with pytest.raises(vol.Invalid):
        integration._RECIPE_GROCERY_ADD_SCHEMA(
            {
                "recipe_id": 7,
                "selections": [
                    {"key": "ri:2:0123456789abcdef"}
                    for _index in range(101)
                ],
                "idempotency_key": "command-7",
            }
        )


def test_recipe_detail_capability_response_and_structured_backend_error() -> None:
    hass = FakeHass()
    coordinator = FakeCoordinator(hass)
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}
    call = _service_call({"recipe_id": 7})

    coordinator.capability_statuses["recipe_detail_v1"] = "unavailable"
    unavailable = asyncio.run(
        integration._async_handle_recipe_detail(hass, call)
    )
    assert unavailable == {
        "success": False,
        "error_kind": "unavailable",
        "error": "capability_probe_failed",
        "required_capability": "recipe_detail_v1",
        "message": (
            "Could not confirm whether the EverShelf backend advertises "
            "recipe_detail_v1"
        ),
    }
    assert not coordinator.events

    coordinator.capability_statuses.pop("recipe_detail_v1")
    coordinator.recipe_detail_supported = False
    unsupported = asyncio.run(
        integration._async_handle_recipe_detail(hass, call)
    )
    assert unsupported == {
        "success": False,
        "error_kind": "unsupported",
        "error": "unsupported_capability",
        "required_capability": "recipe_detail_v1",
        "message": "EverShelf backend does not advertise recipe_detail_v1",
    }

    coordinator.recipe_detail_supported = True
    coordinator.detail_response = {
        "success": False,
        "error": "recipe_not_found",
        "http_status": 404,
    }
    assert asyncio.run(
        integration._async_handle_recipe_detail(hass, call)
    ) == coordinator.detail_response


def test_recipe_detail_returns_backend_envelope() -> None:
    hass = FakeHass()
    coordinator = FakeCoordinator(hass)
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}

    response = asyncio.run(
        integration._async_handle_recipe_detail(
            hass,
            _service_call({"recipe_id": 7}),
        )
    )
    assert response == {
        "success": True,
        "detail": {"schema_version": "recipe_detail_v1", "id": 7},
    }
    assert coordinator.events == [("backend_detail", 7)]


def test_recipe_detail_keeps_effective_grocery_capability_when_supported() -> None:
    hass = FakeHass()
    coordinator = FakeCoordinator(hass)
    coordinator.detail_response = _rich_detail_response()
    original = copy.deepcopy(coordinator.detail_response)
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}

    response = asyncio.run(
        integration._async_handle_recipe_detail(
            hass,
            _service_call({"recipe_id": 7}),
        )
    )

    assert response == original
    assert response["detail"]["capabilities"]["grocery_add"] is True
    assert coordinator.detail_response == original


def test_recipe_detail_preserves_additive_backend_fields() -> None:
    hass = FakeHass()
    coordinator = FakeCoordinator(hass)
    coordinator.detail_response = _rich_detail_response()
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}

    response = asyncio.run(
        integration._async_handle_recipe_detail(
            hass,
            _service_call({"recipe_id": 7}),
        )
    )

    assert response["detail"]["grocery"] == {
        "state": "missing",
        "ingredient_count": 2,
        "complete_count": 2,
        "missing_count": 1,
    }
    assert response["detail"]["ingredients"] == (
        coordinator.detail_response["detail"]["ingredients"]
    )
    assert response["detail"]["ingredients"][0]["display_name"] == "Tomatoes"
    assert response["detail"]["ingredients"][0]["source_text"] == (
        "400 g tomatoes"
    )
    assert response["detail"]["ingredients"][0]["closest_match"] == {
        "name": "Tomatoes",
        "inventory_id": 12,
    }
    assert "closest_match" not in response["detail"]["ingredients"][1]


def test_recipe_detail_disables_grocery_without_backend_capability() -> None:
    hass = FakeHass()
    coordinator = FakeCoordinator(hass)
    coordinator.recipe_grocery_supported = False
    coordinator.detail_response = _rich_detail_response()
    original = copy.deepcopy(coordinator.detail_response)
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}

    response = asyncio.run(
        integration._async_handle_recipe_detail(
            hass,
            _service_call({"recipe_id": 7}),
        )
    )

    assert response["success"] is True
    assert response["detail"]["capabilities"] == {
        "grocery_add": False,
        "external_instructions": True,
        "grocery_add_state": "unsupported",
        "grocery_add_reason": "unsupported_capability",
    }
    assert response["detail"]["grocery"] == original["detail"]["grocery"]
    assert response["detail"]["ingredients"] == original["detail"]["ingredients"]
    assert coordinator.detail_response == original
    assert response["detail"] is not coordinator.detail_response["detail"]
    assert (
        response["detail"]["capabilities"]
        is not coordinator.detail_response["detail"]["capabilities"]
    )


def test_recipe_detail_marks_grocery_probe_failure_as_unavailable() -> None:
    hass = FakeHass()
    coordinator = integration.EverShelfCoordinator(
        hass,
        entry_id="entry-1",
        url="http://evershelf.local",
        token="secret",
    )
    coordinator_module = sys.modules[coordinator.__class__.__module__]
    now = [5000.0]
    probe_responses = [
        {"capabilities": ["recipe_detail_v1"]},
        None,
    ]
    detail_response = _rich_detail_response()
    backend_calls = []

    async def fake_info():
        return probe_responses.pop(0)

    async def fake_detail(recipe_id):
        backend_calls.append(recipe_id)
        return detail_response

    coordinator._capability_clock = lambda: now[0]
    coordinator.async_get_info = fake_info
    coordinator.async_recipe_detail = fake_detail
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}

    async def scenario():
        assert await coordinator.async_load_capabilities() is True
        now[0] += coordinator_module._CAPABILITY_REFRESH_INTERVAL_SECONDS + 1
        return await integration._async_handle_recipe_detail(
            hass,
            _service_call({"recipe_id": 7}),
        )

    response = asyncio.run(scenario())

    assert response["success"] is True
    assert response["detail"]["capabilities"]["grocery_add"] is False
    assert (
        response["detail"]["capabilities"]["grocery_add_state"]
        == "unavailable"
    )
    assert response["detail"]["capabilities"]["grocery_add_reason"] == (
        "capability_probe_failed"
    )
    assert "error_kind" not in response
    assert backend_calls == [7]
    assert coordinator.capability_probe_failed is True
    assert detail_response["detail"]["capabilities"]["grocery_add"] is True


def test_coordinator_recipe_methods_use_request_builders() -> None:
    hass = FakeHass()
    coordinator = integration.EverShelfCoordinator(
        hass,
        entry_id="entry-1",
        url="http://evershelf.local",
        token="secret",
    )
    calls = []

    async def fake_get(action, params, **kwargs):
        calls.append(("GET", action, params, kwargs))
        return {"success": True}

    async def fake_post(action, payload, **kwargs):
        calls.append(("POST", action, payload, kwargs))
        return {"success": True}

    coordinator._get_json = fake_get
    coordinator._post_json = fake_post

    asyncio.run(coordinator.async_recipe_detail(7))
    asyncio.run(
        coordinator.async_recipe_grocery_add(
            {
                "recipe_id": 7,
                "selections": [
                    {"key": "ri:2:0123456789abcdef", "position": 2}
                ],
                "idempotency_key": "command-7",
            }
        )
    )
    assert calls == [
        (
            "GET",
            "recipe_catalog_detail",
            {"id": 7},
            {"timeout": 30, "preserve_errors": True},
        ),
        (
            "POST",
            "recipe_catalog_grocery_add",
            {
                "recipe_id": 7,
                "selections": [
                    {"key": "ri:2:0123456789abcdef", "position": 2}
                ],
                "idempotency_key": "command-7",
            },
            {"timeout": 30, "preserve_errors": True},
        ),
    ]


def test_coordinator_loads_recipe_capabilities_independently() -> None:
    hass = FakeHass()
    coordinator = integration.EverShelfCoordinator(
        hass,
        entry_id="entry-1",
        url="http://evershelf.local",
        token="secret",
    )

    async def fake_info():
        return {
            "capabilities": [
                "recipe_catalog_v2",
                "recipe_detail_v1",
                "recipe_grocery_v1",
            ]
        }

    coordinator.async_get_info = fake_info
    asyncio.run(coordinator.async_load_capabilities())
    assert coordinator.recipe_catalog_supported is True
    assert coordinator.recipe_detail_supported is True
    assert coordinator.recipe_grocery_supported is True


def test_capability_probe_initial_failure_recovers_after_cooldown() -> None:
    hass = FakeHass()
    coordinator = integration.EverShelfCoordinator(
        hass,
        entry_id="entry-1",
        url="http://evershelf.local",
        token="secret",
    )
    coordinator_module = sys.modules[coordinator.__class__.__module__]
    now = [1000.0]
    calls = []
    responses = [
        None,
        {"capabilities": ["recipe_detail_v1"]},
    ]

    async def fake_info():
        calls.append("probe")
        return responses.pop(0)

    coordinator._capability_clock = lambda: now[0]
    coordinator.async_get_info = fake_info

    async def scenario():
        assert (
            await coordinator.async_capability_status("recipe_detail_v1")
            == "unavailable"
        )
        assert (
            await coordinator.async_capability_status("recipe_detail_v1")
            == "unavailable"
        )
        now[0] += coordinator_module._CAPABILITY_PROBE_COOLDOWN_SECONDS + 1
        assert (
            await coordinator.async_capability_status("recipe_detail_v1")
            == "supported"
        )

    asyncio.run(scenario())
    assert calls == ["probe", "probe"]
    assert coordinator.capabilities_known is True
    assert coordinator.capability_probe_failed is False


def test_capability_probe_preserves_known_good_on_timeout() -> None:
    hass = FakeHass()
    coordinator = integration.EverShelfCoordinator(
        hass,
        entry_id="entry-1",
        url="http://evershelf.local",
        token="secret",
    )
    coordinator_module = sys.modules[coordinator.__class__.__module__]
    now = [2000.0]
    calls = 0

    async def fake_info():
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"capabilities": ["recipe_grocery_v1"]}
        raise asyncio.TimeoutError

    coordinator._capability_clock = lambda: now[0]
    coordinator.async_get_info = fake_info

    async def scenario():
        assert await coordinator.async_load_capabilities() is True
        now[0] += coordinator_module._CAPABILITY_REFRESH_INTERVAL_SECONDS + 1
        assert (
            await coordinator.async_capability_status("recipe_grocery_v1")
            == "supported"
        )

    asyncio.run(scenario())
    assert calls == 2
    assert coordinator.recipe_grocery_supported is True
    assert coordinator.capabilities == frozenset({"recipe_grocery_v1"})
    assert coordinator.capability_probe_failed is True


def test_capability_probe_successfully_proves_unsupported_until_stale() -> None:
    hass = FakeHass()
    coordinator = integration.EverShelfCoordinator(
        hass,
        entry_id="entry-1",
        url="http://evershelf.local",
        token="secret",
    )
    coordinator_module = sys.modules[coordinator.__class__.__module__]
    now = [2500.0]
    responses = [{}, None]

    async def fake_info():
        return responses.pop(0)

    coordinator._capability_clock = lambda: now[0]
    coordinator.async_get_info = fake_info

    async def scenario():
        assert (
            await coordinator.async_capability_status("recipe_detail_v1")
            == "unsupported"
        )
        now[0] += coordinator_module._CAPABILITY_REFRESH_INTERVAL_SECONDS + 1
        assert (
            await coordinator.async_capability_status("recipe_detail_v1")
            == "unavailable"
        )

    asyncio.run(scenario())
    assert coordinator.capabilities_known is True
    assert coordinator.capability_probe_failed is True


def test_recipe_detail_handler_recovers_from_initial_probe_failure() -> None:
    hass = FakeHass()
    coordinator = integration.EverShelfCoordinator(
        hass,
        entry_id="entry-1",
        url="http://evershelf.local",
        token="secret",
    )
    coordinator_module = sys.modules[coordinator.__class__.__module__]
    now = [2750.0]
    responses = [
        None,
        {"capabilities": ["recipe_detail_v1"]},
    ]
    backend_calls = []

    async def fake_info():
        return responses.pop(0)

    async def fake_detail(recipe_id):
        backend_calls.append(recipe_id)
        return {"success": True, "detail": {"id": recipe_id}}

    coordinator._capability_clock = lambda: now[0]
    coordinator.async_get_info = fake_info
    coordinator.async_recipe_detail = fake_detail
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}
    call = _service_call({"recipe_id": 7})

    async def scenario():
        unavailable = await integration._async_handle_recipe_detail(
            hass,
            call,
        )
        assert unavailable["error_kind"] == "unavailable"
        assert not backend_calls

        now[0] += coordinator_module._CAPABILITY_PROBE_COOLDOWN_SECONDS + 1
        recovered = await integration._async_handle_recipe_detail(hass, call)
        assert recovered == {"success": True, "detail": {"id": 7}}

    asyncio.run(scenario())
    assert backend_calls == [7]


def test_periodic_coordinator_update_detects_capability_upgrade() -> None:
    hass = FakeHass()
    coordinator = integration.EverShelfCoordinator(
        hass,
        entry_id="entry-1",
        url="http://evershelf.local",
        token="secret",
    )
    coordinator_module = sys.modules[coordinator.__class__.__module__]
    now = [3000.0]
    upgraded = [False]

    async def fake_info():
        return {
            "capabilities": (
                ["recipe_detail_v1"] if upgraded[0] else []
            )
        }

    class FakeResponse:
        def __init__(self, data):
            self.status = 200
            self.data = data

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def json(self, content_type=None):
            return copy.deepcopy(self.data)

    class FakeSession:
        def get(self, _url, *, params, **_kwargs):
            if params["action"] == "ha_sensor":
                return FakeResponse({"state": 0, "attributes": {}})
            if params["action"] == "ha_shopping_items":
                return FakeResponse({"items": []})
            raise AssertionError(f"unexpected action: {params['action']}")

    coordinator._capability_clock = lambda: now[0]
    coordinator.async_get_info = fake_info
    coordinator._session = lambda: FakeSession()

    async def scenario():
        assert await coordinator.async_load_capabilities() is True
        assert coordinator.recipe_detail_supported is False
        upgraded[0] = True
        now[0] += coordinator_module._CAPABILITY_REFRESH_INTERVAL_SECONDS + 1
        await coordinator._async_update_data()

    asyncio.run(scenario())
    assert coordinator.recipe_detail_supported is True


def test_capability_probe_has_cooldown_and_no_stampede() -> None:
    hass = FakeHass()
    coordinator = integration.EverShelfCoordinator(
        hass,
        entry_id="entry-1",
        url="http://evershelf.local",
        token="secret",
    )
    now = [4000.0]
    calls = 0

    async def fake_info():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return None

    coordinator._capability_clock = lambda: now[0]
    coordinator.async_get_info = fake_info

    async def scenario():
        statuses = await asyncio.gather(
            *(
                coordinator.async_capability_status("recipe_detail_v1")
                for _index in range(10)
            )
        )
        assert statuses == ["unavailable"] * 10

    asyncio.run(scenario())
    assert calls == 1


def test_grocery_add_deduplicates_pending_items_and_replays() -> None:
    hass = FakeHass(
        supported_features=int(
            integration.TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
        )
    )
    hass.services.todo_items = [
        {"summary": "  MILK  ", "status": "needs_action"},
        {"summary": "Completed item", "status": "completed"},
    ]
    coordinator = FakeCoordinator(hass)
    outcomes = [
        _backend_outcome("Milk", "added", 1, "1 l"),
        _backend_outcome("Bread", "added", 2, "500 g"),
        _backend_outcome(" bread ", "already_listed", 3, "500 g"),
        _backend_outcome("Salt", "now_in_stock", 4, None),
    ]
    coordinator.grocery_response = _grocery_response(outcomes)
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}
    call = _service_call(
        {
            "recipe_id": 7,
            "selections": [
                {"key": outcome["key"], "position": outcome["position"]}
                for outcome in outcomes
            ],
            "idempotency_key": "command-7",
            "todo_entity_id": "todo.shopping_list",
        }
    )

    first = asyncio.run(
        integration._async_handle_recipe_grocery_add(hass, call)
    )
    assert hass.services.events[:4] == [
        ("todo", "get_items"),
        ("evershelf", "backend_grocery"),
        ("evershelf", "refresh"),
        ("todo", "get_items"),
    ]
    assert len(hass.services.add_calls) == 1
    assert hass.services.add_calls[0]["data"] == {
        "item": "Bread",
        "description": "Recipe source amount: 500 g",
    }
    assert hass.services.add_calls[0]["context"] is call.context
    assert "quantity" not in hass.services.add_calls[0]["data"]
    assert first["success"] is True
    assert first["ha_mirror"]["summary"] == {
        "added": 1,
        "already_present": 2,
        "skipped": 1,
        "failed": 0,
    }
    assert first["ha_mirror"]["replay_persistence"] == {
        "status": "durable",
        "durable": True,
    }

    coordinator.grocery_response = _grocery_response(outcomes, replayed=True)
    second = asyncio.run(
        integration._async_handle_recipe_grocery_add(hass, call)
    )
    assert second["replayed"] is True
    assert len(hass.services.add_calls) == 1
    assert second["ha_mirror"]["summary"]["added"] == 0
    assert second["ha_mirror"]["summary"]["already_present"] == 3


def test_concurrent_grocery_adds_reread_todo_inside_mirror_lock() -> None:
    class BarrierCoordinator(FakeCoordinator):
        def __init__(self, hass):
            super().__init__(hass)
            self.arrivals = 0
            self.ready = asyncio.Event()

        async def async_recipe_grocery_add(self, request):
            self.arrivals += 1
            if self.arrivals == 2:
                self.ready.set()
            await self.ready.wait()
            return await super().async_recipe_grocery_add(request)

    hass = FakeHass()
    coordinator = BarrierCoordinator(hass)
    outcome = _backend_outcome("Tomato", "added", 1, "2 pz")
    coordinator.grocery_response = _grocery_response([outcome])
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}

    async def scenario():
        return await asyncio.gather(
            *(
                integration._async_handle_recipe_grocery_add(
                    hass,
                    _service_call(
                        {
                            "recipe_id": 7,
                            "selections": [
                                {
                                    "key": outcome["key"],
                                    "position": 1,
                                }
                            ],
                            "idempotency_key": f"command-{index}",
                            "todo_entity_id": "todo.shopping_list",
                        }
                    ),
                )
                for index in range(2)
            )
        )

    responses = asyncio.run(scenario())

    assert all(response["success"] is True for response in responses)
    assert [call["data"]["item"] for call in hass.services.add_calls] == [
        "Tomato"
    ]
    assert sorted(
        response["ha_mirror"]["summary"]["already_present"]
        for response in responses
    ) == [0, 1]


def test_grocery_replay_state_survives_reload_and_restart() -> None:
    storage = {}
    outcome = _backend_outcome("Bread", "added", 1, "500 g")
    call_data = {
        "recipe_id": 7,
        "selections": [
            {"key": outcome["key"], "position": outcome["position"]}
        ],
        "idempotency_key": "command-7",
        "todo_entity_id": "todo.shopping_list",
    }

    hass = FakeHass(storage=storage)
    coordinator = FakeCoordinator(hass)
    coordinator.grocery_response = _grocery_response([outcome])
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}
    first = asyncio.run(
        integration._async_handle_recipe_grocery_add(
            hass,
            _service_call(call_data),
        )
    )
    assert first["ha_mirror"]["summary"]["added"] == 1
    assert len(hass.services.add_calls) == 1
    assert integration._RECIPE_MIRROR_STORAGE_KEY in storage
    persisted_record = storage[
        integration._RECIPE_MIRROR_STORAGE_KEY
    ]["records"][0]
    assert set(persisted_record) == {
        "config_entry_id",
        "todo_entity_id",
        "idempotency_key",
        "updated_at",
        "outcomes",
    }
    assert persisted_record["outcomes"] == [
        {"name": "bread", "outcome": "added"}
    ]

    hass.data.pop(integration._RECIPE_SERVICE_RUNTIME_KEY)
    hass.services.add_calls.clear()
    coordinator.grocery_response = _grocery_response(
        [outcome],
        replayed=True,
    )
    reloaded = asyncio.run(
        integration._async_handle_recipe_grocery_add(
            hass,
            _service_call(call_data),
        )
    )
    assert not hass.services.add_calls
    assert reloaded["ha_mirror"]["outcomes"][0]["reason"] == "idempotent_replay"

    restarted_hass = FakeHass(storage=storage)
    restarted_coordinator = FakeCoordinator(restarted_hass)
    restarted_coordinator.grocery_response = _grocery_response(
        [outcome],
        replayed=True,
    )
    restarted_hass.data[integration.DOMAIN] = {
        restarted_coordinator.entry_id: restarted_coordinator
    }
    restarted = asyncio.run(
        integration._async_handle_recipe_grocery_add(
            restarted_hass,
            _service_call(call_data),
        )
    )
    assert not restarted_hass.services.add_calls
    assert restarted["ha_mirror"]["outcomes"][0]["reason"] == (
        "idempotent_replay"
    )


def test_new_idempotency_key_can_remirror_a_removed_item() -> None:
    storage = {}
    hass = FakeHass(storage=storage)
    coordinator = FakeCoordinator(hass)
    outcome = _backend_outcome("Bread", "added", 1)
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}

    coordinator.grocery_response = _grocery_response([outcome])
    asyncio.run(
        integration._async_handle_recipe_grocery_add(
            hass,
            _service_call(
                {
                    "recipe_id": 7,
                    "selections": [
                        {"key": outcome["key"], "position": 1}
                    ],
                    "idempotency_key": "command-7",
                    "todo_entity_id": "todo.shopping_list",
                }
            ),
        )
    )
    assert len(hass.services.add_calls) == 1

    hass.services.add_calls.clear()
    hass.services.todo_items.clear()
    coordinator.grocery_response = {
        **_grocery_response([outcome]),
        "idempotency_key": "command-8",
    }
    second = asyncio.run(
        integration._async_handle_recipe_grocery_add(
            hass,
            _service_call(
                {
                    "recipe_id": 7,
                    "selections": [
                        {"key": outcome["key"], "position": 1}
                    ],
                    "idempotency_key": "command-8",
                    "todo_entity_id": "todo.shopping_list",
                }
            ),
        )
    )
    assert second["ha_mirror"]["summary"]["added"] == 1
    assert len(hass.services.add_calls) == 1


def test_mirror_store_prunes_ttl_and_deterministically_evicts(
    monkeypatch,
) -> None:
    now = 2_000_000_000.0
    records = [
        {
            "config_entry_id": "entry-1",
            "todo_entity_id": "todo.shopping_list",
            "idempotency_key": "expired-command",
            "updated_at": now - integration._RECIPE_MIRROR_TTL_SECONDS,
            "outcomes": [{"name": "expired", "outcome": "added"}],
        }
    ]
    records.extend(
        {
            "config_entry_id": "entry-1",
            "todo_entity_id": "todo.shopping_list",
            "idempotency_key": f"command-{index:03d}",
            "updated_at": now - 1,
            "outcomes": [
                {"name": f"item {index:03d}", "outcome": "added"}
            ],
        }
        for index in range(integration._MAX_RECIPE_MIRROR_REQUESTS + 1)
    )
    storage = {
        integration._RECIPE_MIRROR_STORAGE_KEY: {"records": records}
    }
    hass = FakeHass(storage=storage)
    monkeypatch.setattr(integration.time, "time", lambda: now)

    runtime = asyncio.run(
        integration._async_get_recipe_service_runtime(hass)
    )
    assert len(runtime.records) == integration._MAX_RECIPE_MIRROR_REQUESTS
    assert (
        "entry-1",
        "todo.shopping_list",
        "expired-command",
    ) not in runtime.records
    assert (
        "entry-1",
        "todo.shopping_list",
        "command-000",
    ) not in runtime.records
    assert (
        "entry-1",
        "todo.shopping_list",
        "command-001",
    ) in runtime.records
    persisted = storage[integration._RECIPE_MIRROR_STORAGE_KEY]["records"]
    assert len(persisted) == integration._MAX_RECIPE_MIRROR_REQUESTS
    assert hass.storage_save_calls == 1


def test_mirror_store_sanitizes_corrupt_data() -> None:
    storage = {
        integration._RECIPE_MIRROR_STORAGE_KEY: {
            "records": "not-a-list"
        }
    }
    hass = FakeHass(storage=storage)
    runtime = asyncio.run(
        integration._async_get_recipe_service_runtime(hass)
    )
    assert runtime.records == {}
    assert storage[integration._RECIPE_MIRROR_STORAGE_KEY] == {
        "records": []
    }


def test_mirror_store_failed_initial_load_never_overwrites_or_records() -> None:
    stored_payload = {
        "records": [
            {
                "config_entry_id": "entry-1",
                "todo_entity_id": "todo.shopping_list",
                "idempotency_key": "command-old",
                "updated_at": integration.time.time(),
                "outcomes": [{"name": "bread", "outcome": "added"}],
            }
        ]
    }
    storage = {
        integration._RECIPE_MIRROR_STORAGE_KEY: copy.deepcopy(stored_payload)
    }
    hass = FakeHass(storage=storage)
    hass.storage_load_error = OSError("storage unavailable")

    async def scenario():
        runtime = await integration._async_get_recipe_service_runtime(hass)
        assert runtime.loaded is False
        assert runtime.records == {}
        assert runtime.dirty is False
        assert await runtime.async_record_outcomes(
            "entry-1",
            "todo.shopping_list",
            "command-new",
            {"milk": "added"},
        ) is False
        return runtime

    runtime = asyncio.run(scenario())
    assert runtime.loaded is False
    assert runtime.records == {}
    assert hass.storage_load_calls == 1
    assert hass.storage_save_calls == 0
    assert storage[integration._RECIPE_MIRROR_STORAGE_KEY] == stored_payload


def test_mirror_store_successful_reload_preserves_existing_records() -> None:
    stored_payload = {
        "records": [
            {
                "config_entry_id": "entry-1",
                "todo_entity_id": "todo.shopping_list",
                "idempotency_key": "command-old",
                "updated_at": integration.time.time() - 10,
                "outcomes": [{"name": "bread", "outcome": "added"}],
            }
        ]
    }
    storage = {
        integration._RECIPE_MIRROR_STORAGE_KEY: copy.deepcopy(stored_payload)
    }
    hass = FakeHass(storage=storage)
    hass.storage_load_error = OSError("storage unavailable")
    clock = [100.0]
    runtime = integration._RecipeServiceRuntime(
        store=integration.Store(
            hass,
            integration._RECIPE_MIRROR_STORAGE_VERSION,
            integration._RECIPE_MIRROR_STORAGE_KEY,
        ),
        _load_clock=lambda: clock[0],
    )

    async def scenario():
        assert await runtime.async_load() is False
        assert await runtime.async_record_outcomes(
            "entry-1",
            "todo.shopping_list",
            "command-new",
            {"milk": "added"},
        ) is False
        assert storage[integration._RECIPE_MIRROR_STORAGE_KEY] == stored_payload

        hass.storage_load_error = None
        clock[0] += integration._RECIPE_MIRROR_LOAD_COOLDOWN_SECONDS
        assert await runtime.async_record_outcomes(
            "entry-1",
            "todo.shopping_list",
            "command-new",
            {"milk": "added"},
        ) is True
        assert await runtime.async_get_replay_outcomes(
            "entry-1",
            "todo.shopping_list",
            "command-old",
        ) == {"bread": "added"}

    asyncio.run(scenario())
    assert runtime.loaded is True
    assert hass.storage_load_calls == 3
    assert hass.storage_save_calls == 1
    records = storage[integration._RECIPE_MIRROR_STORAGE_KEY]["records"]
    assert {
        (record["idempotency_key"], record["outcomes"][0]["name"])
        for record in records
    } == {
        ("command-old", "bread"),
        ("command-new", "milk"),
    }


def test_mirror_store_failed_loads_obey_retry_cooldown() -> None:
    hass = FakeHass()
    hass.storage_load_error = OSError("storage unavailable")
    clock = [100.0]
    runtime = integration._RecipeServiceRuntime(
        store=integration.Store(
            hass,
            integration._RECIPE_MIRROR_STORAGE_VERSION,
            integration._RECIPE_MIRROR_STORAGE_KEY,
        ),
        _load_clock=lambda: clock[0],
    )

    async def scenario():
        assert await runtime.async_load() is False
        assert await asyncio.gather(
            *(runtime.async_load() for _index in range(10))
        ) == [False] * 10
        clock[0] += integration._RECIPE_MIRROR_LOAD_COOLDOWN_SECONDS - 1
        assert await runtime.async_load() is False
        assert hass.storage_load_calls == 1

        clock[0] += 1
        assert await asyncio.gather(
            *(runtime.async_load() for _index in range(10))
        ) == [False] * 10

    asyncio.run(scenario())
    assert runtime.loaded is False
    assert hass.storage_load_calls == 2
    assert hass.storage_save_calls == 0


def test_mirror_store_serializes_concurrent_writes() -> None:
    class SlowStore:
        def __init__(self):
            self.active = 0
            self.maximum_active = 0
            self.data = None

        async def async_load(self):
            return copy.deepcopy(self.data)

        async def async_save(self, data):
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            await asyncio.sleep(0.01)
            self.data = copy.deepcopy(data)
            self.active -= 1

    store = SlowStore()
    runtime = integration._RecipeServiceRuntime(store=store)

    async def scenario():
        await asyncio.gather(
            runtime.async_record_outcomes(
                "entry-1",
                "todo.shopping_list",
                "command-1",
                {"bread": "added"},
            ),
            runtime.async_record_outcomes(
                "entry-1",
                "todo.shopping_list",
                "command-2",
                {"milk": "already_present"},
            ),
        )

    asyncio.run(scenario())
    assert store.maximum_active == 1
    assert len(store.data["records"]) == 2


def test_mirror_store_detects_silently_failed_write() -> None:
    class SwallowingStore:
        async def async_load(self):
            return None

        async def async_save(self, _data):
            return None

    runtime = integration._RecipeServiceRuntime(store=SwallowingStore())

    saved = asyncio.run(
        runtime.async_record_outcomes(
            "entry-1",
            "todo.shopping_list",
            "command-1",
            {"bread": "added"},
        )
    )

    assert saved is False
    assert runtime.dirty is True


def test_grocery_add_reports_replay_state_save_failure() -> None:
    hass = FakeHass()
    hass.storage_save_error = OSError("storage unavailable")
    coordinator = FakeCoordinator(hass)
    outcome = _backend_outcome("Bread", "added", 1)
    coordinator.grocery_response = _grocery_response([outcome])
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}

    response = asyncio.run(
        integration._async_handle_recipe_grocery_add(
            hass,
            _service_call(
                {
                    "recipe_id": 7,
                    "selections": [
                        {"key": outcome["key"], "position": 1}
                    ],
                    "idempotency_key": "command-7",
                    "todo_entity_id": "todo.shopping_list",
                }
            ),
        )
    )
    assert len(hass.services.add_calls) == 1
    assert response["success"] is False
    assert response["partial_failure"] is True
    assert response["ha_mirror"]["error"] == "mirror_state_save_failed"
    assert response["ha_mirror"]["replay_persistence"] == {
        "status": "degraded",
        "durable": False,
        "reason": "mirror_state_save_failed",
    }
    assert response["ha_mirror"]["summary"]["added"] == 1


def test_grocery_add_reports_degraded_replay_state_load_failure() -> None:
    stored_payload = {
        "records": [
            {
                "config_entry_id": "entry-1",
                "todo_entity_id": "todo.shopping_list",
                "idempotency_key": "command-7",
                "updated_at": integration.time.time(),
                "outcomes": [{"name": "bread", "outcome": "added"}],
            }
        ]
    }
    storage = {
        integration._RECIPE_MIRROR_STORAGE_KEY: copy.deepcopy(stored_payload)
    }
    hass = FakeHass(storage=storage)
    hass.storage_load_error = OSError("storage unavailable")
    coordinator = FakeCoordinator(hass)
    outcome = _backend_outcome("Bread", "added", 1)
    coordinator.grocery_response = _grocery_response(
        [outcome],
        replayed=True,
    )
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}

    response = asyncio.run(
        integration._async_handle_recipe_grocery_add(
            hass,
            _service_call(
                {
                    "recipe_id": 7,
                    "selections": [
                        {"key": outcome["key"], "position": 1}
                    ],
                    "idempotency_key": "command-7",
                    "todo_entity_id": "todo.shopping_list",
                }
            ),
        )
    )
    runtime = hass.data[integration._RECIPE_SERVICE_RUNTIME_KEY]
    assert len(hass.services.add_calls) == 1
    assert hass.storage_load_calls == 1
    assert hass.storage_save_calls == 0
    assert storage[integration._RECIPE_MIRROR_STORAGE_KEY] == stored_payload
    assert runtime.loaded is False
    assert runtime.records == {}
    assert response["success"] is False
    assert response["partial_failure"] is True
    assert response["replayed"] is True
    assert response["ha_mirror"]["error"] == "mirror_state_load_failed"
    assert response["ha_mirror"]["replay_persistence"] == {
        "status": "degraded",
        "durable": False,
        "reason": "mirror_state_load_failed",
    }
    assert "durable replay safety" in response["ha_mirror"]["message"]


def test_grocery_add_returns_partial_todo_failures() -> None:
    hass = FakeHass()
    hass.services.fail_add_names = {"Eggs"}
    coordinator = FakeCoordinator(hass)
    outcomes = [
        _backend_outcome("Eggs", "added", 1, "2"),
        _backend_outcome("Flour", "already_listed", 2, "500 g"),
    ]
    coordinator.grocery_response = _grocery_response(outcomes)
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}

    response = asyncio.run(
        integration._async_handle_recipe_grocery_add(
            hass,
            _service_call(
                {
                    "recipe_id": 7,
                    "selections": [
                        {"key": outcome["key"], "position": outcome["position"]}
                        for outcome in outcomes
                    ],
                    "idempotency_key": "command-7",
                    "todo_entity_id": "todo.shopping_list",
                }
            ),
        )
    )
    assert response["success"] is False
    assert response["partial_failure"] is True
    assert response["ha_mirror"]["summary"] == {
        "added": 1,
        "already_present": 0,
        "skipped": 0,
        "failed": 1,
    }
    failed = response["ha_mirror"]["outcomes"][0]
    assert failed["error"] == "todo_add_item_failed"
    assert "failed to add Eggs" in failed["message"]


def test_grocery_replay_retries_only_previous_mirror_failures() -> None:
    hass = FakeHass()
    hass.services.fail_add_names = {"Eggs"}
    coordinator = FakeCoordinator(hass)
    outcomes = [
        _backend_outcome("Eggs", "added", 1),
        _backend_outcome("Flour", "added", 2),
    ]
    coordinator.grocery_response = _grocery_response(outcomes)
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}
    call = _service_call(
        {
            "recipe_id": 7,
            "selections": [
                {"key": outcome["key"], "position": outcome["position"]}
                for outcome in outcomes
            ],
            "idempotency_key": "command-7",
            "todo_entity_id": "todo.shopping_list",
        }
    )

    first = asyncio.run(
        integration._async_handle_recipe_grocery_add(hass, call)
    )
    assert first["partial_failure"] is True
    assert [item["data"]["item"] for item in hass.services.add_calls] == [
        "Flour"
    ]

    hass.services.fail_add_names.clear()
    hass.services.add_calls.clear()
    coordinator.grocery_response = _grocery_response(
        outcomes,
        replayed=True,
    )
    replay = asyncio.run(
        integration._async_handle_recipe_grocery_add(hass, call)
    )
    assert replay["success"] is True
    assert [item["data"]["item"] for item in hass.services.add_calls] == [
        "Eggs"
    ]
    assert replay["ha_mirror"]["outcomes"][1]["reason"] == (
        "idempotent_replay"
    )


def test_grocery_add_preserves_backend_errors_after_todo_preflight() -> None:
    hass = FakeHass()
    coordinator = FakeCoordinator(hass)
    coordinator.grocery_response = {
        "success": False,
        "error": "idempotency_key_conflict",
        "http_status": 409,
    }
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}

    response = asyncio.run(
        integration._async_handle_recipe_grocery_add(
            hass,
            _service_call(
                {
                    "recipe_id": 7,
                    "selections": [
                        {"key": "ri:2:0123456789abcdef", "position": 2}
                    ],
                    "idempotency_key": "command-7",
                    "todo_entity_id": "todo.shopping_list",
                }
            ),
        )
    )
    assert response == coordinator.grocery_response
    assert hass.services.events == [
        ("todo", "get_items"),
        ("evershelf", "backend_grocery"),
    ]


def test_grocery_add_capability_gate_is_structured() -> None:
    hass = FakeHass()
    coordinator = FakeCoordinator(hass)
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}
    call = _service_call(
        {
            "recipe_id": 7,
            "selections": [
                {"key": "ri:2:0123456789abcdef", "position": 2}
            ],
            "idempotency_key": "command-7",
            "todo_entity_id": "todo.shopping_list",
        }
    )

    coordinator.capability_statuses["recipe_grocery_v1"] = "unavailable"
    unavailable = asyncio.run(
        integration._async_handle_recipe_grocery_add(hass, call)
    )
    assert unavailable["error_kind"] == "unavailable"
    assert unavailable["error"] == "capability_probe_failed"
    assert not hass.services.events

    coordinator.capability_statuses.pop("recipe_grocery_v1")
    coordinator.recipe_grocery_supported = False
    response = asyncio.run(
        integration._async_handle_recipe_grocery_add(hass, call)
    )
    assert response["success"] is False
    assert response["error"] == "unsupported_capability"
    assert response["required_capability"] == "recipe_grocery_v1"
    assert not hass.services.events


def test_grocery_add_requires_config_entry_with_multiple_instances() -> None:
    hass = FakeHass()
    first = FakeCoordinator(hass)
    second = FakeCoordinator(hass)
    second.entry_id = "entry-2"
    hass.data[integration.DOMAIN] = {
        first.entry_id: first,
        second.entry_id: second,
    }

    with pytest.raises(
        integration.ServiceValidationError,
        match="config_entry_id is required",
    ):
        asyncio.run(
            integration._async_handle_recipe_grocery_add(
                hass,
                _service_call(
                    {
                        "recipe_id": 7,
                        "selections": [
                            {
                                "key": "ri:2:0123456789abcdef",
                                "position": 2,
                            }
                        ],
                        "idempotency_key": "command-7",
                        "todo_entity_id": "todo.shopping_list",
                    }
                ),
            )
        )

    assert first.grocery_requests == []
    assert second.grocery_requests == []


def test_grocery_add_returns_structured_todo_read_failure() -> None:
    hass = FakeHass()
    hass.services.get_error = HOME_ASSISTANT_ERROR("todo entity unavailable")
    coordinator = FakeCoordinator(hass)
    outcomes = [_backend_outcome("Eggs", "added", 1, "2")]
    coordinator.grocery_response = _grocery_response(outcomes)
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}

    response = asyncio.run(
        integration._async_handle_recipe_grocery_add(
            hass,
            _service_call(
                {
                    "recipe_id": 7,
                    "selections": [
                        {"key": outcomes[0]["key"], "position": 1}
                    ],
                    "idempotency_key": "command-7",
                    "todo_entity_id": "todo.shopping_list",
                }
            ),
        )
    )
    assert response["success"] is False
    assert response["error"] == "todo_get_items_failed"
    assert response["summary"]["failed"] == 0
    assert coordinator.grocery_requests == []
    assert not hass.services.add_calls


def test_grocery_add_authorizes_todo_before_backend_outcomes() -> None:
    hass = FakeHass()
    coordinator = FakeCoordinator(hass)
    outcomes = [
        _backend_outcome("Salt", "now_in_stock", 1, None),
        _backend_outcome("Unknown", "unresolved", 2, None),
    ]
    coordinator.grocery_response = _grocery_response(outcomes)
    hass.data[integration.DOMAIN] = {coordinator.entry_id: coordinator}

    response = asyncio.run(
        integration._async_handle_recipe_grocery_add(
            hass,
            _service_call(
                {
                    "recipe_id": 7,
                    "selections": [
                        {"key": outcome["key"], "position": outcome["position"]}
                        for outcome in outcomes
                    ],
                    "idempotency_key": "command-7",
                    "todo_entity_id": "todo.shopping_list",
                }
            ),
        )
    )
    assert response["success"] is True
    assert response["ha_mirror"]["summary"]["skipped"] == 2
    assert hass.services.events[0] == ("todo", "get_items")


def test_setup_registers_and_unload_removes_recipe_services() -> None:
    hass = FakeHass()
    entry = FakeEntry()
    original_coordinator = integration.EverShelfCoordinator
    integration.EverShelfCoordinator = FakeCoordinator
    try:
        assert asyncio.run(integration.async_setup_entry(hass, entry)) is True
        assert hass.storage_load_calls == 1
        detail = hass.services.registered[
            (integration.DOMAIN, "recipe_detail")
        ]
        grocery = hass.services.registered[
            (integration.DOMAIN, "recipe_grocery_add")
        ]
        assert (
            detail.supports_response
            is integration.SupportsResponse.ONLY
        )
        assert (
            grocery.supports_response
            is integration.SupportsResponse.ONLY
        )
        hass.data[integration._RECIPE_SERVICE_RUNTIME_KEY] = (
            integration._RecipeServiceRuntime()
        )

        assert asyncio.run(integration.async_unload_entry(hass, entry)) is True
        assert (
            integration.DOMAIN,
            "recipe_detail",
        ) not in hass.services.registered
        assert (
            integration.DOMAIN,
            "recipe_grocery_add",
        ) not in hass.services.registered
        assert integration._RECIPE_SERVICE_RUNTIME_KEY not in hass.data
    finally:
        integration.EverShelfCoordinator = original_coordinator


def test_unload_retains_dirty_replay_state_when_flush_fails() -> None:
    hass = FakeHass()
    entry = FakeEntry()
    coordinator = FakeCoordinator(hass)
    hass.data[integration.DOMAIN] = {entry.entry_id: coordinator}

    async def scenario():
        runtime = await integration._async_get_recipe_service_runtime(hass)
        hass.storage_save_error = OSError("storage unavailable")
        saved = await runtime.async_record_outcomes(
            entry.entry_id,
            "todo.shopping_list",
            "command-7",
            {"bread": "added"},
        )
        assert saved is False
        assert runtime.dirty is True

        assert await integration.async_unload_entry(hass, entry) is True
        assert hass.data[integration._RECIPE_SERVICE_RUNTIME_KEY] is runtime

        hass.storage_save_error = None
        assert await runtime.async_flush() is True
        assert runtime.dirty is False

    asyncio.run(scenario())


def test_unload_during_failed_replay_load_is_safe() -> None:
    class DelayedFailStore:
        def __init__(self):
            self.started = asyncio.Event()
            self.finish = asyncio.Event()
            self.save_calls = 0

        async def async_load(self):
            self.started.set()
            await self.finish.wait()
            raise OSError("storage unavailable")

        async def async_save(self, _data):
            self.save_calls += 1

    hass = FakeHass()
    entry = FakeEntry()
    coordinator = FakeCoordinator(hass)
    hass.data[integration.DOMAIN] = {entry.entry_id: coordinator}

    async def scenario():
        store = DelayedFailStore()
        runtime = integration._RecipeServiceRuntime(store=store)
        hass.data[integration._RECIPE_SERVICE_RUNTIME_KEY] = runtime
        load_task = asyncio.create_task(runtime.async_load())
        await store.started.wait()
        unload_task = asyncio.create_task(
            integration.async_unload_entry(hass, entry)
        )
        await asyncio.sleep(0)
        assert unload_task.done() is False
        store.finish.set()

        assert await load_task is False
        assert await unload_task is True
        assert runtime.loaded is False
        assert runtime.dirty is False
        assert store.save_calls == 0
        assert integration._RECIPE_SERVICE_RUNTIME_KEY not in hass.data

    asyncio.run(scenario())
