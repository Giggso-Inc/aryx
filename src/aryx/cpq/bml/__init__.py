"""CPQ BML-script evaluator package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "ArrayIterationShape": "bml_analysis",
    "BmlEvaluator": "bml",
    "_BoolExpr": "bml_conditions",
    "_array_membership_hit": "bml_conditions",
    "_branch_bool": "bml_branches",
    "_branch_values": "bml_branches",
    "_eval_boolean_expr": "bml_conditions",
    "_find_block": "bml_text",
    "_first_matching_branch": "bml_tier1",
    "_literal_concat_values": "bml_branches",
    "_match_array_membership": "bml_conditions",
    "_operator_hit": "bml_declarative",
    "_parse_boolean_expr": "bml_conditions",
    "_parse_branches": "bml_branches",
    "_parse_condition": "bml_conditions",
    "_resolve_literal_expr": "bml_tier1",
    "_split_on_plus_outside_quotes": "bml_text",
    "_split_pipe_caret_values": "bml_branches",
    "_split_statements": "bml_text",
    "_split_top_level": "bml_text",
    "_strip_block_comments": "bml_text",
    "_strip_line_comments": "bml_text",
    "_strip_wrapping_parens": "bml_text",
    "_substitute_util_get_constraint_vals": "bml_util_substitution",
    "clear_shared_bml_cache": "bml_tier1",
    "evaluate_constant_return": "bml_tier1",
    "evaluate_declarative_conditions": "bml_declarative",
    "evaluate_hide_master_list": "bml_hide_idioms",
    "evaluate_hide_master_list_unguarded": "bml_hide_idioms",
    "evaluate_hide_tier1": "bml_tier1",
    "evaluate_tier1": "bml_tier1",
    "extract_literal_comparisons": "bml_analysis",
    "parse_array_iteration": "bml_analysis",
    "referenced_variables": "bml_analysis",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.bml.{mod_name}")
    return getattr(mod, name)
