"""Pure request builders for EverShelf recipe catalog services."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
import re
from typing import Any

RECIPE_QUERY_KINDS = ("browse", "recommendations")
RECIPE_SORTS = ("availability", "expiry", "alphabetical")
RECIPE_GROCERY_MAX_SELECTIONS = 100
RECIPE_INGREDIENT_KEY_MAX_LENGTH = 64
RECIPE_IDEMPOTENCY_KEY_MAX_LENGTH = 128
RECIPE_INGREDIENT_KEY_PATTERN = re.compile(r"^ri:\d+:[a-f0-9]{16}$")
RECIPE_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
RECIPE_FEEDBACK_TOKEN_PATTERN = re.compile(r"^[a-f0-9]{64}$")
RECIPE_INGREDIENT_DECISION_ACTIONS = (
    "assume_have",
    "select_inventory_product",
    "reject_current_match",
)
RECIPE_INGREDIENT_ACTION_ORIGINS = (
    "home_assistant",
    "react_dashboard",
    "operator",
)


def _positive_int(value: object, field: str) -> int:
    """Return a strict positive integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def recipe_detail_request(
    data: Mapping[str, object],
) -> tuple[str, str, dict[str, object]]:
    """Return the bounded GET request for one recipe detail projection."""
    recipe_id = _positive_int(data.get("recipe_id"), "recipe_id")
    return "GET", "recipe_catalog_detail", {"id": recipe_id}


def recipe_grocery_add_request(
    data: Mapping[str, object],
) -> tuple[str, str, dict[str, object]]:
    """Return the bounded POST request for selected missing ingredients."""
    recipe_id = _positive_int(data.get("recipe_id"), "recipe_id")

    idempotency_value = data.get("idempotency_key")
    if not isinstance(idempotency_value, str):
        raise ValueError("idempotency_key must be a string")
    idempotency_key = idempotency_value.strip()
    if (
        not idempotency_key
        or len(idempotency_key) > RECIPE_IDEMPOTENCY_KEY_MAX_LENGTH
        or RECIPE_IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key) is None
    ):
        raise ValueError("idempotency_key is invalid")

    raw_selections = data.get("selections")
    if (
        not isinstance(raw_selections, list)
        or not 1 <= len(raw_selections) <= RECIPE_GROCERY_MAX_SELECTIONS
    ):
        raise ValueError("selections must contain between 1 and 100 items")

    selections: list[dict[str, object]] = []
    for raw_selection in raw_selections:
        if not isinstance(raw_selection, Mapping):
            raise ValueError("selection must be an object")
        if set(raw_selection) - {"key", "position"}:
            raise ValueError("selection contains unsupported fields")

        key_value = raw_selection.get("key")
        if not isinstance(key_value, str):
            raise ValueError("selection key must be a string")
        key = key_value.strip()
        if (
            not key
            or len(key) > RECIPE_INGREDIENT_KEY_MAX_LENGTH
            or RECIPE_INGREDIENT_KEY_PATTERN.fullmatch(key) is None
        ):
            raise ValueError("selection key is invalid")

        selection: dict[str, object] = {"key": key}
        if "position" in raw_selection:
            position = raw_selection["position"]
            if isinstance(position, bool) or not isinstance(position, int) or position < 0:
                raise ValueError("selection position must be a nonnegative integer")
            selection["position"] = position
        selections.append(selection)

    return (
        "POST",
        "recipe_catalog_grocery_add",
        {
            "recipe_id": recipe_id,
            "selections": selections,
            "idempotency_key": idempotency_key,
        },
    )


