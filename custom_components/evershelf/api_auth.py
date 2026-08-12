"""Shared EverShelf HTTP auth helpers."""
from __future__ import annotations

from typing import Any


def evershelf_headers(token: str = "", *, json_body: bool = False) -> dict[str, str]:
    """Return EverShelf headers with credentials only in X-API-Token."""
    headers: dict[str, str] = {"X-EverShelf-Request": "1"}
    if json_body:
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-API-Token"] = token
    return headers


def evershelf_params(token: str = "", params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return query params without placing credentials in URLs or access logs."""
    return dict(params or {})
