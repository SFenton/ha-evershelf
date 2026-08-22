"""Bounded normalization for EverShelf processing diagnostics."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_PHASES = {
    "idle",
    "recipes",
    "canonical",
    "ontology",
    "preparing",
    "scoring",
    "publishing",
    "compacting",
    "activating",
    "degraded",
}
PROCESSING_ERROR_PUBLIC_MESSAGE = (
    "EverShelf processing needs attention. Check the server logs for details."
)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bounded_int(value: object, *, maximum: int = 2_147_483_647) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(maximum, parsed))


def _bounded_float(value: object, *, maximum: float = 100.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(maximum, parsed))


def _bounded_text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:maximum] if value else None


def processing_status_data(payload: object) -> dict[str, Any]:
    """Flatten one processing-status response into entity-safe coordinator data."""
    unavailable: dict[str, Any] = {
        "processing_status_available": False,
        "processing_phase": "unavailable",
        "processing_active": False,
        "processing_problem": False,
        "processing_pending": 0,
        "processing_recipe_jobs": 0,
        "processing_canonical_open": 0,
        "processing_canonical_active": 0,
        "processing_canonical_lock_available": False,
        "processing_canonical_pending": 0,
        "processing_canonical_in_progress": 0,
        "processing_canonical_retries": 0,
        "processing_canonical_due": 0,
        "processing_canonical_failed": 0,
        "processing_canonical_exhausted": 0,
        "processing_canonical_exhausted_pending": 0,
        "processing_canonical_failed_24h": 0,
        "processing_canonical_overdue_leases": 0,
        "processing_canonical_stale_due": 0,
        "processing_canonical_stale_due_seconds": 0,
        "processing_canonical_oldest_pending_at": None,
        "processing_canonical_oldest_pending_age_seconds": 0,
        "processing_canonical_oldest_retry_at": None,
        "processing_canonical_oldest_retry_age_seconds": 0,
        "processing_canonical_oldest_due_at": None,
        "processing_canonical_oldest_due_age_seconds": 0,
        "processing_canonical_oldest_in_progress_at": None,
        "processing_canonical_oldest_in_progress_age_seconds": 0,
        "processing_canonical_earliest_lease_expires_at": None,
        "processing_canonical_next_due_at": None,
        "processing_canonical_last_error_kind": None,
        "processing_canonical_last_error": None,
        "processing_canonical_last_error_at": None,
        "processing_ontology_jobs": 0,
        "processing_ontology_deferred": 0,
        "processing_ontology_generation_intents": 0,
        "processing_ontology_intents_pending": 0,
        "processing_ontology_policy_deferred": 0,
        "processing_ontology_intent_oldest_age_seconds": 0,
        "processing_identity_coverage_gaps": 0,
        "processing_coverage_gap_oldest_age_seconds": 0,
        "processing_missing_recipe_observations": 0,
        "processing_score_products": 0,
        "processing_score_recipes": 0,
        "processing_score_phase": "idle",
        "processing_score_processed": 0,
        "processing_score_total": 0,
        "processing_score_progress": 0.0,
        "processing_score_recovery_required": False,
        "processing_score_recovery_strategy": None,
        "processing_oldest_age_seconds": 0,
        "processing_oldest_job_at": None,
        "processing_observed_at": None,
        "processing_last_error": None,
        "processing_logging_healthy": False,
        "processing_activation_outcome": None,
        "processing_activation_outcome_at": None,
        "recipe_score_revision": 0,
        "recipe_score_overlay_revision": 0,
        "recipe_score_status": "unavailable",
        "recipe_scores_stale": False,
        "recipe_score_inventory_revision": 0,
        "recipe_score_built_inventory_revision": 0,
        "recipe_score_catalog_revision": 0,
        "recipe_score_built_catalog_revision": 0,
        "recipe_score_source_revision": 0,
        "recipe_score_built_source_revision": 0,
        "identity_inventory_products": 0,
        "identity_accepted_products": 0,
        "identity_unresolved_products": 0,
        "identity_rejected_products": 0,
        "ontology_provider": None,
        "ontology_provider_required": False,
        "ontology_provider_healthy": False,
        "recipe_source_ontology_coverage": 0.0,
        "recipe_source_ontology_rows": 0,
        "recipe_source_ontology_covered": 0,
        "recipe_source_ontology_missing": 0,
    }
    root = _mapping(payload)
    status = _mapping(root.get("status"))
    if root.get("success") is not True or not status:
        return unavailable

    pending = _mapping(status.get("pending"))
    canonical_queue = _mapping(status.get("canonical_queue"))
    scores = _mapping(status.get("recipe_scores"))
    current = _mapping(scores.get("current"))
    built = _mapping(scores.get("built"))
    ontology_queue = _mapping(status.get("ontology_queue"))
    provider = _mapping(ontology_queue.get("provider"))
    activation = _mapping(status.get("activation"))
    provider_required = bool(ontology_queue.get("runtime_enabled"))
    coverage = _mapping(status.get("recipe_source_ontology"))
    incremental = _mapping(status.get("incremental_scores"))
    identity = _mapping(status.get("identity_admission"))
    logging_status = _mapping(status.get("logging"))
    phase = status.get("phase")
    if not isinstance(phase, str) or phase not in _PHASES:
        phase = "degraded"

    return {
        "processing_status_available": True,
        "processing_phase": phase,
        "processing_active": bool(status.get("active")),
        "processing_problem": bool(status.get("problem")),
        "processing_pending": _bounded_int(pending.get("total")),
        "processing_recipe_jobs": _bounded_int(
            pending.get("recipe_jobs")
        ),
        "processing_canonical_open": _bounded_int(
            canonical_queue.get("open_count")
        ),
        "processing_canonical_active": _bounded_int(
            canonical_queue.get("active_count")
        ),
        "processing_canonical_lock_available": bool(
            canonical_queue.get("lock_available")
        ),
        "processing_canonical_pending": _bounded_int(
            canonical_queue.get("pending_count")
        ),
        "processing_canonical_in_progress": _bounded_int(
            canonical_queue.get("in_progress_count")
        ),
        "processing_canonical_retries": _bounded_int(
            canonical_queue.get("retry_count")
        ),
        "processing_canonical_due": _bounded_int(
            canonical_queue.get("retry_due_count")
        ),
        "processing_canonical_failed": _bounded_int(
            canonical_queue.get("failed_count")
        ),
        "processing_canonical_exhausted": _bounded_int(
            canonical_queue.get("exhausted_count")
        ),
        "processing_canonical_exhausted_pending": _bounded_int(
            canonical_queue.get("exhausted_pending_count")
        ),
        "processing_canonical_failed_24h": _bounded_int(
            canonical_queue.get("failed_24h_count")
        ),
        "processing_canonical_overdue_leases": _bounded_int(
            canonical_queue.get("overdue_lease_count")
        ),
        "processing_canonical_stale_due": _bounded_int(
            canonical_queue.get("stale_due_count")
        ),
        "processing_canonical_stale_due_seconds": _bounded_int(
            canonical_queue.get("stale_due_seconds")
        ),
        "processing_canonical_oldest_pending_at": _bounded_text(
            canonical_queue.get("oldest_pending_at"),
            40,
        ),
        "processing_canonical_oldest_pending_age_seconds": _bounded_int(
            canonical_queue.get("oldest_pending_age_seconds")
        ),
        "processing_canonical_oldest_retry_at": _bounded_text(
            canonical_queue.get("oldest_retry_at"),
            40,
        ),
        "processing_canonical_oldest_retry_age_seconds": _bounded_int(
            canonical_queue.get("oldest_retry_age_seconds")
        ),
        "processing_canonical_oldest_due_at": _bounded_text(
            canonical_queue.get("oldest_due_at"),
            40,
        ),
        "processing_canonical_oldest_due_age_seconds": _bounded_int(
            canonical_queue.get("oldest_due_age_seconds")
        ),
        "processing_canonical_oldest_in_progress_at": _bounded_text(
            canonical_queue.get("oldest_in_progress_at"),
            40,
        ),
        "processing_canonical_oldest_in_progress_age_seconds": _bounded_int(
            canonical_queue.get("oldest_in_progress_age_seconds")
        ),
        "processing_canonical_earliest_lease_expires_at": _bounded_text(
            canonical_queue.get("earliest_lease_expires_at"),
            40,
        ),
        "processing_canonical_next_due_at": _bounded_text(
            canonical_queue.get("next_due_at"),
            40,
        ),
        "processing_canonical_last_error_kind": _bounded_text(
            canonical_queue.get("last_error_kind"),
            80,
        ),
        "processing_canonical_last_error": (
            PROCESSING_ERROR_PUBLIC_MESSAGE
            if _bounded_text(canonical_queue.get("last_error"), 1)
            else None
        ),
        "processing_canonical_last_error_at": _bounded_text(
            canonical_queue.get("last_error_at"),
            40,
        ),
        "processing_ontology_jobs": _bounded_int(
            pending.get("ontology_intake_jobs")
        )
        + _bounded_int(pending.get("ontology_generation_jobs")),
        "processing_ontology_deferred": _bounded_int(
            pending.get("ontology_deferred_jobs")
        ),
        "processing_ontology_generation_intents": _bounded_int(
            pending.get("ontology_generation_intents")
        ),
        "processing_ontology_intents_pending": _bounded_int(
            ontology_queue.get("generation_intent_pending_count")
        ),
        "processing_ontology_policy_deferred": _bounded_int(
            pending.get("ontology_policy_deferred_intents")
        ),
        "processing_ontology_intent_oldest_age_seconds": _bounded_int(
            ontology_queue.get("generation_intent_oldest_age_seconds")
        ),
        "processing_identity_coverage_gaps": _bounded_int(
            pending.get("identity_coverage_gaps")
        ),
        "processing_coverage_gap_oldest_age_seconds": _bounded_int(
            ontology_queue.get("coverage_gap_oldest_age_seconds")
        ),
        "processing_missing_recipe_observations": _bounded_int(
            pending.get("recipes_missing_observation")
        ),
        "processing_score_products": _bounded_int(
            incremental.get("pending_product_count")
        ),
        "processing_score_recipes": _bounded_int(
            incremental.get("pending_recipe_count")
        ),
        "processing_score_phase": _bounded_text(
            incremental.get("phase"),
            40,
        )
        or "idle",
        "processing_score_processed": _bounded_int(
            incremental.get("processed_recipe_count")
        ),
        "processing_score_total": _bounded_int(
            incremental.get("total_recipe_count")
        ),
        "processing_score_progress": _bounded_float(
            incremental.get("progress_percent")
        ),
        "processing_score_recovery_required": bool(
            incremental.get("copied_recovery_required")
        ),
        "processing_score_recovery_strategy": _bounded_text(
            incremental.get("recovery_strategy"),
            80,
        ),
        "processing_oldest_age_seconds": _bounded_int(
            status.get("oldest_age_seconds")
        ),
        "processing_oldest_job_at": _bounded_text(
            status.get("oldest_at"),
            40,
        ),
        "processing_observed_at": _bounded_text(
            status.get("observed_at"),
            40,
        ),
        "processing_last_error": (
            PROCESSING_ERROR_PUBLIC_MESSAGE
            if _bounded_text(status.get("last_error"), 1)
            else None
        ),
        "processing_logging_healthy": bool(
            logging_status.get("healthy")
        ),
        "processing_activation_outcome": _bounded_text(
            activation.get("last_outcome_kind"),
            80,
        ),
        "processing_activation_outcome_at": _bounded_text(
            activation.get("last_outcome_at"),
            40,
        ),
        "recipe_score_revision": _bounded_int(
            scores.get("active_revision_id")
        ),
        "recipe_score_overlay_revision": _bounded_int(
            scores.get("overlay_revision_id")
        ),
        "recipe_score_status": _bounded_text(
            scores.get("status"),
            40,
        )
        or "unavailable",
        "recipe_scores_stale": bool(scores.get("stale")),
        "recipe_score_inventory_revision": _bounded_int(
            current.get("inventory_revision")
        ),
        "recipe_score_built_inventory_revision": _bounded_int(
            built.get("inventory_revision")
        ),
        "recipe_score_catalog_revision": _bounded_int(
            current.get("catalog_revision")
        ),
        "recipe_score_built_catalog_revision": _bounded_int(
            built.get("catalog_revision")
        ),
        "recipe_score_source_revision": _bounded_int(
            current.get("ontology_source_revision")
        ),
        "recipe_score_built_source_revision": _bounded_int(
            built.get("ontology_source_revision")
        ),
        "identity_inventory_products": _bounded_int(
            identity.get("inventory_product_count")
        ),
        "identity_accepted_products": _bounded_int(
            identity.get("accepted_count")
        ),
        "identity_unresolved_products": _bounded_int(
            identity.get("unresolved_count")
        ),
        "identity_rejected_products": _bounded_int(
            identity.get("rejected_count")
        ),
        "ontology_provider": _bounded_text(
            provider.get("provider"),
            80,
        ),
        "ontology_provider_required": provider_required,
        "ontology_provider_healthy": (
            not provider_required or bool(provider.get("healthy"))
        ),
        "recipe_source_ontology_coverage": _bounded_float(
            coverage.get("coverage_percent")
        ),
        "recipe_source_ontology_rows": _bounded_int(
            coverage.get("source_row_count")
        ),
        "recipe_source_ontology_covered": _bounded_int(
            coverage.get("covered_row_count")
        ),
        "recipe_source_ontology_missing": _bounded_int(
            coverage.get("missing_row_count")
        ),
    }
