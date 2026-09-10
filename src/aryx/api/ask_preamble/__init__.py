"""Ask-turn preamble API package (Phase 8a folder restructuring). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_preamble_capture_quantity_background": "ask_preamble_quantity_background",
    "_preamble_country_change_gate": "ask_preamble_country_change",
    "_preamble_dedicated_quantity_gate": "ask_preamble_quantity_gate",
    "_preamble_extract_hints_and_resolve_country": "ask_preamble_hints_and_country",
    "_preamble_init_session": "ask_preamble_session_and_shortcuts",
    "_preamble_quantity_no_quote_gate": "ask_preamble_quantity_background",
    "_preamble_resolve_quantity_target": "ask_preamble_quantity_target_resolve",
    "_preamble_run": "ask_preamble_run",
    "_preamble_shortcut_gates": "ask_preamble_session_and_shortcuts",
    "_preamble_undo_gate": "ask_preamble_session_and_shortcuts",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.api.ask_preamble.{mod_name}")
    return getattr(mod, name)
