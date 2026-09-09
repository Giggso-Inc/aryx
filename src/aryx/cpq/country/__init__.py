"""CPQ country-alias resolution package (Phase 8a folder restructuring, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Lazy re-exports (PEP 562) to avoid circular-import chains across sibling Phase 8a packages."""

import importlib

_EXPORTS = {
    "_country_alias_group": "country_helpers",
    "_country_canonical_name": "country_helpers",
    "_normalize_country_candidate": "country_helpers",
    "detect_country_change_request": "country_helpers",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    mod_name = _EXPORTS.get(name)
    if mod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"aryx.cpq.country.{mod_name}")
    return getattr(mod, name)