def _recipe_feedback_base(
    data: Mapping[str, object],
) -> dict[str, object]:
    recipe_id = _positive_int(data.get("recipe_id"), "recipe_id")
    position = data.get("position")
    if isinstance(position, bool) or not isinstance(position, int) or position < 0:
        raise ValueError("position must be a nonnegative integer")
    key_value = data.get("ingredient_key")
    if not isinstance(key_value, str):
        raise ValueError("ingredient_key must be a string")
    ingredient_key = key_value.strip()
    if (
        not ingredient_key
        or len(ingredient_key) > RECIPE_INGREDIENT_KEY_MAX_LENGTH
        or RECIPE_INGREDIENT_KEY_PATTERN.fullmatch(ingredient_key) is None
    ):
        raise ValueError("ingredient_key is invalid")
    token_value = data.get("feedback_token")
    if not isinstance(token_value, str):
        raise ValueError("feedback_token must be a string")
    feedback_token = token_value.strip()
    if RECIPE_FEEDBACK_TOKEN_PATTERN.fullmatch(feedback_token) is None:
        raise ValueError("feedback_token is invalid")
    idempotency_value = data.get("idempotency_key")
    if not isinstance(idempotency_value, str):
        raise ValueError("idempotency_key must be a string")
    idempotency_key = idempotency_value.strip()
    if (
        not idempotency_key
        or len(idempotency_key) > RECIPE_IDEMPOTENCY_KEY_MAX_LENGTH
        or RECIPE_IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key) is None
    ):
        raise ValueError("idempotency_key is invalid")
    return {
        "recipe_id": recipe_id,
        "ingredient_key": ingredient_key,
        "position": position,
        "feedback_token": feedback_token,
        "idempotency_key": idempotency_key,
    }


def recipe_ingredient_override_request(
    data: Mapping[str, object],
) -> tuple[str, str, dict[str, object]]:
    """Return the bounded availability-override request."""
    payload = _recipe_feedback_base(data)
    availability = str(data.get("availability", "")).strip().lower()
    if availability not in {"have", "missing", "clear"}:
        raise ValueError("availability is invalid")
    payload["availability"] = availability
    return "POST", "recipe_catalog_ingredient_override", payload


def recipe_identity_feedback_request(
    data: Mapping[str, object],
) -> tuple[str, str, dict[str, object]]:
    """Return the bounded explicit identity-feedback request."""
    payload = _recipe_feedback_base(data)
    verdict = str(data.get("verdict", "")).strip().lower()
    target_kind = str(data.get("target_kind", "")).strip().lower()
    if verdict not in {"correct", "wrong"}:
        raise ValueError("verdict is invalid")
    if target_kind not in {"matched_product", "closest_match"}:
        raise ValueError("target_kind is invalid")
    payload["verdict"] = verdict
    payload["target_kind"] = target_kind
    return "POST", "recipe_catalog_identity_feedback", payload


def recipe_ingredient_decision_request(
    data: Mapping[str, object],
) -> tuple[str, str, dict[str, object]]:
    """Return the atomic ingredient decision v2 request."""
    payload = _recipe_feedback_base(data)
    action = str(data.get("action", "")).strip().lower()
    if action not in RECIPE_INGREDIENT_DECISION_ACTIONS:
        raise ValueError("action is invalid")
    origin = str(data.get("action_origin", "home_assistant")).strip().lower()
    if origin not in RECIPE_INGREDIENT_ACTION_ORIGINS:
        raise ValueError("action_origin is invalid")
    payload["action"] = action
    payload["action_origin"] = origin
    if action == "select_inventory_product":
        payload["selected_product_id"] = _positive_int(
            data.get("selected_product_id"),
            "selected_product_id",
        )
    elif "selected_product_id" in data:
        raise ValueError("selected_product_id is invalid for this action")
    if action == "reject_current_match":
        expected = data.get("expected_target_product_id")
        if expected is not None:
            payload["expected_target_product_id"] = _positive_int(
                expected,
                "expected_target_product_id",
            )
    elif "expected_target_product_id" in data:
        raise ValueError(
            "expected_target_product_id is invalid for this action"
        )
    return "POST", "recipe_catalog_ingredient_decision", payload


