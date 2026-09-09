"""Ingest-validation pipeline package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "CheckResult": "ingest_validation_types",
    "DatasetTruth": "ingest_validation_types",
    "FkTruth": "ingest_validation_types",
    "GroundTruth": "ingest_validation_types",
    "ValidationReport": "ingest_validation_types",
    "_check_projection_parity": "ingest_validation_checks",
    "_dataset_type_map": "ingest_validation_checks",
    "_parse_csv": "ingest_validation_ground_truth",
    "_raw_xml_counts": "ingest_validation",
    "ground_truth_from_tabular": "ingest_validation_ground_truth",
    "main": "ingest_validation",
    "validate_workspace": "ingest_validation_checks",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.pipeline.ingest_validation.{mod_name}")
    return getattr(mod, name)
