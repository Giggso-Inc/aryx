"""Ask-turn Q&A dispatch API package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_build_qa_resume_prompt": "ask_qa_resume_prompt",
    "_qa_fast_path_or_enumeration": "ask_qa_fast_path",
    "_qa_graph_search": "ask_qa_graph_search",
    "_qa_label_collision_response": "ask_qa_label_collision",
    "_qa_multi_attr_options_response": "ask_qa_multi_attr_options",
    "_qa_status_shortcircuit": "ask_qa_status_shortcircuit",
    "_route_ambiguous": "ask_route_qa",
    "_route_qa": "ask_route_qa",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_qa.{mod_name}")
    return getattr(mod, name)
