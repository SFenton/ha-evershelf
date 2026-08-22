import importlib.util
from pathlib import Path


def _load_module(name: str, relative_path: str):
    path = Path(__file__).parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


processing_status = _load_module(
    "evershelf_processing_status",
    "custom_components/evershelf/processing_status.py",
)
processing_status_data = processing_status.processing_status_data
PROCESSING_ERROR_PUBLIC_MESSAGE = (
    processing_status.PROCESSING_ERROR_PUBLIC_MESSAGE
)


def test_processing_status_flattens_bounded_entity_data() -> None:
    data = processing_status_data(
        {
            "success": True,
            "status": {
                "phase": "ontology",
                "active": True,
                "problem": False,
                "observed_at": "2026-08-16T18:00:00+00:00",
                "oldest_at": "2026-08-16 17:00:00",
                "oldest_age_seconds": 3600,
                "pending": {
                    "total": 12,
                    "recipe_jobs": 5,
                    "ontology_intake_jobs": 3,
                    "ontology_generation_jobs": 2,
                    "ontology_deferred_jobs": 30906,
                    "ontology_generation_intents": 7,
                    "ontology_policy_deferred_intents": 11,
                    "identity_coverage_gaps": 4,
                    "recipes_missing_observation": 2,
                },
                "recipe_scores": {
                    "active_revision_id": 57,
                    "overlay_revision_id": 58,
                    "status": "stale",
                    "stale": True,
                    "current": {
                        "inventory_revision": 56,
                        "catalog_revision": 96,
                        "ontology_source_revision": 5905,
                    },
                    "built": {
                        "inventory_revision": 43,
                        "catalog_revision": 96,
                        "ontology_source_revision": 5884,
                    },
                },
                "incremental_scores": {
                    "pending_product_count": 4,
                    "pending_recipe_count": 2,
                    "phase": "scoring",
                    "processed_recipe_count": 3,
                    "total_recipe_count": 8,
                    "progress_percent": 37.5,
                    "copied_recovery_required": True,
                    "recovery_strategy": "copied_score_refresh",
                },
                "identity_admission": {
                    "inventory_product_count": 18,
                    "accepted_count": 12,
                    "unresolved_count": 5,
                    "rejected_count": 1,
                },
                "ontology_queue": {
                    "generation_intent_pending_count": 19,
                    "generation_intent_oldest_age_seconds": 7200,
                    "coverage_gap_oldest_age_seconds": 1800,
                    "provider": {
                        "provider": "copilot_socket",
                        "healthy": True,
                    }
                },
                "activation": {
                    "last_outcome_kind": "policy_deferred",
                    "last_outcome_at": "2026-08-16 17:59:00",
                },
                "recipe_source_ontology": {
                    "coverage_percent": 37.8,
                    "source_row_count": 4480,
                    "covered_row_count": 1692,
                    "missing_row_count": 2788,
                },
                "logging": {"healthy": True},
            },
        }
    )

    assert data["processing_status_available"] is True
    assert data["processing_phase"] == "ontology"
    assert data["processing_pending"] == 12
    assert data["processing_ontology_jobs"] == 5
    assert data["processing_ontology_deferred"] == 30906
    assert data["processing_ontology_generation_intents"] == 7
    assert data["processing_ontology_intents_pending"] == 19
    assert data["processing_ontology_policy_deferred"] == 11
    assert data["processing_ontology_intent_oldest_age_seconds"] == 7200
    assert data["processing_identity_coverage_gaps"] == 4
    assert data["processing_coverage_gap_oldest_age_seconds"] == 1800
    assert data["processing_activation_outcome"] == "policy_deferred"
    assert (
        data["processing_activation_outcome_at"]
        == "2026-08-16 17:59:00"
    )
    assert data["processing_score_products"] == 4
    assert data["processing_score_recipes"] == 2
    assert data["processing_score_phase"] == "scoring"
    assert data["processing_score_processed"] == 3
    assert data["processing_score_total"] == 8
    assert data["processing_score_progress"] == 37.5
    assert data["processing_score_recovery_required"] is True
    assert (
        data["processing_score_recovery_strategy"]
        == "copied_score_refresh"
    )
    assert data["recipe_scores_stale"] is True
    assert data["recipe_score_inventory_revision"] == 56
    assert data["recipe_score_built_inventory_revision"] == 43
    assert data["recipe_score_overlay_revision"] == 58
    assert data["identity_inventory_products"] == 18
    assert data["identity_accepted_products"] == 12
    assert data["identity_unresolved_products"] == 5
    assert data["identity_rejected_products"] == 1
    assert data["ontology_provider_healthy"] is True
    assert data["recipe_source_ontology_coverage"] == 37.8
    assert data["recipe_source_ontology_missing"] == 2788


