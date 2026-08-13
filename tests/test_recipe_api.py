import importlib.util
from datetime import date, timedelta
from pathlib import Path


def _load_module(name: str, relative_path: str):
    path = Path(__file__).parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


api_auth = _load_module(
    "evershelf_api_auth",
    "custom_components/evershelf/api_auth.py",
)
recipe_api = _load_module(
    "evershelf_recipe_api",
    "custom_components/evershelf/recipe_api.py",
)
evershelf_params = api_auth.evershelf_params
evershelf_headers = api_auth.evershelf_headers
recipe_detail_request = recipe_api.recipe_detail_request
recipe_grocery_add_request = recipe_api.recipe_grocery_add_request
recipe_ingredient_override_request = (
    recipe_api.recipe_ingredient_override_request
)
recipe_identity_feedback_request = (
    recipe_api.recipe_identity_feedback_request
)
recipe_ingredient_decision_request = (
    recipe_api.recipe_ingredient_decision_request
)
recipe_planner_add_request = recipe_api.recipe_planner_add_request
recipe_hydration_request = recipe_api.recipe_hydration_request
recipe_query_request = recipe_api.recipe_query_request


def test_auth_token_never_enters_query_params() -> None:
    assert evershelf_params("secret", {"action": "recipe_catalog_search"}) == {
        "action": "recipe_catalog_search"
    }
    assert evershelf_headers("secret") == {
        "X-EverShelf-Request": "1",
        "X-API-Token": "secret",
    }


def test_recipe_browse_request_is_compact_and_bounded() -> None:
    action, params = recipe_query_request(
        {
            "kind": "browse",
            "q": "chicken",
            "sort": "expiry",
            "availability_weight": 80,
            "expiry_weight": 65,
            "minimum_coverage": 25,
            "expiring_within_days": 7,
            "limit": 50,
            "cursor": "opaque",
        }
    )
    assert action == "recipe_catalog_search"
    assert params == {
        "q": "chicken",
        "sort": "expiry",
        "availability_weight": 80,
        "expiry_weight": 65,
        "minimum_coverage": 25,
        "limit": 50,
        "fields": "card",
        "explain": "false",
        "expiring_within_days": 7,
        "cursor": "opaque",
    }


def test_recipe_recommendation_request_ignores_browse_fields() -> None:
    action, params = recipe_query_request(
        {
            "kind": "recommendations",
            "q": "ignored",
            "sort": "alphabetical",
            "source": "cookidoo",
            "locale": "en",
            "limit": 70,
        }
    )
    assert action == "recipe_catalog_recommendations"
    assert params == {"source": "cookidoo", "locale": "en", "limit": 70}


def test_recipe_hydration_enqueue_and_poll() -> None:
    assert recipe_hydration_request({"query": "chicken", "locale": "en"}) == (
        "POST",
        "recipe_catalog_discover",
        {
            "query": "chicken",
            "interactive": True,
            "exclude_cached": True,
            "limit": 20,
            "max_pages": 1,
            "force": False,
            "include_local_results": False,
            "locale": "en",
        },
    )
    assert recipe_hydration_request({"search_id": "cookidoo:abc"}) == (
        "GET",
        "recipe_jobs_status",
        {"search_id": "cookidoo:abc"},
    )
    assert recipe_hydration_request({"q": "chicken"})[2]["query"] == "chicken"


def test_recipe_hydration_requires_exactly_one_identity() -> None:
    for payload in ({}, {"query": "chicken", "search_id": "cookidoo:abc"}):
        try:
            recipe_hydration_request(payload)
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


def test_recipe_detail_request_uses_bounded_get_shape() -> None:
    assert recipe_detail_request({"recipe_id": 42, "ignored": "value"}) == (
        "GET",
        "recipe_catalog_detail",
        {"id": 42},
    )


def test_recipe_grocery_request_uses_bounded_post_shape() -> None:
    assert recipe_grocery_add_request(
        {
            "recipe_id": 42,
            "selections": [
                {"key": "ri:2:0123456789abcdef", "position": 2},
                {"key": "ri:3:fedcba9876543210"},
            ],
            "idempotency_key": "ha-command-42",
            "todo_entity_id": "todo.shopping_list",
            "config_entry_id": "entry",
        }
    ) == (
        "POST",
        "recipe_catalog_grocery_add",
        {
            "recipe_id": 42,
            "selections": [
                {"key": "ri:2:0123456789abcdef", "position": 2},
                {"key": "ri:3:fedcba9876543210"},
            ],
            "idempotency_key": "ha-command-42",
        },
    )


def test_recipe_feedback_requests_are_bounded() -> None:
    common = {
        "recipe_id": 42,
        "ingredient_key": "ri:2:0123456789abcdef",
        "position": 2,
        "feedback_token": "a" * 64,
        "idempotency_key": "feedback-42",
        "config_entry_id": "ignored",
    }
    assert recipe_ingredient_override_request(
        common | {"availability": "have"}
    ) == (
        "POST",
        "recipe_catalog_ingredient_override",
        {
            "recipe_id": 42,
            "ingredient_key": "ri:2:0123456789abcdef",
            "position": 2,
            "feedback_token": "a" * 64,
            "idempotency_key": "feedback-42",
            "availability": "have",
        },
    )
    assert recipe_identity_feedback_request(
        common
        | {
            "verdict": "wrong",
            "target_kind": "closest_match",
        }
    ) == (
        "POST",
        "recipe_catalog_identity_feedback",
        {
            "recipe_id": 42,
            "ingredient_key": "ri:2:0123456789abcdef",
            "position": 2,
            "feedback_token": "a" * 64,
            "idempotency_key": "feedback-42",
            "verdict": "wrong",
            "target_kind": "closest_match",
        },
    )


