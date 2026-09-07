"""The non-CPQ "standard Ask pipeline" — package split.

Split out of `ask_api.py` per
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md Phase 4 step 1: term
extraction, attribute enrichment, plain-language synthesis, and the
top-level `_standard_ask_pipeline` orchestrator for the standard (non-CPQ)
Ask path.

Every name below is re-exported here so `ask_api.py` can do a single
`from .ask_standard_pipeline import _extract_terms, _enrich_with_attributes,
_synthesise, _standard_ask_pipeline, ...` re-export — which keeps every
existing `mock.patch("aryx.api.ask_api.<name>", ...)` call site resolving
exactly as it did before the split (patches target `ask_api`'s own module
namespace, which this re-export populates).
"""
from __future__ import annotations

from aryx.api.ask_standard_pipeline._enrichment import _enrich_with_attributes
from aryx.api.ask_standard_pipeline._pipeline import _standard_ask_pipeline
from aryx.api.ask_standard_pipeline._rewrite import _enforce_plain_answer, _rewrite_plain
from aryx.api.ask_standard_pipeline._synthesis import _synthesise
from aryx.api.ask_standard_pipeline._terms import _extract_terms
from aryx.api.ask_standard_pipeline._text_utils import (
    _recent,
    _strip_think,
    _user_texts_from_history,
)

__all__ = [
    "_enrich_with_attributes",
    "_enforce_plain_answer",
    "_extract_terms",
    "_recent",
    "_rewrite_plain",
    "_standard_ask_pipeline",
    "_strip_think",
    "_synthesise",
    "_user_texts_from_history",
]
