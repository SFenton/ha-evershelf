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
                    "recipes_missing_observation": 2,
                },
                "recipe_scores": {
                    "active_revision_id": 57,
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
                "ontology_queue": {
                    "provider": {
                        "provider": "copilot_socket",
                        "healthy": True,
                    }
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
    assert data["recipe_scores_stale"] is True
    assert data["recipe_score_inventory_revision"] == 56
    assert data["recipe_score_built_inventory_revision"] == 43
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
                "last_error": "x" * 1000,
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
    assert len(data["processing_last_error"]) == 300
    assert data["recipe_source_ontology_coverage"] == 100.0