def test_recipe_decision_and_planner_requests_are_bounded() -> None:
    common = {
        "recipe_id": 42,
        "ingredient_key": "ri:2:0123456789abcdef",
        "position": 2,
        "feedback_token": "a" * 64,
        "idempotency_key": "decision-42",
    }
    assert recipe_ingredient_decision_request(
        common
        | {
            "action": "select_inventory_product",
            "selected_product_id": 91,
            "action_origin": "react_dashboard",
        }
    ) == (
        "POST",
        "recipe_catalog_ingredient_decision",
        {
            "recipe_id": 42,
            "ingredient_key": "ri:2:0123456789abcdef",
            "position": 2,
            "feedback_token": "a" * 64,
            "idempotency_key": "decision-42",
            "action": "select_inventory_product",
            "action_origin": "react_dashboard",
            "selected_product_id": 91,
        },
    )
    assert recipe_ingredient_decision_request(
        common
        | {
            "action": "reject_current_match",
            "expected_target_product_id": 91,
        }
    )[2]["expected_target_product_id"] == 91
    assert recipe_ingredient_decision_request(
        common | {"action": "assume_have"}
    )[2]["action_origin"] == "home_assistant"

    planned_date = (date.today() + timedelta(days=1)).isoformat()
    assert recipe_planner_add_request(
        {
            "recipe_id": 42,
            "date": planned_date,
            "provider_action_token": "b" * 64,
            "idempotency_key": "planner-42",
            "external_id": "must-not-pass-through",
        }
    ) == (
        "POST",
        "recipe_catalog_planner_add",
        {
            "recipe_id": 42,
            "date": planned_date,
            "provider_action_token": "b" * 64,
            "idempotency_key": "planner-42",
        },
    )


def test_recipe_request_builders_reject_invalid_inputs() -> None:
    invalid_detail = (0, -1, True, "1")
    for recipe_id in invalid_detail:
        try:
            recipe_detail_request({"recipe_id": recipe_id})
        except ValueError:
            pass
        else:
            raise AssertionError("expected invalid recipe ID")

    invalid_grocery = (
        {
            "recipe_id": 1,
            "selections": [],
            "idempotency_key": "valid",
        },
        {
            "recipe_id": 1,
            "selections": [{"key": "invalid"}],
            "idempotency_key": "valid",
        },
        {
            "recipe_id": 1,
            "selections": [{"key": "ri:0:0123456789abcdef", "position": -1}],
            "idempotency_key": "valid",
        },
        {
            "recipe_id": 1,
            "selections": [{"key": "ri:0:0123456789abcdef"}],
            "idempotency_key": "contains spaces",
        },
    )
    for payload in invalid_grocery:
        try:
            recipe_grocery_add_request(payload)
        except ValueError:
            pass
        else:
            raise AssertionError("expected invalid grocery request")

    invalid_feedback = (
        {
            "recipe_id": 1,
            "ingredient_key": "invalid",
            "position": 0,
            "feedback_token": "a" * 64,
            "idempotency_key": "valid",
            "availability": "have",
        },
        {
            "recipe_id": 1,
            "ingredient_key": "ri:0:0123456789abcdef",
            "position": 0,
            "feedback_token": "short",
            "idempotency_key": "valid",
            "availability": "have",
        },
    )
    for payload in invalid_feedback:
        try:
            recipe_ingredient_override_request(payload)
        except ValueError:
            pass
        else:
            raise AssertionError("expected invalid feedback request")

    for payload in (
        {
            "recipe_id": 1,
            "ingredient_key": "ri:0:0123456789abcdef",
            "position": 0,
            "feedback_token": "a" * 64,
            "idempotency_key": "valid",
            "action": "select_inventory_product",
        },
        {
            "recipe_id": 1,
            "ingredient_key": "ri:0:0123456789abcdef",
            "position": 0,
            "feedback_token": "a" * 64,
            "idempotency_key": "valid",
            "action": "assume_have",
            "selected_product_id": 5,
        },
    ):
        try:
            recipe_ingredient_decision_request(payload)
        except ValueError:
            pass
        else:
            raise AssertionError("expected invalid ingredient decision")

    for payload in (
        {
            "recipe_id": 1,
            "date": "2020-01-01",
            "provider_action_token": "b" * 64,
            "idempotency_key": "valid",
        },
        {
            "recipe_id": 1,
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "provider_action_token": "short",
            "idempotency_key": "valid",
        },
    ):
        try:
            recipe_planner_add_request(payload)
        except ValueError:
            pass
        else:
            raise AssertionError("expected invalid planner request")