def recipe_planner_add_request(
    data: Mapping[str, object],
) -> tuple[str, str, dict[str, object]]:
    """Return the bounded account-level Cookidoo planner request."""
    recipe_id = _positive_int(data.get("recipe_id"), "recipe_id")
    date_value = data.get("date")
    if not isinstance(date_value, str):
        raise ValueError("date must be an ISO date")
    try:
        planned_date = date.fromisoformat(date_value.strip())
    except ValueError as err:
        raise ValueError("date must be an ISO date") from err
    today = datetime.now(timezone.utc).date()
    if planned_date < today or planned_date > today + timedelta(days=365):
        raise ValueError("date is outside the allowed range")
    token_value = data.get("provider_action_token")
    if not isinstance(token_value, str):
        raise ValueError("provider_action_token must be a string")
    token = token_value.strip()
    if RECIPE_FEEDBACK_TOKEN_PATTERN.fullmatch(token) is None:
        raise ValueError("provider_action_token is invalid")
    idempotency_value = data.get("idempotency_key")
    if not isinstance(idempotency_value, str):
        raise ValueError("idempotency_key must be a string")
    idempotency_key = idempotency_value.strip()
    if (
        not idempotency_key
        or len(idempotency_key) > RECIPE_IDEMPOTENCY_KEY_MAX_LENGTH
        or RECIPE_IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key) is None
    ):
        raise ValueError("idempotency_key is invalid")
    return (
        "POST",
        "recipe_catalog_planner_add",
        {
            "recipe_id": recipe_id,
            "date": planned_date.isoformat(),
            "provider_action_token": token,
            "idempotency_key": idempotency_key,
        },
    )


def recipe_query_request(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return the EverShelf action and bounded query parameters."""
    kind = str(data.get("kind", "browse")).strip().lower()
    if kind not in RECIPE_QUERY_KINDS:
        raise ValueError("kind must be browse or recommendations")

    params: dict[str, Any] = {}
    source = str(data.get("source", "")).strip()
    locale = str(data.get("locale", "")).strip()
    if source:
        params["source"] = source
    if locale:
        params["locale"] = locale
    if kind == "recommendations":
        params["limit"] = int(data.get("limit", 30))
        return "recipe_catalog_recommendations", params

    sort = str(data.get("sort", "availability")).strip().lower()
    if sort not in RECIPE_SORTS:
        raise ValueError("sort must be availability, expiry, or alphabetical")
    params.update(
        {
            "q": str(data.get("q", "")).strip(),
            "sort": sort,
            "availability_weight": int(data.get("availability_weight", 100)),
            "expiry_weight": int(data.get("expiry_weight", 25)),
            "minimum_coverage": int(data.get("minimum_coverage", 0)),
            "limit": int(data.get("limit", 50)),
            "fields": "card",
            "explain": "false",
        }
    )
    expiring_within_days = data.get("expiring_within_days")
    if expiring_within_days not in (None, ""):
        params["expiring_within_days"] = int(expiring_within_days)
    cursor = str(data.get("cursor", "")).strip()
    if cursor:
        params["cursor"] = cursor
    return "recipe_catalog_search", params


def recipe_hydration_request(
    data: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Return method, action and params/payload for hydration enqueue or status."""
    search_id = str(data.get("search_id", "")).strip()
    query = str(data.get("query") or data.get("q") or "").strip()
    if bool(search_id) == bool(query):
        raise ValueError("Provide exactly one of search_id or query")
    if search_id:
        return "GET", "recipe_jobs_status", {"search_id": search_id}

    payload: dict[str, Any] = {
        "query": query,
        "interactive": True,
        "exclude_cached": True,
        "limit": 20,
        "max_pages": 1,
        "force": bool(data.get("force", False)),
        "include_local_results": False,
    }
    source = str(data.get("source", "")).strip()
    if source and source != "cookidoo":
        raise ValueError("Cookidoo is the only remote recipe source currently available")
    locale = str(data.get("locale", "")).strip()
    if locale:
        payload["locale"] = locale
    return "POST", "recipe_catalog_discover", payload
