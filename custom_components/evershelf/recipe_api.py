"""Pure request builders for EverShelf recipe catalog services."""
from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

RECIPE_QUERY_KINDS = ("browse", "recommendations")
RECIPE_SORTS = ("availability", "expiry", "alphabetical")
RECIPE_GROCERY_MAX_SELECTIONS = 100
RECIPE_INGREDIENT_KEY_MAX_LENGTH = 64
RECIPE_IDEMPOTENCY_KEY_MAX_LENGTH = 128
RECIPE_INGREDIENT_KEY_PATTERN = re.compile(r"^ri:\d+:[a-f0-9]{16}$")
RECIPE_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


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
