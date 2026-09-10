"""Dynamic-FK-detection pipeline package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_candidate_columns": "dynamic_fk_sampling",
    "_headers": "dynamic_fk_sampling",
    "_judge_one": "dynamic_fk",
    "_truncate_counts": "dynamic_fk_sampling",
    "detect_dynamic_fk_links": "dynamic_fk",
    "estimate_join_fanout": "dynamic_fk_sampling",
    "generate_candidate_pairs": "dynamic_fk",
    "judge_candidates_with_llm": "dynamic_fk",
    "sample_distinct_values": "dynamic_fk_sampling",
    "sample_value_counts": "dynamic_fk_sampling",
    "try_prefix_transforms": "dynamic_fk_sampling",
    "value_overlap_ratio": "dynamic_fk_sampling",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.pipeline.dynamic_fk.{mod_name}")
    return getattr(mod, name)