def test_processing_status_fails_closed_and_bounds_values() -> None:
    assert processing_status_data(None)["processing_status_available"] is False
    data = processing_status_data(
        {
            "success": True,
            "status": {
                "phase": "unexpected",
                "pending": {"total": -10},
                "oldest_age_seconds": 10**20,
                "last_error": (
                    "SQLSTATE table ontology_activation_imports at "
                    "/var/www/html/api/lib/ontology_v3/activation.php"
                ),
                "recipe_scores": {},
                "ontology_queue": {},
                "recipe_source_ontology": {
                    "coverage_percent": 200,
                },
            },
        }
    )
    assert data["processing_phase"] == "degraded"
    assert data["processing_pending"] == 0
    assert data["processing_oldest_age_seconds"] == 2_147_483_647
    assert (
        data["processing_last_error"]
        == PROCESSING_ERROR_PUBLIC_MESSAGE
    )
    assert "SQLSTATE" not in data["processing_last_error"]
    assert "/var/www" not in data["processing_last_error"]
    assert data["recipe_source_ontology_coverage"] == 100.0


def test_processing_status_exposes_canonical_queue_without_false_degradation() -> None:
    data = processing_status_data(
        {
            "success": True,
            "status": {
                "phase": "canonical",
                "active": True,
                "problem": False,
                "pending": {
                    "total": 3,
                    "canonical_queue": 3,
                    "canonical_due": 1,
                },
                "canonical_queue": {
                    "open_count": 3,
                    "active_count": 2,
                    "lock_available": True,
                    "pending_count": 2,
                    "in_progress_count": 1,
                    "retry_count": 2,
                    "retry_due_count": 1,
                    "failed_count": 4,
                    "exhausted_count": 1,
                    "exhausted_pending_count": 0,
                    "failed_24h_count": 0,
                    "overdue_lease_count": 0,
                    "stale_due_count": 0,
                    "stale_due_seconds": 300,
                    "oldest_pending_at": "2026-08-20 12:00:00",
                    "oldest_pending_age_seconds": 12,
                    "oldest_retry_at": "2026-08-20 12:00:05",
                    "oldest_retry_age_seconds": 7,
                    "oldest_due_at": "2026-08-20 12:00:04",
                    "oldest_due_age_seconds": 8,
                    "oldest_in_progress_at": "2026-08-20 12:00:10",
                    "oldest_in_progress_age_seconds": 2,
                    "earliest_lease_expires_at": "2026-08-20 12:02:10",
                    "next_due_at": "2026-08-20 12:00:20",
                    "last_error_kind": "sqlite_busy",
                    "last_error": "private database path and SQLSTATE",
                    "last_error_at": "2026-08-20 12:00:08",
                },
                "recipe_scores": {},
                "ontology_queue": {},
                "recipe_source_ontology": {},
            },
        }
    )

    assert data["processing_phase"] == "canonical"
    assert data["processing_problem"] is False
    assert data["processing_canonical_open"] == 3
    assert data["processing_canonical_active"] == 2
    assert data["processing_canonical_lock_available"] is True
    assert data["processing_canonical_pending"] == 2
    assert data["processing_canonical_in_progress"] == 1
    assert data["processing_canonical_retries"] == 2
    assert data["processing_canonical_due"] == 1
    assert data["processing_canonical_failed"] == 4
    assert data["processing_canonical_exhausted"] == 1
    assert data["processing_canonical_exhausted_pending"] == 0
    assert data["processing_canonical_failed_24h"] == 0
    assert data["processing_canonical_overdue_leases"] == 0
    assert data["processing_canonical_stale_due"] == 0
    assert data["processing_canonical_stale_due_seconds"] == 300
    assert data["processing_canonical_oldest_pending_age_seconds"] == 12
    assert data["processing_canonical_oldest_retry_age_seconds"] == 7
    assert data["processing_canonical_oldest_due_at"] == "2026-08-20 12:00:04"
    assert data["processing_canonical_oldest_due_age_seconds"] == 8
    assert data["processing_canonical_oldest_in_progress_age_seconds"] == 2
    assert data["processing_canonical_next_due_at"] == "2026-08-20 12:00:20"
    assert data["processing_canonical_last_error_kind"] == "sqlite_busy"
    assert (
        data["processing_canonical_last_error"]
        == PROCESSING_ERROR_PUBLIC_MESSAGE
    )
    assert "SQLSTATE" not in data["processing_canonical_last_error"]
