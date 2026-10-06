"""CPQ configuration engine — retriever/Ask layer.

Never touches ingestion code. Reads entity attributes from PostgreSQL
(aryx_entity.attributes JSONB) and graph structure from FalkorDB to:

  1. Detect CPQ configuration intent in a question.
  2. Extract product hints (hardware version, country, etc.) from NL.
  3. Load the product's config attributes + menu options from the graph.
  4. Auto-fill attributes using:
       a. User-stated values (from NL)
       b. Valid default_value from XML
       c. First eligible item_value by order (NEVER None/null/empty)
  5. Identify the next pending required attribute to ask about.
  6. Build the final CPQ payload {variable_name: item_value}.

item_value vs item_text: this engine always reads item_value directly from
the PostgreSQL attributes JSON — bypassing any ingestion-layer naming issues.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from aryx.config import get_settings
from aryx.raven_log import raven_log
from aryx.cpq import rule_scope
from aryx.cpq import data_table_bridge
from aryx.cpq.bml.bml import (
    BmlEvaluator, evaluate_declarative_conditions, extract_literal_comparisons,
    _operator_hit,
)
from aryx.cpq.data_table.data_table_resolver import resolve_whitelist_values as dt_resolve_whitelist_values
from aryx.cpq.data_table.data_table_resolver import resolve_product_cpq_model_family as dt_resolve_product_cpq_model_family
from aryx.cpq.data_table.data_table_resolver import resolve_product_cpq_models_from_rows as dt_resolve_product_cpq_models_from_rows
from aryx.cpq.data_table.data_table_resolver import resolve_product_cpq_models_from_hint as dt_resolve_product_cpq_models_from_hint
from aryx.cpq.data_table.data_table_resolver import resolve_region_allow_value as dt_resolve_region_allow_value
from aryx.cpq.data_table.data_table_resolver import resolve_invalid_product_variant as dt_resolve_invalid_product_variant
from aryx.cpq.data_table.data_table_resolver import discover_cpq_models_for_base_model as dt_discover_cpq_models_for_base_model
from aryx.cpq.data_table.data_table_resolver import governed_attr_names_for_base_model as dt_governed_attr_names_for_base_model
from aryx.cpq.data_table.data_table_resolver import governed_required_attr_names_for_base_model as dt_governed_required_attr_names_for_base_model
from aryx.cpq.data_table.data_table_resolver import find_inconsistent_filled_pairs as dt_find_inconsistent_filled_pairs
from aryx.cpq.data_table.data_table_resolver import (
    find_inconsistent_filled_pairs_detailed as dt_find_inconsistent_filled_pairs_detailed,
)
from aryx.cpq.data_table.data_table_resolver import attr_ever_governed_for_cpq_model as dt_attr_ever_governed_for_cpq_model
from aryx.cpq.data_table.data_table_cache import _invalidate_on_marker_change
from aryx.cpq.data_table.data_table_cache import _cache_write_if_marker_unchanged
from aryx.cpq.layout_source import LayoutFileSource
from aryx.cpq.logging_context import install_run_id_logging
from aryx.cpq.rdb.rdb import PostgresCpqRdb, get_cpq_rdb
from aryx.cpq.rule_trace import rule_trace
from aryx.resolution.classical import string_score
from aryx.cpq.state import (
    ConfigAttr, ConstraintRule, CpqSession, HidingRule, MenuOption,
    RecommendationRule, ValidationRule,
)
from aryx.store.ingest_question_store import IngestQuestionStore

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)

# ── None-value sentinel set ────────────────────────────────────────────────────
# CPQ attributes with these values represent "no selection" — auto-fill must
# skip them and try the next option. The rule: no None value ever selected.
_NONE_VALUES: frozenset[str] = frozenset({
    "none", "null", "n/a", "na", "", "0", "-1",
    "not applicable", "no selection", "select...", "--", "choose",
    "false", "undefined", "not selected", "any",
})


def _valid(val: str | None) -> bool:
    """True when val is a usable CPQ API code (not a None sentinel)."""
    return bool(val) and str(val).strip().lower() not in _NONE_VALUES


# Values that are too empty/placeholder to be presented as user-selectable options.
# Stricter than _NONE_VALUES — keeps codes like "NA" (North America), "0" (quantity),
# etc. so they appear in prompts but are still blocked from auto-fill via _valid().
_DISPLAY_EMPTY: frozenset[str] = frozenset({
    "", "--", "select...", "choose", "none", "null", "undefined",
})


def _presentable(val: str | None) -> bool:
    """True when val should appear as a numbered option in the user-facing prompt."""
    return bool(val) and str(val).strip().lower() not in _DISPLAY_EMPTY


# A reply declining one grid-selector option's upfront quantity question
# (see CpqEngine.parse_grid_quantity_reply) — "skip"/"none"/"no" etc. all
# mean the same thing a bare "0" does: this option isn't included.
_GRID_QUANTITY_SKIP_RE = re.compile(
    r"^\s*(skip|none|no|nope|nothing|n/?a|not\s+needed)\s*$", re.IGNORECASE,
)

# 2026-08-27 follow-up: a customer plausibly types a spelled-out or
# "dozen"-family quantity ("three", "a dozen", "half a dozen", "2 dozen")
# instead of a bare digit. Deliberately a small, FIXED vocabulary — never
# a general NLP number parser — same "never guess, only convert a
# recognized phrasing" discipline as the rest of this module. Negative
# quantities ("-5", "minus 6") are intentionally NOT included here: a
# negative mount count has no real business meaning, so parse_grid_
# quantity_reply correctly keeps rejecting those (unchanged).
_GRID_QUANTITY_WORD_NUMBERS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}

_GRID_QUANTITY_DOZEN_N_RE = re.compile(r"^(\d+|[a-z]+)\s+dozen$")


def _parse_grid_quantity_dozen_phrase(text: str) -> int | None:
    """"dozen"/"a dozen" -> 12, "half a dozen"/"half dozen" -> 6, "N
    dozen" (N a digit or one of _GRID_QUANTITY_WORD_NUMBERS) -> N*12.
    Returns None for anything else — never a guess."""
    tl = text.strip().lower()
    if tl in ("dozen", "a dozen"):
        return 12
    if tl in ("half a dozen", "half dozen"):
        return 6
    m = _GRID_QUANTITY_DOZEN_N_RE.match(tl)
    if not m:
        return None
    n_text = m.group(1)
    if n_text.isdigit():
        return int(n_text) * 12
    if n_text in _GRID_QUANTITY_WORD_NUMBERS:
        return _GRID_QUANTITY_WORD_NUMBERS[n_text] * 12
    return None


# Deferred to here (not the top-of-file import block) for the same reason
# as `turn_intent`'s and `auto_fill_resolve`'s imports further down:
# aryx.cpq.grid_quantity's submodules import names BACK from this module
# (_valid, _GRID_QUANTITY_SKIP_RE, _GRID_QUANTITY_WORD_NUMBERS,
# _parse_grid_quantity_dozen_phrase) — the last of them being
# `_parse_grid_quantity_dozen_phrase` right above, so this line must sit
# after it. A top-of-file import would be a circular-import failure.
from aryx.cpq import grid_quantity  # noqa: E402

# aryx.cpq.nl_hint_extraction's submodules only ever do
# `from aryx.cpq import engine as _engine_module` (whole-module reference,
# attributes read at call time) -- never `from aryx.cpq.engine import
# <name>` -- so this import has no ordering constraint relative to any
# module-level name defined later in this file.
from aryx.cpq import nl_hint_extraction  # noqa: E402


# Moved to catalog_naming.py/label_matching.py/token_unit_matching.py
# (Phase 4 module-level extraction) -- re-exported here so every existing
# `from aryx.cpq.engine import <name>` caller/test, and
# `_engine_module._strip_catalog_name_noise(...)`'s whole-module-reference
# call, keep working unchanged.
from aryx.cpq.token_unit_matching import (  # noqa: E402
    _has_digit, _is_ordered_abbreviation, _option_matches_with_unit_normalization,
    _singularize_token, _tokens_match_loosely,
)
from aryx.cpq.label_matching import (  # noqa: E402
    _label_mention_span, _label_mentioned, _label_mentioned_strict,
)
from aryx.cpq.catalog_naming import (  # noqa: E402
    _ACRONYM_BOUNDARY_RE, _CAMEL_BOUNDARY_RE, _catalog_prefix,
    _condition_value_matches, _strip_catalog_name_noise, _variable_words,
)



# Public alias so ask_api can access it without importing a private name
# (same convention as DECISION_REQUIRED_KEYS above). Used by the ISSUE-004
# country-change fix (PR #205 review, Medium finding #5) to replace a raw
# substring test with a real word-segment match — "region" as a substring
# would incorrectly match a hypothetical "RegionalDiscountCode" (segment
# "regional" != "region"); splitting into real camelCase/underscore words
# first and requiring an EXACT segment match avoids that false positive
# while staying fully generic (no hardcoded attribute names).
variable_name_words = _variable_words


# ── CPQ intent detection ───────────────────────────────────────────────────────
# Generic CPQ-domain vocabulary only — the English words customers use to
# signal configuration intent ("quote", "configure", "bom", ...) are a fixed
# set of the language, not workspace-ingested data, so listing them isn't the
# same kind of hardcoding a product-name list is. Product-name literals
# (formerly apx|mototrbo|sl3500|dpx|xpr here) were removed — is_cpq_question()
# now also checks the workspace's actually-ingested product names dynamically.
# Live-confirmed gap (2026-07-27, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_
# PLAN.md): "\bradio\b" never matches "radios" — the word boundary after
# "radio" fails when an "s" immediately continues the word. "I want to
# order APX Next radios..." silently fell through to the generic,
# non-CPQ LLM pipeline entirely because of this one missing "s?".
_CPQ_TRIGGER = re.compile(
    r"\b(quote|configure|configuration|build.*quote|create.*quote|"
    r"radios?|"
    r"5g|lte|carrier|billing|activation|hardware.*version|"
    r"bom|payload)\b",
    re.IGNORECASE,
)

# ── NL hint extraction patterns ────────────────────────────────────────────────
_HINT_PATTERNS: list[tuple[str, str, str]] = [
    # (attr_key_fragment, regex, extracted_value)
    # attr_key_fragment is matched word-by-word against the attribute's variable_name.
    # ORDER MATTERS: more specific patterns must appear before generic ones — the first
    # match for each key wins (extract_hints skips a key once it's set).
    #
    # Full option-name patterns MUST come before the generic "lte"/"5g"/"4g" tokens so
    # "4G LTE Only" is never collapsed to the ambiguous "LTE" hint that cannot
    # distinguish "APX NEXT (4G LTE Only)" from "APX NEXT (4G LTE+5G)".
    ("hwversion", r"\b4g\s+lte\s+only\b", "APX NEXT (4G LTE Only)"),
    ("hwversion", r"\b4g\s+lte\s*\+\s*5g\b", "APX NEXT (4G LTE+5G)"),
    ("hwversion", r"\b5g\b", "5G"),
    ("hwversion", r"\blte\b", "LTE"),
    ("hwversion", r"\b4g\b", "4G"),
    # Specific country shortcuts — passed as-is to word-boundary display matching.
    # Only list codes/aliases the DB display name won't spell out verbatim.
    ("country", r"\b(us|usa|u\.s\.)\b", "United States"),
    ("country", r"\b(uk|u\.k\.)\b", "United Kingdom"),
    # NOTE: no "product" concept here anymore. A hardcoded product-name/
    # variant list (APX NEXT XE/XN/Enhanced/...) used to live in this table
    # and fed detect_product_mention()'s fallback path — removed because it
    # silently failed to recognise any product outside that fixed list.
    # Product detection is now fully dynamic: CpqEngine._ingested_product_names()
    # reads the REAL product/family names of every catalog actually ingested
    # into the workspace, live from the graph (see detect_product_mention).
]

# Reverse of the country entries above — a country-fragment attribute whose
# real options are abbreviation codes rather than full names (e.g.
# chargerCountryPlug_apcr offers "US"/"UK", not "United States"/"United
# Kingdom") can never match the "United States" hint via substring search:
# a longer needle can't be found inside a shorter haystack. Confirmed live:
# ultimateDestinationCountry (whose own option IS "United States"... actually
# whose display name matches directly) resolves fine via Priority 2/3, but
# chargerCountryPlug_apcr kept re-asking because "united states" can never be
# found inside its own "US" option text — the customer had already answered
# with the country, typed it again for this attribute, and got rejected.
# Moved to country_alias_data.py/country_alias_data_a.py/
# country_alias_data_b.py/country_helpers.py (Phase 4 module-level
# extraction) -- re-exported here so every existing `from
# aryx.cpq.engine import <name>` caller/test keeps working unchanged.
from aryx.cpq.country.country_alias_data import _COUNTRY_ALIAS_GROUPS  # noqa: E402
from aryx.cpq.country.country_helpers import (  # noqa: E402
    _country_alias_group, _country_canonical_name, _normalize_country_candidate,
    detect_country_change_request,
)


# Generic country extraction — captures any proper-noun country name from NL
# phrases like "customer in Australia", "located in New Zealand", "for Canada".
# The extracted name is matched word-boundary against DB option display names,
# so no country → item_value mapping is needed here.

# Live-confirmed bug, fixed 2026-07-26 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_
# PLAN.md Amendment 11): a bare re.IGNORECASE on the whole pattern makes
# [A-Z]/[a-z] match EITHER case, defeating the capture group's actual
# purpose — matching a genuinely Title-Case proper noun. Once that
# distinction is gone, the repeated group `(?:\s+[A-Z][a-z]+)*` happily
# keeps consuming every following lowercase word too, since each one still
# satisfies "[A-Z][a-z]+" under blanket IGNORECASE. Confirmed live: "...for
# customer Houston City of whose destination country is United States"
# captured "Customer Houston City Of Whose Destination Country Is United
# States" as the "country" — the ENTIRE tail of the sentence, not just the
# real country name. Fixed by scoping case-insensitivity to ONLY the
# preposition alternation via an inline (?i:...) group — the capture group
# itself now requires genuine Title Case, as originally intended, so a run
# of ordinary lowercase words correctly stops the match instead of
# extending it.
# Added 2026-07-27: "destination country is X" / "country is X" phrasing
# — confirmed live it falls through with none of the existing triggers
# (the word before the country name is "is", not in/for/from). Scoped
# narrowly to "country is" specifically (not a bare "is", which would
# false-positive on any unrelated "X is Y" sentence) — safe because the
# word "country" immediately preceding it is itself already a strong,
# on-topic signal.
# N1 harden (2026-07-28): also match "destination country is X",
# "destination country X", "whose destination country is X" — confirmed
# negative few-shot re-asked country when user already said United States.
# Capture group allows Title Case OR single-token ALLCAPS (US) after the
# trigger; multi-word countries use Title Case words.
# 2026-07-31 follow-up (docs/config_consistency_issues_2026-07-30.md item
# 5): "...with destination country as United States" fell through every
# existing trigger — "as" sits between "destination country" and the real
# country name, and none of the prior alternatives account for that
# preposition, so the country was silently dropped and re-asked despite
# being stated. Added "destination country as"/"country as" alongside the
# existing "is" variants.
# Fallback-path hardening, 2026-08-13 (docs/CPQ_COUNTRY_LLM_ONLY_PLAN_
# 2026_08_13.md review finding: `_mine_history_for_cpq_context`, which
# recovers a country stated on an EARLIER non-CPQ turn, has no LLM call
# to route through -- those historical texts were never classified at
# all, so this regex remains the only mechanism there. Two fixes:
# (1) an optional "the" between the preposition and the country name
# ("in the United States") -- the capture group previously had to start
# IMMEDIATELY after the preposition, and a lowercase "the" broke the
# match outright; (2) a trailing `\b` on the `[A-Z]{2}` alternative so
# it can never again grab a 2-letter fragment of a longer ALLCAPS token
# ("APXNET" -> "AP"). The leftmost-match-wins failure mode (a bad match
# earlier in the sentence shadowing a real country later on) is fixed
# at the call site in `extract_hints` below, not here in the pattern
# itself.
_COUNTRY_PREP = re.compile(
    r"(?i:\b(?:in|for|from|customer\s+in|located\s+in|based\s+in|"
    r"destination\s+country\s+is|destination\s+country\s+as|"
    r"destination\s+country|"
    r"whose\s+destination\s+country\s+is|country\s+is|country\s+as)\s+)"
    r"(?:the\s+)?"
    r"((?:[A-Z]{2,}\b|[A-Z][a-z]+)(?:\s+[A-Z][a-z]+)*)"
)

# Region hints (abbreviations the generic extractor won't catch as country names)
# CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T10: this list independently
# hand-maintains region abbreviations rather than deriving from
# region_and_noise_constants.py's own real, ingested-alias-table-backed
# `_COUNTRY_TO_REGION` (same divergence class T5 already fixed for
# region_for_country's own lookup) -- it had drifted to 4 of that other
# module's 5 real regions, missing "ME" (Middle East) entirely, even
# though ME is a real, catalog-facing region value elsewhere in this
# engine (derive_region, region_for_country, and real test fixtures all
# confirm it). Not merged into one shared list here -- this is a regex-
# over-free-text scan, a genuinely different shape from a country-name
# dict lookup -- just given the one concrete pattern it was missing,
# mirroring the existing "latin america" -> "LA" entry's own style.
_REGION_PATTERNS: list[tuple[str, str]] = [
    (r"\b(north\s+america|namer)\b", "NA"),
    (r"\bemea\b", "EMEA"),
    (r"\bapac\b", "APAC"),
    (r"\blatin\s+america\b", "LA"),
    (r"\bmiddle\s+east\b", "ME"),
]

# Moved to quantity_patterns.py/quantity_word_numbers.py/
# quantity_hint_extraction.py/quantity_turn_detection.py (Phase 4 module-
# level extraction) -- re-exported here so every existing `from
# aryx.cpq.engine import <name>` caller/test keeps working unchanged.
from aryx.cpq.quantity.quantity_patterns import (  # noqa: E402
    MAX_PRODUCT_QUANTITY, MIN_PRODUCT_QUANTITY, is_valid_product_quantity,
)
from aryx.cpq.quantity.quantity_word_numbers import (  # noqa: E402
    _normalize_quantity_text, _substitute_number_words, _words_to_number,
)
from aryx.cpq.quantity.quantity_hint_extraction import (  # noqa: E402
    _is_year_shaped_model_quantity, extract_quantity_decimal_hint,
    extract_quantity_hint,
)
from aryx.cpq.quantity.quantity_turn_detection import (  # noqa: E402
    find_catalog_quantity_attrs, question_mentions_quantity, quantity_turn_precheck,
)



# catalog-hint matching (extract_catalog_hints): a real menu option's own
# text (item_value/display_name) found verbatim in the question — punctuation
# and casing stripped so "AT&T/FirstNet" matches item_value "ATT/FIRSTNET" and
# "no multikey" matches "NO MULTIKEY". Deliberately glued (no word-boundary
# anchors survive stripping), so a minimum cleaned length keeps accidental
# substring collisions (e.g. "essential" inside "quintessential") negligible.
_HINT_MIN_PHRASE_LEN = 5
_HINT_STRIP_RE = re.compile(r"[^a-z0-9]")

# detect_product_mention's fuzzy-substring fallback (see its docstring):
# minimum aryx.resolution.classical.string_score (SequenceMatcher ratio,
# [0,1]) against a sliding window the length of the candidate name for a
# PARTIAL/misspelled product mention to count. Deliberately conservative —
# high enough that an unrelated, generic question never scores this well
# against a real product name by coincidence; a genuine near-miss (a typo,
# or a name missing one trailing character) comfortably clears it.
_PRODUCT_FUZZY_MATCH_THRESHOLD = 0.82

# suggest_product_candidates' lower bound for the "maybe, not confident"
# band — empirically, unrelated generic questions ("does it support dual
# SIM too", "what color options are available") score up to ~0.5 against a
# real product name purely by character-overlap coincidence, while a
# genuine near-miss clears 0.82. 0.65 sits well above that noise floor
# (leaves margin so ordinary questions never trigger a "did you mean...?"
# hint) while still well below the confirm-worthy threshold.
_PRODUCT_FUZZY_SUGGEST_THRESHOLD = 0.65

# The sliding-window score above compares a candidate against the WHOLE
# normalized question (filler words, quantities, country names and all),
# which is the right shape for "does some run of this sentence spell out
# the product" but has no signal for the opposite, equally common case: a
# short brand abbreviation ("APX", "SL", "MOTO") that IS a genuine leading
# fragment of a real ingested name ("APXNEXT", "SL3500E", "MOTOTRBO") but
# is far too short for name_norm-in-q_norm containment to ever fire, and
# too short relative to a long candidate for the sliding window to carry
# any real signal (window > len(q_norm) collapses to one whole-string
# comparison, so short/vague mentions were scored on coincidental overlap
# with unrelated filler text — confirmed live: "APX" alone matched
# "videoSolutions_BOM" over any real APX-family name). This bonus scores
# any individual WORD token from the question that is a genuine prefix of
# a candidate's normalized name — dynamic, no product list involved, works
# for whatever is actually ingested. Sits inside the "suggest" band, never
# the "confirm" band: a bare abbreviation is real signal that the customer
# means SOME member of a family, never enough on its own to silently pick
# WHICH one (this engine's documented "never guess" discipline).
_ABBR_PREFIX_MIN_LEN = 3
_ABBR_PREFIX_SCORE = 0.75

# next_question_prompt: an attr whose effective option list exceeds this is
# asked as "type the exact name" (with a few examples) instead of a numbered
# menu — confirmed live that unconstrained master lists (product selector:
# ~325 models spanning every family; country: ~250 entries) are unusable as
# a menu dump. Threshold-based and attr-agnostic — no attribute names
# hardcoded. 25 keeps every genuinely menu-shaped list seen in real
# catalogs (colors, bands, service tiers — all well under 20) enumerated.
_MAX_ENUMERATED_OPTIONS = 25

# Moved to engine_caches.py (Phase 4 module-level extraction) --
# re-exported here so every existing `from aryx.cpq.engine import
# <name>` caller/test, `_engine_module.<name>` whole-module-reference
# read, and `patch("aryx.cpq.engine.<name>")`/`monkeypatch.setattr(
# engine_mod, "<name>", ...)` dotted-path test patch keep working
# unchanged.
from aryx.cpq.engine_caches import (  # noqa: E402
    _clear_data_table_forced_vns_cache, _clear_rule_join_data_cache,
    _clear_substitute_util_get_constraint_vals_cache, _clear_value_rules_cache,
    _DATA_TABLE_FORCED_VNS_CACHE, _DATA_TABLE_FORCED_VNS_CACHE_LAST_SEEN_MARKER,
    _DATA_TABLE_FORCED_VNS_CACHE_TTL_SECONDS, _DEFAULT_LAYOUT_FILE_SOURCE,
    _FLAG_KEYWORD_INDEX_CACHE, _LAYOUT_COMPONENTS_CACHE, _LAYOUT_DISPLAY_ORDER_CACHE,
    _LAYOUT_FULL_ORDER_CACHE, _LAYOUT_SCOPE_CACHE, _LAYOUT_TIER_CACHE,
    _RULE_JOIN_DATA_CACHE, _RULE_JOIN_DATA_CACHE_LAST_SEEN_MARKER,
    _RULE_JOIN_DATA_CACHE_TTL_SECONDS,
    _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE,
    _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE_LAST_SEEN_MARKER,
    _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE_TTL_SECONDS, _VALUE_RULES_CACHE,
    _VALUE_RULES_CACHE_LAST_SEEN_MARKER, _VALUE_RULES_CACHE_TTL_SECONDS,
)



# docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_BLIND_PICK_PLAN_2026_08_10.md -- a
# Moved to missing_data_table.py (Phase 4 module-level extraction) --
# re-exported here so every existing `from aryx.cpq.engine import
# <name>` caller/test keeps working unchanged.
from aryx.cpq.missing_data_table import (  # noqa: E402
    _hiding_rule_needs_missing_data_table, _KNOWN_MISSING_DATA_TABLES,
    _table_ingested_for_workspace,
)



# Moved to hint_normalization.py (Phase 4 module-level extraction) --
# re-exported here so every existing `from aryx.cpq.engine import
# <name>` caller/test, and `_engine_module.<name>(...)`'s whole-module-
# reference calls in catalog_hints.py/catalog_hints_negation.py, keep
# working unchanged.
from aryx.cpq.hint_normalization import (  # noqa: E402
    _find_plural_tolerant, _is_negated_before, _normalize_for_hint,
    _normalize_for_hint_with_map, _parenthetical_suffix,
)



# Moved to fill_signature.py (Phase 4 module-level extraction) --
# re-exported here so every existing `from aryx.cpq.engine import
# <name>` caller/test (including auto_fill_resolve's submodules'
# bare-name imports below, and monkeypatch.setattr(engine_module,
# "_fill_signature", ...)) keeps working unchanged. _NEVER_SUPPRESS_
# FRAGMENTS/_CONFIRMED_DEAD_ATTRS (previously defined here) were
# confirmed dead -- unused anywhere in this file or elsewhere, fully
# superseded by data_table_bridge.attr_governance's own copies -- and
# dropped rather than moved.
from aryx.cpq.fill_signature import (  # noqa: E402
    _DECISION_ANCHOR_VNS, _DECISION_REQUIRED_KEYS, _fill_signature,
    _no_real_fill_justification, _SELECT_ALL_NARROWED_LEGAL_MULTI_VNS,
    DECISION_REQUIRED_KEYS,
)


# Moved to blind_fill_constants.py/opt_out_and_duplicates.py (Phase 4
# module-level extraction) -- re-exported here so every existing `from
# aryx.cpq.engine import <name>` caller/test keeps working unchanged.
from aryx.cpq.blind_fill_constants import (  # noqa: E402
    _ATTRSEQ_CONFIRMED_REQUIRED_VNS, _BLIND_FILL_RISK_ACCEPTED_VNS,
)
from aryx.cpq.opt_out_and_duplicates import (  # noqa: E402
    _DUPLICATE_DISPLAY_NAME_CANONICAL_ITEM_VALUE, _OPT_OUT_OPTION_RE,
    _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS, _sole_opt_out_option,
)


# Deferred to here (not the top-of-file import block, and not right after
# _DECISION_REQUIRED_KEYS either — turn_intent's submodules collectively
# need several module-level names defined at various points throughout
# this file, the latest being _DUPLICATE_DISPLAY_NAME_CANONICAL_ITEM_VALUE
# right above): aryx.cpq.turn_intent imports names from this module that
# must already be defined by the time it loads — a top-of-file import
# would be a circular-import failure.
from aryx.cpq import turn_intent  # noqa: E402

# Deferred to here for the same circular-import reason as `turn_intent`
# above: aryx.cpq.hiding_rules' submodules import names BACK from this
# module (logger, _condition_value_matches, _ATTRSEQ_CONFIRMED_REQUIRED_
# VNS, _DATA_TABLE_FORCED_VNS_CACHE + its TTL/marker) — the latest of
# those being `_ATTRSEQ_CONFIRMED_REQUIRED_VNS` just above, so this line
# must sit after it. (`_cpq_model_candidates`/`dt_resolve_whitelist_
# values`, defined/imported elsewhere in this file, are deliberately NOT
# imported by name there — several tests patch them as
# `aryx.cpq.engine.<name>`, so that submodule goes through the module
# object instead.) A top-of-file import would be a circular-import
# failure.
from aryx.cpq import hiding_rules  # noqa: E402

# Deferred to here for the same circular-import reason as `hiding_rules`
# above: aryx.cpq.layout_and_join_data's submodules import `logger` BACK
# from this module by name, so this line must sit after it. (Everything
# else they need — `get_cpq_rdb`, `_RULE_JOIN_DATA_CACHE` + its TTL/marker,
# `_LAYOUT_*_CACHE`, `_DEFAULT_LAYOUT_FILE_SOURCE` — is deliberately NOT
# imported by name there: tests patch `aryx.cpq.engine.get_cpq_rdb` and
# reassign `aryx.cpq.engine._LAYOUT_TIER_CACHE`/`_LAYOUT_SCOPE_CACHE` by
# dotted path, and a frozen import-time reference would silently bypass
# those patches, so that package goes through the module object instead.)
from aryx.cpq import layout_and_join_data  # noqa: E402

# Deferred to here for the same circular-import reason as `hiding_rules`
# above: aryx.cpq.recommendation_and_constraint_rules' submodules import
# `logger`, `_valid` and `_condition_value_matches` BACK from this module
# by name, so this line must sit after all three. (`get_cpq_rdb` is
# deliberately NOT imported by name there — tests patch
# `aryx.cpq.engine.get_cpq_rdb` by dotted path and a frozen import-time
# reference would silently bypass those patches, so build_bml_evaluator
# reaches it through the module object instead.)
from aryx.cpq import recommendation_and_constraint_rules as rec_con_rules  # noqa: E402

# Deferred to here (not the top-of-file imports) because this package
# reaches names BACK from this module. Every one of them
# (`_COUNTRY_TO_REGION`, `_DECISION_REQUIRED_KEYS`, the `_country_*`
# alias helpers, `CpqEngine` itself) is read through the engine MODULE
# object rather than imported by name, so the lookups happen at call
# time — that keeps `_COUNTRY_TO_REGION` (defined further below) usable
# and keeps any dotted-path patch of those names honored, exactly as the
# original in-class `CpqEngine.<name>` / bare-global references were.
from aryx.cpq import governance_and_sibling_exclusivity as gov_sibling  # noqa: E402

# Deferred to here for the same circular-import reason as the packages
# above: aryx.cpq.payload_building reaches `_cpq_model_candidates`,
# `dt_resolve_whitelist_values`, `dt_resolve_region_allow_value`,
# `dt_governed_required_attr_names_for_base_model` and
# `_COUNTRY_TO_REGION` BACK from this module. All five are read through
# the engine MODULE object rather than imported by name, so the lookups
# happen at call time — that keeps `_cpq_model_candidates` and
# `_COUNTRY_TO_REGION` (both defined further below) usable, and keeps the
# dotted-path patches several tests apply to those names honored, exactly
# as the original bare-global references were.
from aryx.cpq import payload_building  # noqa: E402

# Deferred for the same circular-import reason as the imports above:
# `rule_specificity_ranking` imports this module BACK (to reach
# `CpqEngine._rule_condition_edges` through the engine MODULE object, so
# the original class-attribute lookup — and any patch of it — still
# applies at call time). The name is only ever resolved when a method
# runs, never at import time.
from aryx.cpq import rule_specificity_ranking  # noqa: E402

# Product-line selectors that list the full multi-family portfolio (~325
# models). Must wait until Hardware Version is filled on hardware-based
# catalogs — otherwise next_question_prompt dumps the unconstrained list.
_PRODUCT_LINE_SELECTOR_EXACT: frozenset[str] = frozenset({
    "productSelectionProduct_all",
})

# Attrs confirmed live (docs/CPQ_SCRIPT_GOVERNED_GUESS_ISSUE.md) to be
# governed EXCLUSIVELY by a script-based recommendation rule that can
# legitimately resolve to "no recommendation" (not just "unknown") — for
# these, auto_fill's blind first-by-order fallback ("safe because a rule
# REQUIRES this attr to be resolved") must not fire, since the rule can
# validly decline to recommend anything. Deliberately an explicit,
# narrow allowlist rather than a blanket "any script-only-governed attr"
# rule: the blanket version (commit 59074de, reverted) silenced this
# fallback for APX Next's entire catalog too (601 recommendation rules,
# almost all script-only, per the same pattern) — turning its working
# instant-complete flow into ~30 unwanted questions on a fresh quote.
# Add a new variable_name here only after live-reproducing the same
# failure mode, the same way this one was found.
_NEVER_GUESS_SCRIPT_GOVERNED: frozenset[str] = frozenset({
    "wouldYouLikeToIncludeABatterySubscription_viSoln",
})

# Deferred to here (not the top-of-file imports) for the same reason as
# `turn_intent`'s import below: `auto_fill_resolve` imports several names
# BACK from this module (_valid, _fill_signature, _country_alias_group,
# _no_real_fill_justification, _sole_opt_out_option, _DECISION_REQUIRED_
# KEYS, _DECISION_ANCHOR_VNS, _KNOWN_MISSING_DATA_TABLES, _NEVER_GUESS_
# SCRIPT_GOVERNED, _BLIND_FILL_RISK_ACCEPTED_VNS, _OPTIONAL_EMPTY_FILL_
# ACCEPTED_VNS, _SELECT_ALL_NARROWED_LEGAL_MULTI_VNS, logger) — this line
# must sit after every one of those is already defined above.
from aryx.cpq.auto_fill import auto_fill_hw_order
from aryx.cpq import catalog_hints
from aryx.cpq import mandatory_input
from aryx.cpq.auto_fill import auto_fill_postpass
from aryx.cpq.auto_fill import auto_fill_resolve
from aryx.cpq.auto_fill_stages import fill_log as _fill_log

_DEFAULT_CPQ_MODEL_CANDIDATES: tuple[str, ...] = ("APXNEXT", "APXNEXT_BOM")


def _cpq_model_candidates(
    product_name: str, workspace_id: int | None = None, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None, base_model: str = "",
) -> tuple[str, ...]:
    return data_table_bridge._cpq_model_candidates(
        product_name, workspace_id, catalog_prefix, cache, base_model,
    )


# Moved to bml_util_substitution.py (Phase 4 module-level extraction)
# -- re-exported here so every existing `from aryx.cpq.engine import
# <name>` caller/test keeps working unchanged.
from aryx.cpq.bml.bml_util_substitution import (  # noqa: E402
    _substitute_util_get_constraint_vals, _UTIL_ATTR_VAR_NAME_RE,
    _UTIL_GET_CONSTRAINT_VALS_CALL_RE,
)

# Summary categories (§ render_filled_summary grouping) — structural
# fragment-matching against variable_name, same convention as
# Moved to summary_category_constants.py (Phase 4 module-level
# extraction) -- re-exported here so every existing `from
# aryx.cpq.engine import <name>` caller/test, and
# summary_display_formatting's `_engine_module.<name>` whole-module-
# reference reads, keep working unchanged.
from aryx.cpq.summary_category_constants import (  # noqa: E402
    _ASSOCIATED_OPTIONS_KEY_FRAGMENTS, _SUMMARY_CATEGORY_KEYS,
    _SUMMARY_FALLBACK_CATEGORY, _SUMMARY_MANDATORY_CATEGORY,
    SUMMARY_CATEGORY_NAMES, SUMMARY_FALLBACK_CATEGORY,
)

# Deferred for the same circular-import reason as the imports above:
# `summary_display_formatting` imports this module BACK (to reach the
# `_SUMMARY_CATEGORY_KEYS` / `_SUMMARY_FALLBACK_CATEGORY` /
# `_SUMMARY_MANDATORY_CATEGORY` tables just above through the engine
# MODULE object, so the original bare-global references — and any patch
# of them — still resolve at call time). The name is only ever resolved
# when a method runs, never at import time.
from aryx.cpq import summary_display_formatting  # noqa: E402


# Moved to region_and_noise_constants.py (Phase 4 module-level
# extraction) -- re-exported here so every existing `from
# aryx.cpq.engine import <name>` caller/test keeps working unchanged.
from aryx.cpq.region_and_noise_constants import (  # noqa: E402
    _COUNTRY_TO_REGION, _LAYOUT_TYPE_FRAGMENTS, _NOISE_ITEM_FRAGMENTS,
    _NOISE_VAR_FRAGMENTS,
)

# aryx.cpq.constraint_rules.constraint_rules's submodules import _substitute_util_get_
# constraint_vals/_condition_value_matches BACK from this module by name
# -- this line must sit after both are already defined above (the last
# being _substitute_util_get_constraint_vals, right above).
from aryx.cpq.constraint_rules import constraint_rules  # noqa: E402
from aryx.cpq.rules_loop import rules_loop  # noqa: E402
from aryx.cpq.payload import payload_build  # noqa: E402
from aryx.cpq.value_rules import value_rules_load  # noqa: E402


# Moved to attr_type_classification.py (Phase 4 module-level
# extraction) -- re-exported here so every existing `from
# aryx.cpq.engine import classify_select_type` caller/test keeps
# working unchanged.
from aryx.cpq.attr_type_classification import classify_select_type  # noqa: E402



@dataclass
class FillContext:
    """Bundles `auto_fill`'s truly-shared, cross-attribute mutable state
    (Phase 4 step 3, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md's
    "FillContext Decomposition Design") — the objects every per-attr
    resolution (`_resolve_one_attr`, née P1) and post-pass (P2/P3) reads
    and writes. `_resolve_one_attr` reads/writes every field below
    exclusively via `ctx.*` (confirmed via `symtable` — zero bare-local
    leaks of these names remain in its body).

    `display_filled`/`pending`/`user_answered_dropped_ids` were added
    when `_resolve_one_attr` was relocated out of `auto_fill`'s own
    scope (Phase 4, the mechanical `auto_fill_resolve` move) — same
    "shared across every attr in one call" property as the original 6,
    just not noticed until the move required threading them explicitly
    instead of via closure.
    """

    filled: dict[str, str]
    filled_multi: dict[str, list[str]]
    sources: dict[str, str]
    dropped: dict[str, list[str]]
    dt_cache: dict[tuple[int, str], tuple]
    default_fill_signatures: dict[str, tuple] | None
    display_filled: dict[str, str]
    pending: list["ConfigAttr"]
    user_answered_dropped_ids: set[int]


@dataclass(frozen=True)
class FillScope:
    """Bundles `_resolve_one_attr`'s read-only, per-`auto_fill`-call
    inputs (Phase 4, the `auto_fill_resolve` move) — everything it needs
    besides `attr` itself and the mutable `FillContext`. Built once, right
    before the per-attribute loop, from `auto_fill`'s own parameters and
    P0 precomputed values.

    `is_pointer_default`/`satisfied_recommendation`/`dt_never_governed_
    anywhere` are the three closures `auto_fill`'s P0 setup already builds
    (over `_all_vns`/`rec_by_target`/`attr_by_rule_id`/`bml_eval`/`filled`
    and `_dt_candidates`/`_dt_cache`/`workspace_id`/`catalog_prefix`
    respectively) — threaded through as already-bound callables rather
    than re-parameterized, so their own definitions never had to move.
    """

    hints: dict[str, str]
    attrs: list["ConfigAttr"]
    constrained_opts: dict[int, list[str]] | None
    country: str | None
    negated_vns: set[str] | None
    skip_always_ask: set[str] | None
    bml_eval: "BmlEvaluator | None"
    validation_rules: "list[ValidationRule] | None"
    display_order: dict[str, int] | None
    workspace_id: int | None
    catalog_prefix: str
    product_anchor_hint: str | None
    signature_exclude_vns: frozenset[str] | None
    grid_declined_vns: "frozenset[str] | None"
    governed: set[int]
    rule_governed: set[int]
    rec_by_target: dict[int, list["RecommendationRule"]]
    grid_selector_vns: set[str]
    bm_region_allow_value: str | None
    dt_governed_vns: set[str]
    missing_data_target_ids: set[int]
    conflicted_optional_ids: set[int]
    is_pointer_default: "Any"
    satisfied_recommendation: "Any"
    dt_never_governed_anywhere: "Any"


# Deferred: auto_fill_setup imports FillContext/FillScope BACK from this
# module, so it must be placed after both class definitions above.
from aryx.cpq.auto_fill import auto_fill_run  # noqa: E402
from aryx.cpq.auto_fill import auto_fill_setup  # noqa: E402
from aryx.cpq.product_config import product_config_load  # noqa: E402


class CpqEngine:
    """Drives guided CPQ configuration within the Ask conversation."""

    # Maximum turns before declaring complete (even if attrs remain)
    MAX_TURNS: int = 5

    # ── Intent detection ──────────────────────────────────────────────────────

    def is_cpq_question(self, question: str, reader: Any = None, workspace_id: int = 1) -> bool:
        return nl_hint_extraction.question_hints.is_cpq_question(self, question, reader, workspace_id)

    def extract_hints(self, question: str) -> dict[str, str]:
        return nl_hint_extraction.question_hints.extract_hints(self, question)

    def extract_catalog_hints(
        self, question: str, attrs: list["ConfigAttr"],
    ) -> tuple[dict[str, str], set[str]]:
        return catalog_hints.extract_catalog_hints(self, question, attrs)


    def _build_flag_keyword_index(
        self, attrs: list["ConfigAttr"], workspace_id: int, catalog_prefix: str,
    ) -> dict[str, tuple[str, str]]:
        return nl_hint_extraction.flag_hints._build_flag_keyword_index(self, attrs, workspace_id, catalog_prefix)

    def extract_flag_hints(
        self, question: str, attrs: list["ConfigAttr"],
        workspace_id: int, catalog_prefix: str,
    ) -> dict[str, str]:
        return nl_hint_extraction.flag_hints.extract_flag_hints(self, question, attrs, workspace_id, catalog_prefix)

    def find_unresolvable_context_attrs(
        self,
        attrs: list["ConfigAttr"],
        filled: dict[str, str],
        workspace_id: int,
        catalog_prefix: str,
        rec_rules: list["RecommendationRule"],
        con_rules: list["ConstraintRule"],
    ) -> list[dict[str, Any]]:
        return nl_hint_extraction.unresolvable_context.find_unresolvable_context_attrs(self, attrs, filled, workspace_id, catalog_prefix, rec_rules, con_rules)

    def _ingested_product_names(self, reader: Any, workspace_id: int) -> list[str]:
        return nl_hint_extraction.ingested_products._ingested_product_names(self, reader, workspace_id)

    def ingested_product_alias_map(self, reader: Any, workspace_id: int) -> dict[str, str]:
        return nl_hint_extraction.ingested_products.ingested_product_alias_map(self, reader, workspace_id)

    def single_model_variable_name(
        self, reader: Any, workspace_id: int, catalog_prefix: str,
    ) -> str:
        return nl_hint_extraction.model_leaves.single_model_variable_name(self, reader, workspace_id, catalog_prefix)

    def model_variable_candidates(
        self, reader: Any, workspace_id: int, catalog_prefix: str,
    ) -> list[str]:
        return nl_hint_extraction.model_leaves.model_variable_candidates(self, reader, workspace_id, catalog_prefix)

    def model_catalog_path(
        self,
        reader: Any,
        workspace_id: int,
        catalog_prefix: str,
        model: str,
        product_family: str = "",
    ) -> dict[str, str]:
        return nl_hint_extraction.model_path.model_catalog_path(self, reader, workspace_id, catalog_prefix, model, product_family)

    def detect_product_mention(
        self, question: str, hints: dict[str, str],
        reader: Any = None, workspace_id: int = 1,
        alias_map: dict[str, str] | None = None,
    ) -> str:
        return nl_hint_extraction.product_mention.detect_product_mention(self, question, hints, reader, workspace_id, alias_map)

    @staticmethod
    def _question_tokens(question: str) -> frozenset[str]:
        return nl_hint_extraction.fuzzy_scoring._question_tokens(question)

    @staticmethod
    def _fuzzy_score_candidates(
        q_norm: str, ordered: list[tuple[str, str]],
        question_tokens: frozenset[str] | None = None,
    ) -> list[tuple[str, float]]:
        return nl_hint_extraction.fuzzy_scoring._fuzzy_score_candidates(q_norm, ordered, question_tokens)

    def suggest_product_candidates(
        self, question: str, reader: Any, workspace_id: int,
        exclude: str = "", limit: int = 5,
        alias_map: dict[str, str] | None = None,
    ) -> list[str]:
        return nl_hint_extraction.product_suggestions.suggest_product_candidates(self, question, reader, workspace_id, exclude, limit, alias_map)

    def check_country_availability(
        self,
        attrs: list[ConfigAttr],
        con_rules: list["ConstraintRule"],
        filled: dict[str, str],
        bml_eval: BmlEvaluator,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
    ) -> bool:
        return nl_hint_extraction.country_availability.check_country_availability(self, attrs, con_rules, filled, bml_eval, workspace_id, catalog_prefix)

    # ── PostgreSQL attribute fetch ────────────────────────────────────────────

    def _batch_fetch(
        self, entity_ids: list[int], workspace_id: int,
    ) -> dict[int, dict[str, Any]]:
        return nl_hint_extraction.entity_fetch._batch_fetch(self, entity_ids, workspace_id)

    # ── Graph loading ─────────────────────────────────────────────────────────

    def _is_layout_noise(self, ontology_type: str) -> bool:
        return nl_hint_extraction.entity_fetch._is_layout_noise(self, ontology_type)

    def _match_family_name(
        self, reader: Any, workspace_id: int, prefix: str, hint_norm: str,
    ) -> str | None:
        return nl_hint_extraction.entity_fetch._match_family_name(self, reader, workspace_id, prefix, hint_norm)

    def _match_basemodel_to_config_name(
        self, reader: Any, workspace_id: int, prefix: str, hint_norm: str,
        rdb_cache: dict | None = None,
    ) -> str | None:
        return nl_hint_extraction.entity_fetch._match_basemodel_to_config_name(self, reader, workspace_id, prefix, hint_norm, rdb_cache)

    def _scope_to_catalog(
        self, reader: Any, workspace_id: int, attr_types: list[str], product_hint: str,
    ) -> tuple[list[str], str]:
        return nl_hint_extraction.catalog_scoping._scope_to_catalog(self, reader, workspace_id, attr_types, product_hint)

    # Fallback structural signal for _fetch_product_option_list when no attr
    # is literally named "productSelectionProduct_all" — see that method's
    # docstring. Matches the common BM naming convention for a product-line
    # variant selector without hardcoding one catalog's exact field name.
    _PRODUCT_FIELD_FALLBACK_RE = re.compile(r"product", re.IGNORECASE)
    _PRODUCT_FIELD_FALLBACK_HINT_RE = re.compile(r"select|line", re.IGNORECASE)

    def _fetch_product_option_list(
        self, reader: Any, workspace_id: int, prefix: str,
    ) -> list[tuple[str, str]]:
        return nl_hint_extraction.product_option_fetch.fetch_product_option_list(self, reader, workspace_id, prefix)

    def resolve_product_hint(
        self, reader: Any, workspace_id: int, hint_text: str,
    ) -> tuple[str, str] | None:
        return nl_hint_extraction.product_hint_resolve.resolve_product_hint(self, reader, workspace_id, hint_text)

    def list_ingested_families(
        self, reader: Any, workspace_id: int,
    ) -> list[str]:
        return nl_hint_extraction.families.list_ingested_families(self, reader, workspace_id)

    def ingested_family_labels(
        self, reader: Any, workspace_id: int,
    ) -> dict[str, str]:
        _t0 = time.monotonic()
        result = nl_hint_extraction.families.ingested_family_labels(self, reader, workspace_id)
        raven_log("DEBUG", "P4", "ask.family_labels.delegated engine delegated to nl_hint_extraction.families",
                  context={"dependency_name": "nl_hint_extraction.families.ingested_family_labels",
                           "operation": "ingested_family_labels", "duration_ms": int((time.monotonic() - _t0) * 1000),
                           "result": "ok", "error_class": "none", "attempt": 1, "trace_id": str(uuid.uuid4()),
                           "task_id": f"family-labels-{workspace_id}", "final_status": "done",
                           "stage": "ingested_family_labels", "reason_code": "DELEGATED_OK",
                           "impact_scope": f"workspace:{workspace_id}"})
        return result

    def load_product_config(
        self,
        reader: Any,
        workspace_id: int,
        product_hint: str,
    ) -> tuple[list[ConfigAttr], str]:
        """Load configuration attributes for the identified product.

        Steps:
          1. Find bm_config_attr entities in the graph.
          2. Fetch their full attributes from PostgreSQL (variable_name,
             default_value, required, hidden, order_number).
          3. For each attr, get bm_menu_item neighbors and fetch their
             item_value + item_text from PostgreSQL.
          4. Build ConfigAttr list sorted by order_number.

        Returns (attrs, resolved_product_name).
        """
        return product_config_load.load_product_config(
            self, reader, workspace_id, product_hint,
        )

    # ── Rule loaders (dialect-agnostic via cpq.rdb) ──────────────────────────

    # ── Rule-join fetch / target resolution + native-UI layout cluster ───
    # The sixteen methods below are one-line delegating wrappers; the real
    # implementations now live in `aryx.cpq.layout_and_join_data` (Phase 4
    # step 5, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md), which also
    # carries their full docstrings. Only the ones that genuinely need the
    # live instance (or, for the classmethod, the class) pass it through as
    # the module function's leading `engine`/`cls` argument; the rest need
    # nothing from it. Signatures, method order, and staticmethod/
    # classmethod-ness are unchanged, so every existing call site
    # (`self.foo(...)`, `_cpq_engine.foo(...)`, `engine.foo(...)` from
    # hiding_rules) keeps working unchanged, and so does every
    # `monkeypatch.setattr(eng, "foo", ...)` / `patch.object` in tests.

    def _load_rule_join_data(
        self, workspace_id: int, catalog_prefix: str = ""
    ) -> tuple[
        PostgresCpqRdb,
        dict[int, list[tuple[int, str, str]]],
        dict[int, list[tuple[int, int, str, int, int, str]]],
        dict[int, list[int]],
        dict[int, int],
    ]:
        return layout_and_join_data._load_rule_join_data(workspace_id, catalog_prefix)

    @staticmethod
    def _resolve_targets(
        rule_key: int,
        actions_by_rule: dict[int, list[tuple[int, int, str, int, int, str]]],
        marked_by_rule: dict[int, list[int]],
        chain_by_rule: dict[int, int],
        max_hops: int = 3,
    ) -> list[tuple[int, int]]:
        return layout_and_join_data._resolve_targets(
            rule_key, actions_by_rule, marked_by_rule, chain_by_rule, max_hops,
        )

    @staticmethod
    def _rule_key(entity_id: int, source_id: int | None,
                  inputs: dict, actions: dict) -> int:
        return layout_and_join_data._rule_key(entity_id, source_id, inputs, actions)

    @staticmethod
    def _condition_has_operator_collision(conditions: list[tuple[int, str, str]]) -> bool:
        return layout_and_join_data._condition_has_operator_collision(conditions)

    def _detect_layout_tier(self, workspace_id: int, catalog_prefix: str = "") -> int:
        return layout_and_join_data._detect_layout_tier(workspace_id, catalog_prefix)

    def _is_country_anchor_var(self, variable_name: str) -> bool:
        return layout_and_join_data._is_country_anchor_var(self, variable_name)

    def _find_country_anchor_attr_id(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> int | None:
        return layout_and_join_data._find_country_anchor_attr_id(
            self, workspace_id, catalog_prefix,
        )

    def resolve_ui_layout_scope(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> dict[str, Any] | None:
        return layout_and_join_data.resolve_ui_layout_scope(
            self, workspace_id, catalog_prefix,
        )

    @staticmethod
    def _walk_layout_components(node: Any) -> list[dict[str, Any]]:
        return layout_and_join_data._walk_layout_components(node)

    @classmethod
    def _load_layout_components(
        cls, workspace_id: int, catalog_prefix: str,
        layout_source: LayoutFileSource | None,
    ) -> list[dict[str, Any]] | None:
        return layout_and_join_data._load_layout_components(
            cls, workspace_id, catalog_prefix, layout_source,
        )

    def load_layout_display_order(
        self, workspace_id: int, catalog_prefix: str = "",
        layout_source: LayoutFileSource | None = None,
    ) -> dict[str, int] | None:
        return layout_and_join_data.load_layout_display_order(
            self, workspace_id, catalog_prefix, layout_source,
        )

    def _load_layout_full_order(
        self, workspace_id: int, catalog_prefix: str = "",
        layout_source: LayoutFileSource | None = None,
    ) -> dict[str, int] | None:
        return layout_and_join_data._load_layout_full_order(
            self, workspace_id, catalog_prefix, layout_source,
        )

    def resolve_always_ask_skips(
        self, workspace_id: int, catalog_prefix: str, attrs: list[ConfigAttr],
    ) -> set[str]:
        return layout_and_join_data.resolve_always_ask_skips(
            self, workspace_id, catalog_prefix, attrs,
        )

    def resolve_primary_layout_section_vns(
        self, workspace_id: int, catalog_prefix: str, attrs: list["ConfigAttr"],
    ) -> set[str] | None:
        return layout_and_join_data.resolve_primary_layout_section_vns(
            self, workspace_id, catalog_prefix, attrs,
        )

    @staticmethod
    def model_context_mirror_vns(attrs: list["ConfigAttr"]) -> set[str]:
        return layout_and_join_data.model_context_mirror_vns(attrs)

    def payload_flow_exclusions(
        self, workspace_id: int, catalog_prefix: str, attrs: list["ConfigAttr"],
    ) -> set[str]:
        return layout_and_join_data.payload_flow_exclusions(
            self, workspace_id, catalog_prefix, attrs,
        )

    # ── Array-grid / per-option-quantity cluster ─────────────────────────
    # The nine methods below are one-line delegating wrappers; the real
    # implementations now live in `aryx.cpq.grid_quantity` (Phase 4 step 3,
    # docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md), which also carries
    # their full docstrings. Only `append_pending_grid_quantities` needs
    # anything from the live instance (`_is_svx_mounting_array_quantity_attr`,
    # which stays here), so it passes `self` through as the module
    # function's leading `engine` argument; the other eight need nothing
    # from the instance. Signatures, method order, and staticmethod-ness are
    # unchanged, so every existing call site (`self.foo(...)`,
    # `_cpq_engine.foo(...)`, `engine.foo(...)` from turn_intent/
    # auto_fill_resolve) keeps working unchanged.

    @staticmethod
    def array_grid_controls_in_play(attrs: list[ConfigAttr]) -> list[str]:
        return grid_quantity.array_grid_controls_in_play(attrs)

    @staticmethod
    def resolve_array_grid_links(attrs: list[ConfigAttr]) -> dict[str, dict[str, str]]:
        return grid_quantity.resolve_array_grid_links(attrs)

    def is_grid_quantity_attr(self, attr: ConfigAttr, attrs: list[ConfigAttr]) -> bool:
        return grid_quantity.is_grid_quantity_attr(attr, attrs)

    def parse_grid_quantity_reply(self, text: str) -> str | None:
        return grid_quantity.parse_grid_quantity_reply(text)

    def parse_grid_batch_quantities(
        self, candidates: list[tuple[str, str]], user_answer: str,
    ) -> dict[str, int]:
        return grid_quantity.parse_grid_batch_quantities(candidates, user_answer)

    @staticmethod
    def grid_batch_count_mismatch(
        candidates: list[tuple[str, str]], user_answer: str,
    ) -> int | None:
        return grid_quantity.grid_batch_count_mismatch(candidates, user_answer)

    @staticmethod
    def grid_batch_unparseable_segment(
        candidates: list[tuple[str, str]], user_answer: str,
    ) -> str | None:
        return grid_quantity.grid_batch_unparseable_segment(candidates, user_answer)

    def resolve_pending_grid_quantities(
        self, attrs: list[ConfigAttr], filled: dict[str, str],
        filled_multi: dict[str, list[str]],
        constrained_opts: dict[int, list[str]] | None = None,
        selector_vns: set[str] | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        dt_cache: dict[tuple[int, str], tuple] | None = None,
    ) -> list[ConfigAttr]:
        return grid_quantity.resolve_pending_grid_quantities(
            attrs, filled, filled_multi, constrained_opts, selector_vns,
            workspace_id, catalog_prefix, dt_cache,
        )

    def _finalize_grid_selections_from_quantities(
        self, attrs: list[ConfigAttr], filled: dict[str, str],
        filled_multi: dict[str, list[str]],
        filled_source: dict[str, str] | None = None,
        constrained_opts: dict[int, list[str]] | None = None,
    ) -> None:
        grid_quantity._finalize_grid_selections_from_quantities(
            attrs, filled, filled_multi, filled_source, constrained_opts,
        )

    def append_pending_grid_quantities(
        self, pending: list[ConfigAttr], attrs: list[ConfigAttr],
        filled: dict[str, str], filled_multi: dict[str, list[str]],
        filled_source: dict[str, str] | None = None,
        constrained_opts: dict[int, list[str]] | None = None,
        selector_vns: set[str] | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        dt_cache: dict[tuple[int, str], tuple] | None = None,
    ) -> list[ConfigAttr]:
        return grid_quantity.append_pending_grid_quantities(
            self, pending, attrs, filled, filled_multi, filled_source,
            constrained_opts, selector_vns, workspace_id, catalog_prefix, dt_cache,
        )

    @staticmethod
    def grid_selector_remaining_options(
        attr: "ConfigAttr",
        filled_multi: dict[str, list[str]],
        constrained_opts: dict[int, list[str]] | None,
    ) -> list["MenuOption"]:
        return grid_quantity.grid_selector_remaining_options(
            attr, filled_multi, constrained_opts,
        )

    def unresolved_grid_quantity_options(
        self, attrs: list[ConfigAttr], filled_multi: dict[str, list[str]],
    ) -> list[tuple[str, str]]:
        return grid_quantity.unresolved_grid_quantity_options(attrs, filled_multi)


    def load_hiding_rules(
        self, workspace_id: int, catalog_prefix: str = "", product_name: str = "",
    ) -> list[HidingRule]:
        return hiding_rules.load_hiding_rules(self, workspace_id, catalog_prefix, product_name)

    @staticmethod
    def _attr_index(attrs: list[ConfigAttr]) -> dict[int, ConfigAttr]:
        return hiding_rules._attr_index(attrs)

    @staticmethod
    def _rule_forced_from_active_decision_vns(
        rules: list[Any] | None, attrs: list[ConfigAttr] | None,
        filled_source: dict[str, str], active_sources: frozenset[str],
    ) -> frozenset[str]:
        return hiding_rules._rule_forced_from_active_decision_vns(
            rules, attrs, filled_source, active_sources,
        )

    @staticmethod
    def _data_table_forced_vns(
        filled: dict[str, str], workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
        filled_multi: dict[str, list[str]] | None = None,
    ) -> frozenset[str]:
        return hiding_rules._data_table_forced_vns(
            filled, workspace_id, catalog_prefix, cache, filled_multi,
        )

    @staticmethod
    def _filled_by_rule_id(
        attrs: list[ConfigAttr], filled: dict[str, str],
        filled_multi: dict[str, list[str]] | None = None,
    ) -> dict[int, str]:
        return hiding_rules._filled_by_rule_id(attrs, filled, filled_multi)

    def apply_hiding_rules(
        self,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        rules: list[HidingRule],
        bml_eval: BmlEvaluator | None = None,
        filled_multi: dict[str, list[str]] | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        dt_cache: dict[tuple[int, str], tuple] | None = None,
    ) -> tuple[list[ConfigAttr], list[str], set[str]]:
        return hiding_rules.apply_hiding_rules(
            attrs, filled, rules, bml_eval, filled_multi,
            workspace_id=workspace_id, catalog_prefix=catalog_prefix, dt_cache=dt_cache,
        )

    # ── Recommendation rule loader ────────────────────────────────────────────

    def _load_value_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> tuple[
        list[RecommendationRule], list[ConstraintRule], list[ValidationRule],
        list[HidingRule],
    ]:
        """Load recommendation + constraint + validation + (a subset of)
        hiding rules together in one pass.

        Historical note: this originally filtered by a hardcoded rule_type
        ("10" for recommendation, "5" for constraint) and action_type ("3"
        for recommend, "4" for constrain). NEITHER exists anywhere in either
        ingested catalog (APX Next, SL3500e) — confirmed empirically: real
        rule_type codes seen are 1/2/4/6/9/11/23, never 5 or 10, and
        action_type only ever takes the values 1/2. rule_type turns out to
        be tenant/catalog-specific numbering (the two catalogs even use
        DIFFERENT codes for the same semantic categories, and SL3500e
        introduces codes never seen in APX Next at all), so it cannot be
        used to select rule categories.

        The signal that DOES hold consistently across both catalogs is
        set_type on each declarative rule action: set_type == -1 always
        means "remove this value from the allowed set" (constraint); any
        other set_type means "assign this specific value" (recommendation/
        default) EXCEPT when the action carries no value1 at all and
        set_type is 1 or 3 — confirmed (docs/CPQ_VALUELESS_HIDE_ACTION_
        LOADING_GAP_PLAN_2026_08_05.md) via cross-catalog rule-name sampling
        to be a genuine "hide" action authored outside rule_type=11 (hiding
        needs no value to assign). This classifies every non-rule_type=11
        rule by inspecting its own actions instead of trusting rule_type/
        action_type.

        The BULK of hiding rules (rule_type=11) are unaffected by any of
        this — that code has proven reliable across both catalogs and is
        loaded separately by load_hiding_rules(). The 4th return value here
        is a SEPARATE, ADDITIONAL subset of hiding rules this codebase used
        to silently drop (see the plan doc above for the 1,096-action,
        421-rule, 4-catalog audit) — callers needing the complete hiding
        rule set must merge both (see load_recommendation_and_constraint_
        rules' return type).

        catalog_prefix — scopes to one ingested catalog (see
        _load_rule_join_data) when the workspace holds more than one
        product's XML export. "" preserves the original workspace-wide load.
        """
        _cache_key = (workspace_id, catalog_prefix)
        _marker_at_read = _invalidate_on_marker_change(_VALUE_RULES_CACHE, _VALUE_RULES_CACHE_LAST_SEEN_MARKER)
        _cache_hit = _VALUE_RULES_CACHE.get(_cache_key)
        if _cache_hit is not None:
            _cache_ts, _cache_result = _cache_hit
            if time.monotonic() - _cache_ts < _VALUE_RULES_CACHE_TTL_SECONDS:
                logger.info(
                    "cpq_perf: _load_value_rules CACHE HIT ws=%s prefix=%r",
                    workspace_id, catalog_prefix,
                )
                _fill_log.log_load("value_rules_cache", result="hit", workspace_id=workspace_id,
                                   catalog_prefix=catalog_prefix)
                return rule_scope.scope_value_rules_tuple(_cache_result, workspace_id, catalog_prefix)
        _fill_log.log_load("value_rules_cache", result="miss" if _cache_hit is None else "expired",
                           workspace_id=workspace_id, catalog_prefix=catalog_prefix)

        _t0 = time.monotonic()
        logger.info(
            "cpq_step: _load_value_rules (rec/con/validation) start "
            "workspace_id=%s catalog_prefix=%r", workspace_id, catalog_prefix,
        )
        # Ambiguous multi-value recommendations are never guessed (D2) — instead
        # routed through the same HITL ingest-question queue used elsewhere for
        # ingest-time ambiguity. Prefetch existing rows once so 14 rules don't
        # cost 14 round-trips, and so an already-answered rule resolves normally
        # instead of being skipped forever.
        try:
            ingest_store = IngestQuestionStore(get_settings().effective_dsn())
            existing_questions = {
                q["job_id"]: q for q in ingest_store.list(workspace_id, status="")
            }
        except Exception as exc:
            _fill_log.log_load_failed("ingest_question_store", exc, "INGEST_QUESTION_STORE_UNAVAILABLE",
                                      workspace_id=workspace_id)
            ingest_store = None
            existing_questions = {}
        _result = value_rules_load.load_value_rules(
            self, workspace_id, catalog_prefix, ingest_store, existing_questions, _t0,
        )
        _cache_write_if_marker_unchanged(_VALUE_RULES_CACHE, _cache_key, (time.monotonic(), _result), _marker_at_read)
        return rule_scope.scope_value_rules_tuple(_result, workspace_id, catalog_prefix)

    def load_recommendation_and_constraint_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> tuple[list[RecommendationRule], list[ConstraintRule]]:
        return rec_con_rules.load_recommendation_and_constraint_rules(
            self, workspace_id, catalog_prefix)

    def load_validation_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[ValidationRule]:
        return rec_con_rules.load_validation_rules(
            self, workspace_id, catalog_prefix)

    def load_recommendation_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[RecommendationRule]:
        return rec_con_rules.load_recommendation_rules(
            self, workspace_id, catalog_prefix)

    def apply_recommendation_rules(
        self,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        rules: list[RecommendationRule],
        bml_eval: BmlEvaluator | None = None,
        filled_multi: dict[str, list[str]] | None = None,
        constrained_opts: dict[int, list[str]] | None = None,
    ) -> dict[str, tuple[str, str]]:
        return rec_con_rules.apply_recommendation_rules(
            attrs, filled, rules, bml_eval, filled_multi, constrained_opts)

    def resync_stale_recommendations(
        self,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_source: dict[str, str] | None,
        rules: list[RecommendationRule],
        bml_eval: BmlEvaluator | None = None,
        filled_multi: dict[str, list[str]] | None = None,
        constrained_opts: dict[int, list[str]] | None = None,
    ) -> dict[str, tuple[str, str]]:
        return rec_con_rules.resync_stale_recommendations(
            attrs, filled, filled_source, rules, bml_eval, filled_multi,
            constrained_opts)

    def apply_validation_rules(
        self,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        rules: list[ValidationRule],
        bml_eval: BmlEvaluator | None = None,
        filled_multi: dict[str, list[str]] | None = None,
    ) -> dict[str, str]:
        return rec_con_rules.apply_validation_rules(
            attrs, filled, rules, bml_eval, filled_multi)

    # ── Constraint rule loader ────────────────────────────────────────────────

    def load_constraint_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[ConstraintRule]:
        return rec_con_rules.load_constraint_rules(
            self, workspace_id, catalog_prefix)

    def build_bml_evaluator(
        self, workspace_id: int, catalog_prefix: str = "", run_id: str = "",
    ) -> BmlEvaluator:
        return rec_con_rules.build_bml_evaluator(workspace_id, catalog_prefix, run_id=run_id)

    def apply_constraint_rules(
        self,
        attrs: list[ConfigAttr],
        rules: list[ConstraintRule],
        filled: dict[str, str],
        bml_eval: BmlEvaluator | None = None,
        filled_multi: dict[str, list[str]] | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        _dt_cache: dict[tuple[int, str], tuple] | None = None,
        _constraint_cache: dict[str, tuple] | None = None,
        _signature_exclude_vns: frozenset[str] | None = None,
        narrowing_rec_rules: list[RecommendationRule] | None = None,
        narrow_from_data_tables: bool = False,
    ) -> dict[int, list[str]]:
        return constraint_rules.apply_constraint_rules(
            self, attrs, rules, filled, bml_eval, filled_multi,
            workspace_id, catalog_prefix, _dt_cache, _constraint_cache,
            _signature_exclude_vns, narrowing_rec_rules, narrow_from_data_tables,
        )


    # ── Rule-consistency cross-check ──────────────────────────────────────────

    def find_rule_inconsistencies(
        self,
        filled: dict[str, str],
        attrs: list[ConfigAttr],
        hiding_rules: list[HidingRule],
        con_rules: list[ConstraintRule],
        rec_rules: list[RecommendationRule],
        bml_eval: BmlEvaluator | None = None,
        filled_source: dict[str, str] | None = None,
        filled_multi: dict[str, list[str]] | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
    ) -> list[dict[str, Any]]:
        return rec_con_rules.find_rule_inconsistencies(
            self, filled, attrs, hiding_rules, con_rules, rec_rules, bml_eval,
            filled_source, filled_multi, workspace_id, catalog_prefix)

    # ── Rule evaluation loop ──────────────────────────────────────────────────

    def evaluate_rules_loop(
        self,
        attrs: list[ConfigAttr],
        hints: dict[str, str],
        filled: dict[str, str],
        hiding_rules: list[HidingRule],
        rec_rules: list[RecommendationRule],
        con_rules: list[ConstraintRule],
        bml_eval: BmlEvaluator | None = None,
        filled_source: dict[str, str] | None = None,
        filled_multi: dict[str, list[str]] | None = None,
        dropped_multi: dict[str, list[str]] | None = None,
        country: str | None = None,
        negated_vns: set[str] | None = None,
        skip_always_ask: set[str] | None = None,
        rule_conflict_order: dict[str, int] | None = None,
        display_order: dict[str, int] | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        product_anchor_hint: str | None = None,
        _dt_cache: dict[tuple[int, str], tuple] | None = None,
    ) -> tuple[list[ConfigAttr], dict[str, str], dict[str, str], dict[int, list[str]]]:
        return rules_loop.evaluate_rules_loop(
            self, attrs, hints, filled, hiding_rules, rec_rules, con_rules,
            bml_eval, filled_source, filled_multi, dropped_multi, country,
            negated_vns, skip_always_ask, rule_conflict_order, display_order,
            workspace_id, catalog_prefix, product_anchor_hint, _dt_cache,
        )


    @staticmethod
    def _bml_prefetch_requests(
        filled: dict[str, str],
        attrs: list[ConfigAttr] | None = None,
        hiding: list[HidingRule] | None = None,
        rec: list[RecommendationRule] | None = None,
        con: list[ConstraintRule] | None = None,
    ) -> list[tuple[str, str, dict[str, str], int | None]]:
        return gov_sibling.bml_prefetch_requests(filled, attrs, hiding, rec, con)

    # ── Context sentence builder ────────────────────────

    def build_context_sentence(
        self,
        pending_attr: ConfigAttr,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        display_filled: dict[str, str],
        hiding_rules: list[HidingRule],
        rec_rules: list[RecommendationRule],
    ) -> str:
        return gov_sibling.build_context_sentence(
            self, pending_attr, attrs, filled, display_filled, hiding_rules, rec_rules,
        )

    # ── Auto-fill ───────────────────────────────────

    @staticmethod
    def rule_governed_ids(
        attrs: list[ConfigAttr],
        hiding_rules: list[HidingRule],
        rec_rules: list[RecommendationRule],
        con_rules: list[ConstraintRule],
    ) -> set[int]:
        return gov_sibling.rule_governed_ids(attrs, hiding_rules, rec_rules, con_rules)

    @staticmethod
    def product_label_noise_vns(
        attrs: list[ConfigAttr],
        hiding_rules: list[HidingRule],
        rec_rules: list[RecommendationRule],
        con_rules: list[ConstraintRule],
    ) -> set[str]:
        return gov_sibling.product_label_noise_vns(
            attrs, hiding_rules, rec_rules, con_rules,
        )

    @staticmethod
    def _normalized_label_stem(label: str) -> str:
        return gov_sibling.normalized_label_stem(label)

    # Explicit, disclosed exception to the generic label-stem detector
    # in `exclusive_sibling_family_exclusions` — see that function's
    # docstring (now in cpq/governance_and_sibling_exclusivity/sibling_
    # exclusions.py) for why this pair specifically cannot be found by
    # label similarity, and the live evidence establishing it belongs
    # here anyway. Catalog-specific by necessity (this concept has no
    # other derivable signal in the ingested data), NOT a general
    # mechanism — kept to this one pair, added only after direct
    # confirmation, not silently. Deliberately stays on the class: it
    # is the single disclosed exception table and is read back through
    # the `engine` instance by the extracted detector.
    _KNOWN_SIBLING_PAIRS: tuple[tuple[str, str], ...] = (
        ("wirelessCarrier_astro", "carrierSelectionMultiSelect_astro"),
    )

    def exclusive_sibling_family_exclusions(
        self,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]],
        filled_source: dict[str, str],
        all_attrs: list[ConfigAttr] | None = None,
        catalog_confirmed_vns: frozenset[str] | None = None,
        product_name: str = "",
        workspace_id: int | None = None,
        catalog_prefix: str = "",
    ) -> tuple[set[str], list[ConfigAttr]]:
        return gov_sibling.exclusive_sibling_family_exclusions(
            self, attrs, filled, filled_multi, filled_source, all_attrs,
            catalog_confirmed_vns, product_name, workspace_id, catalog_prefix,
        )

    def enforce_exclusive_sibling_families(
        self,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]],
        filled_source: dict[str, str],
        display_filled: dict[str, str],
        pending: list[ConfigAttr],
        all_attrs: list[ConfigAttr] | None = None,
        catalog_confirmed_vns: frozenset[str] | None = None,
        product_name: str = "",
        workspace_id: int | None = None,
        catalog_prefix: str = "",
    ) -> list[ConfigAttr]:
        return gov_sibling.enforce_exclusive_sibling_families(
            self, attrs, filled, filled_multi, filled_source, display_filled,
            pending, all_attrs, catalog_confirmed_vns, product_name,
            workspace_id, catalog_prefix,
        )

    @staticmethod
    def governed_target_ids(
        attrs: list[ConfigAttr],
        hiding_rules: list[HidingRule],
        rec_rules: list[RecommendationRule],
        con_rules: list[ConstraintRule],
    ) -> set[int]:
        return gov_sibling.governed_target_ids(
            attrs, hiding_rules, rec_rules, con_rules,
        )

    @staticmethod
    def is_recognized_country(value: str) -> str | None:
        return gov_sibling.is_recognized_country(value)

    @staticmethod
    def derive_region(country: str, attr: ConfigAttr) -> tuple[str, str] | None:
        return gov_sibling.derive_region(country, attr)

    @staticmethod
    def _apply_series_mapping_exclusions(
        attrs: list[ConfigAttr], constrained_opts: dict[int, list[str]],
        filled: dict[str, str], workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> None:
        data_table_bridge._apply_series_mapping_exclusions(
            attrs, constrained_opts, filled, workspace_id, catalog_prefix, cache,
        )

    @staticmethod
    def _suppress_ungoverned_attrs(
        attrs: list[ConfigAttr], filled: dict[str, str],
        workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> tuple[list[ConfigAttr], set[str]]:
        return data_table_bridge._suppress_ungoverned_attrs(
            attrs, filled, workspace_id, catalog_prefix, cache,
        )

    @staticmethod
    def _compute_hidden_master_string(
        filled: dict[str, str],
        workspace_id: int | None,
        catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
        attrs: list[ConfigAttr] | None = None,
        var_name: str = "hiddenMasterStringForAstroPortable_astro",
        separator_var_name: str = "hidddenRecordSeparator_allFamilly",
    ) -> str | None:
        return data_table_bridge._compute_hidden_master_string(
            filled, workspace_id, catalog_prefix, cache, attrs, var_name, separator_var_name,
        )

    @staticmethod
    def _invalidate_inconsistent_paired_values(
        filled: dict[str, str], sources: dict[str, str],
        workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> set[str]:
        return data_table_bridge._invalidate_inconsistent_paired_values(
            filled, sources, workspace_id, catalog_prefix, cache,
        )

    @staticmethod
    def find_confirmed_data_table_conflicts(
        filled: dict[str, str], sources: dict[str, str],
        workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> set[tuple[str, str]]:
        return data_table_bridge.find_confirmed_data_table_conflicts(
            filled, sources, workspace_id, catalog_prefix, cache,
        )

    @staticmethod
    def _resolve_via_data_tables(
        vn: str, filled: dict[str, str], valid_opts: list[MenuOption],
        workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> MenuOption | None:
        return data_table_bridge._resolve_via_data_tables(
            vn, filled, valid_opts, workspace_id, catalog_prefix, cache,
        )

    @staticmethod
    def _resolve_narrowed_legal_values(
        vn: str, filled: dict[str, str], workspace_id: int, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> list[str] | None:
        return data_table_bridge._resolve_narrowed_legal_values(
            vn, filled, workspace_id, catalog_prefix, cache,
        )

    def auto_fill(
        self,
        attrs: list[ConfigAttr],
        hints: dict[str, str],
        already_filled: dict[str, str] | None = None,
        constrained_opts: dict[int, list[str]] | None = None,
        filled_source: dict[str, str] | None = None,
        governed_ids: set[int] | None = None,
        already_filled_multi: dict[str, list[str]] | None = None,
        dropped_multi: dict[str, list[str]] | None = None,
        rule_governed_ids: set[int] | None = None,
        country: str | None = None,
        rec_rules: list[RecommendationRule] | None = None,
        negated_vns: set[str] | None = None,
        skip_always_ask: set[str] | None = None,
        bml_eval: BmlEvaluator | None = None,
        validation_rules: list["ValidationRule"] | None = None,
        display_order: dict[str, int] | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        _dt_cache: dict[tuple[int, str], tuple] | None = None,
        hiding_rules: list["HidingRule"] | None = None,
        _default_fill_signatures: dict[str, tuple] | None = None,
        _signature_exclude_vns: frozenset[str] | None = None,
        grid_declined_vns: frozenset[str] | None = None,
        product_anchor_hint: str | None = None,
    ) -> tuple[dict[str, str], dict[str, str], list[ConfigAttr]]:
        return auto_fill_run.run_auto_fill(
            self, attrs, hints, already_filled, constrained_opts, filled_source,
            governed_ids, already_filled_multi, dropped_multi, rule_governed_ids,
            country, rec_rules, negated_vns, skip_always_ask, bml_eval,
            validation_rules, display_order, workspace_id, catalog_prefix,
            _dt_cache, hiding_rules, _default_fill_signatures, _signature_exclude_vns,
            grid_declined_vns, product_anchor_hint,
        )

    @staticmethod
    def _resolve_pointer_defaults(
        attrs: list["ConfigAttr"],
        filled: dict[str, str],
        display_filled: dict[str, str],
        sources: dict[str, str],
    ) -> None:
        return auto_fill_postpass.resolve_pointer_defaults(attrs, filled, display_filled, sources)

    @staticmethod
    def _cascade_fill_pending(
        pending: list["ConfigAttr"],
        filled: dict[str, str],
        display_filled: dict[str, str],
        sources: dict[str, str],
    ) -> list["ConfigAttr"]:
        return auto_fill_postpass.cascade_fill_pending(pending, filled, display_filled, sources)

    @staticmethod
    def _is_hardware_version_attr(attr: "ConfigAttr") -> bool:
        return auto_fill_hw_order.is_hardware_version_attr(attr)

    @staticmethod
    def _is_product_line_selector(attr: "ConfigAttr") -> bool:
        return auto_fill_hw_order.is_product_line_selector(attr)

    @staticmethod
    def _is_svx_mounting_array_quantity_attr(attr: "ConfigAttr") -> bool:
        return auto_fill_hw_order.is_svx_mounting_array_quantity_attr(attr)

    def _order_pending_hardware_before_product(
        self,
        pending: list["ConfigAttr"],
        filled: dict[str, str],
        attrs: list["ConfigAttr"],
        display_order: dict[str, int] | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
        product_anchor_hint: str | None = None,
    ) -> list["ConfigAttr"]:
        return auto_fill_hw_order.order_pending_hardware_before_product(
            self, pending, filled, attrs, display_order,
            workspace_id=workspace_id, catalog_prefix=catalog_prefix,
            cache=cache, product_anchor_hint=product_anchor_hint,
        )

    @staticmethod
    def _hardware_version_confirmed_not_applicable(
        hint_text: str | None, workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> bool:
        """True ONLY when a specific device can be confidently resolved
        from `hint_text` (the customer's own original wording, e.g. "I
        want APX 3000 for United States" — see CpqSession.product_
        anchor_question) AND real attrSequence data confirms Hardware
        Version is never governed for ANY of its real CPQModel
        candidates (docs/Hardware_Version_APX3000_Product_Anchoring_
        Issue.md v2.2's merged recommendation).

        Every other outcome — no hint, no workspace_id, no confident
        single product match (resolve_product_cpq_models_from_hint's own
        "never guess" contract — see its docstring), or Hardware Version
        IS governed for at least one resolved candidate — returns False,
        preserving today's exact behavior (still treated as a mandatory
        anchor). Deliberately one-sided: can only ever make Hardware
        Version LESS forced, never more, and only when the underlying
        data gives a real, unambiguous answer.

        Kept as real logic here (not delegated to auto_fill_hw_order,
        despite that module holding the rest of the hardware-ordering
        code) so this module's own `dt_resolve_product_cpq_models_from_
        hint`/`dt_attr_ever_governed_for_cpq_model` names are what
        actually execute — tests patch those two names by dotted path
        (`aryx.cpq.engine.<name>`), and a delegate elsewhere would bind
        its own separate copies at import time, silently missing the
        patch (same re-export-hub pitfall documented elsewhere in this
        codebase).
        """
        # TODO(hardcoding): the "hWVersion_astro" literal is kept (not
        # derived from the attr) so flag-off results stay provably identical.
        return CpqEngine._named_attr_confirmed_not_applicable(
            "hWVersion_astro", hint_text, workspace_id, catalog_prefix, cache,
        )

    @staticmethod
    def _named_attr_confirmed_not_applicable(
        vn: str, hint_text: str | None, workspace_id: int | None,
        catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> bool:
        """`_hardware_version_confirmed_not_applicable`'s one-sided "real
        Data Table evidence, never a guess" contract for any variable name
        `vn` (port of dev-rv-msi #365). True ONLY when `hint_text` resolves
        to a confident set of CPQModel candidates and NONE of them is ever
        seen governing `vn`. Callers decide whether `vn` is safe to check
        this way (structural anchors must be exempted by the caller).
        """
        if not hint_text or workspace_id is None:
            return False
        candidates = dt_resolve_product_cpq_models_from_hint(
            hint_text, workspace_id, catalog_prefix, cache,
        )
        if not candidates:
            return False
        return not any(
            dt_attr_ever_governed_for_cpq_model(
                cm, vn, workspace_id, catalog_prefix, cache,
            )
            for cm in candidates
        )

    @staticmethod
    def _attrs_confirmed_not_applicable_for_hint(
        pending: list["ConfigAttr"], hint_text: str | None,
        workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> list["ConfigAttr"]:
        """Drop pending attrs never governed for the device resolved from
        `hint_text` (port of dev-rv-msi #362). See
        aryx.cpq.auto_fill.auto_fill_pending_prune."""
        from aryx.cpq.auto_fill import auto_fill_pending_prune
        return auto_fill_pending_prune.attrs_confirmed_not_applicable_for_hint(
            pending, hint_text, workspace_id, catalog_prefix, cache,
        )

    # ── Step 6 / 7 / 8 detection helpers ─────────────────────────────────────

    # §6.1/§6.2 explicit-request detectors — shared "did the client ask for a
    # different presentation" pattern. Biased toward returning None (the rich
    # default: verbose narrative, one question at a time) on ambiguity — a
    # false negative just stays verbose; a false positive leaks JSON or a
    # batch dump the client didn't ask for.
    _JSON_REQUEST_RE = re.compile(
        r"\b(show|give|see|what'?s)\b[^.?!]{0,30}\b(json|payload|bom)\b|"
        r"\bjson\b[^.?!]{0,20}\b(so\s+far|now|please)\b",
        re.IGNORECASE,
    )
    _BATCH_REQUEST_RE = re.compile(
        r"\bwhat\s+else\b|\bwhat'?s\s+left\b|"
        r"\bshow\s+(me\s+)?(all|everything)\b|"
        r"\blist\s+(all|the)\s+(remaining|pending)\b|"
        r"\bwhat\s+do\s+you\s+(still\s+)?need\b",
        re.IGNORECASE,
    )

    # The 28 methods below were originally defined directly on this class;
    # the real implementations now live in `aryx.cpq.turn_intent` (Phase 4
    # step 2, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). 7 of them --
    # detect_attr_activation, detect_attr_clear, detect_bulk_quantity_change,
    # _change_request_matches, find_cascade_dependents, build_review_prompt,
    # next_question_prompt -- genuinely need to call back into other
    # CpqEngine instance methods (apply_hiding_rules, apply_constraint_rules,
    # apply_recommendation_rules, resolve_array_grid_links, extract_hints,
    # _attr_index, _is_html_value), so they stay plain instance methods that
    # pass `self` through as the module function's leading `engine` argument.
    # The other 21 need nothing from the instance and are `@staticmethod`
    # wrappers, same convention as the data_table_bridge cluster above. Every
    # existing call site (`self.foo(...)`, `CpqEngine.foo(...)`,
    # `CpqEngine().foo(...)`, and every `mock.patch("aryx.cpq.engine.foo")` in
    # the test suite) keeps working unchanged.
    #
    # These 14 class-level constants moved the same way — kept as class
    # attributes here (not just inside turn_intent) since external code
    # (e.g. ask_api.py's `_cpq_engine._CHANGE_VERB_RE`) accesses them as
    # attributes of the CpqEngine instance/class, not via a module import.
    _APPROVAL_RE = turn_intent._APPROVAL_RE
    _QA_INTENT_RE = turn_intent._QA_INTENT_RE
    _CHANGE_VERB_RE = turn_intent._CHANGE_VERB_RE
    _ARROW_RE = turn_intent._ARROW_RE
    _REMOVE_VERB_RE = turn_intent._REMOVE_VERB_RE
    _ADD_VERB_RE = turn_intent._ADD_VERB_RE
    _CLEAR_VERB_RE = turn_intent._CLEAR_VERB_RE
    _BULK_QTY_RE = turn_intent._BULK_QTY_RE
    _DECLINE_RE = turn_intent._DECLINE_RE
    _SHOW_SUMMARY_RE = turn_intent._SHOW_SUMMARY_RE
    _MAX_MULTI_CHANGE_REQUESTS = turn_intent._MAX_MULTI_CHANGE_REQUESTS
    _GENERIC_CLAUSE_STOPWORDS = turn_intent._GENERIC_CLAUSE_STOPWORDS
    _OPTIONS_KEYWORDS = turn_intent._OPTIONS_KEYWORDS
    _ALLOWED_CHARS_RE = turn_intent._ALLOWED_CHARS_RE

    @staticmethod
    def detect_response_mode_request(question: str) -> str | None:
        return turn_intent.detect_response_mode_request(question)

    @staticmethod
    def detect_multi_select_removal(
        question: str,
        attrs: list[ConfigAttr],
        filled_multi: dict[str, list[str]],
    ) -> 'tuple[ConfigAttr, list[str]] | None':
        return turn_intent.detect_multi_select_removal(question, attrs, filled_multi)

    def detect_attr_activation(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]],
        hiding_rules: list[HidingRule],
        workspace_id: int,
        catalog_prefix: str,
        bml_eval: BmlEvaluator | None = None,
    ) -> ConfigAttr | None:
        return turn_intent.detect_attr_activation(
            self,
            question,
            attrs,
            filled,
            filled_multi,
            hiding_rules,
            workspace_id,
            catalog_prefix,
            bml_eval,
        )

    def detect_attr_clear(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        rec_rules: list[RecommendationRule],
        con_rules: list[ConstraintRule],
        bml_eval: BmlEvaluator | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
    ) -> ConfigAttr | None:
        return turn_intent.detect_attr_clear(
            self,
            question,
            attrs,
            filled,
            rec_rules,
            con_rules,
            bml_eval,
            workspace_id,
            catalog_prefix,
        )

    def detect_bulk_quantity_change(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled_multi: dict[str, list[str]],
    ) -> 'tuple[str, list[str], str] | None':
        return turn_intent.detect_bulk_quantity_change(self, question, attrs, filled_multi)

    @staticmethod
    def detect_approval(question: str) -> bool:
        return turn_intent.detect_approval(question)

    @staticmethod
    def detect_decline(question: str) -> bool:
        return turn_intent.detect_decline(question)

    @staticmethod
    def detect_show_summary_request(question: str) -> bool:
        return turn_intent.detect_show_summary_request(question)

    @staticmethod
    def detect_qa_question(
        question: str,
        pending_attr: 'ConfigAttr | None' = None,
        strict: bool = False,
    ) -> bool:
        return turn_intent.detect_qa_question(question, pending_attr, strict)

    def detect_change_request(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]] | None = None,
    ) -> 'tuple[ConfigAttr, str] | None':
        return turn_intent.detect_change_request(self, question, attrs, filled, filled_multi)

    @staticmethod
    def detect_all_change_targets_without_value(
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        *,
        filled_multi: dict[str, list[str]] | None = None,
        exclude_vns: set[str] | None = None,
        cap: int = 10,
    ) -> list[ConfigAttr]:
        return turn_intent.detect_all_change_targets_without_value(
            question,
            attrs,
            filled,
            filled_multi=filled_multi,
            exclude_vns=exclude_vns,
            cap=cap,
        )

    @staticmethod
    def detect_change_target_without_value(
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
    ) -> ConfigAttr | None:
        return turn_intent.detect_change_target_without_value(question, attrs, filled)

    def detect_change_requests_multi(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]] | None = None,
    ) -> list[tuple[ConfigAttr, str]]:
        return turn_intent.detect_change_requests_multi(self, question, attrs, filled, filled_multi)

    @staticmethod
    def detect_unmatched_change_targets(
        question: str,
        attrs: list[ConfigAttr],
        matched_vns: 'set[str]',
    ) -> list[str]:
        return turn_intent.detect_unmatched_change_targets(question, attrs, matched_vns)

    def _change_request_matches(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]] | None = None,
    ) -> Iterator[tuple[ConfigAttr, str]]:
        return turn_intent._change_request_matches(self, question, attrs, filled, filled_multi)

    def find_cascade_dependents(
        self,
        changed_attr: 'ConfigAttr',
        all_attrs: list[ConfigAttr],
        hiding_rules: list[HidingRule],
        rec_rules: list[RecommendationRule],
        con_rules: list[ConstraintRule],
    ) -> list[int]:
        return turn_intent.find_cascade_dependents(
            self,
            changed_attr,
            all_attrs,
            hiding_rules,
            rec_rules,
            con_rules,
        )

    def build_review_prompt(
        self,
        product_name: str,
        attrs: list[ConfigAttr],
        display_filled: dict[str, str],
    ) -> str:
        return turn_intent.build_review_prompt(self, product_name, attrs, display_filled)

    @staticmethod
    def detect_label_collision(question: str, attrs: list[ConfigAttr]) -> list[ConfigAttr] | None:
        return turn_intent.detect_label_collision(question, attrs)

    @staticmethod
    def detect_change_request_collision(
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]] | None = None,
    ) -> list[ConfigAttr] | None:
        return turn_intent.detect_change_request_collision(question, attrs, filled, filled_multi)

    @staticmethod
    def count_turn_intents(
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]] | None = None,
    ) -> list[str]:
        return turn_intent.count_turn_intents(question, attrs, filled, filled_multi)

    @staticmethod
    def detect_attr_query(question: str, attrs: list[ConfigAttr]) -> ConfigAttr | None:
        return turn_intent.detect_attr_query(question, attrs)

    @staticmethod
    def _describe_char_allowlist(script: str | None) -> str | None:
        return turn_intent._describe_char_allowlist(script)

    @staticmethod
    def describe_free_text_constraint(
        attr: ConfigAttr,
        validation_rules: list['ValidationRule'] | None,
    ) -> str | None:
        return turn_intent.describe_free_text_constraint(attr, validation_rules)

    @staticmethod
    def should_ask_free_text_attr(
        attr: ConfigAttr,
        validation_rules: list['ValidationRule'] | None,
        bml_eval: 'BmlEvaluator | None',
    ) -> bool:
        return turn_intent.should_ask_free_text_attr(attr, validation_rules, bml_eval)

    @staticmethod
    def disambiguated_label(attr: ConfigAttr, attrs: list[ConfigAttr]) -> str:
        return turn_intent.disambiguated_label(attr, attrs)

    def next_question_prompt(
        self,
        attr: ConfigAttr,
        context_sentence: str = "",
        constrained_item_values: list[str] | None = None,
        validation_rules: list['ValidationRule'] | None = None,
        attrs: list[ConfigAttr] | None = None,
        already_selected: 'list[str] | set[str] | None' = None,
    ) -> str:
        return turn_intent.next_question_prompt(
            self,
            attr,
            context_sentence,
            constrained_item_values,
            validation_rules,
            attrs,
            already_selected,
        )

    @staticmethod
    def apply_answer(
        attr: ConfigAttr,
        user_answer: str,
        constrained_item_values: list[str] | None = None,
    ) -> tuple[str, str] | None:
        return turn_intent.apply_answer(attr, user_answer, constrained_item_values)

    @staticmethod
    def apply_multi_answer(
        attr: ConfigAttr,
        user_answer: str,
        constrained_item_values: list[str] | None = None,
    ) -> list[tuple[str, str]]:
        return turn_intent.apply_multi_answer(attr, user_answer, constrained_item_values)

    # ── Payload builder ───────────────────────────────────────────────────────

    def _is_html_value(self, val: str) -> bool:
        """True when the value is an HTML/template blob (not a real selection)."""
        s = val.strip()
        return s.startswith("<") and ">" in s

    # Provenance classes whose values are kept even when they collide with a
    # none-sentinel spelling: the user (or a value validated against the menu
    # of a sibling attr) explicitly chose them. Region="NA" (North America)
    # and quantity "0" are legitimate API codes, not empty selections.
    _CONFIRMED_SOURCES: frozenset[str] = frozenset({"user", "hint", "cascade"})

    def build_standalone_payload(
        self,
        reader: Any,
        workspace_id: int,
        product_hint: str,
        filled: dict[str, str],
        filled_multi: dict[str, list[str]] | None = None,
        hints: dict[str, str] | None = None,
        country: str | None = None,
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        return payload_building.build_standalone_payload(
            self, reader, workspace_id, product_hint, filled, filled_multi, hints, country)

    # docs/CPQ_ConfigData_Payload_Mandatory_Fix_Scope_2026_08_19.md -- for
    # `build_payload`'s config_data scoping specifically (NOT beautify/
    # summary, which keep the literal source=="user" check). Live-
    # confirmed gap: Ultimate Destination Country, Wireless Carrier,
    # Frequency Band Msl, and "Is provisioning required in cloud?" are all
    # genuine, pure-user-input Mandatory fields with no catalog default,
    # yet were missing from config_data because their real filled_source
    # is "hint" (extracted directly from a compound opening sentence, e.g.
    # "configure APX NEXT for USA") or "cascade"/"cascade-dependent" (re-
    # derived as a side effect of a Hardware Version/Product change) --
    # never the literal string "user" the old bare fallback required.
    # `_SUMMARY_ACTIVE_SOURCES` (below) already treats these as genuine
    # per-turn decisions for the summary's own purpose -- this is the same
    # set, MINUS "rule": a fired-rule value (e.g. Package Type resolving
    # via the ICE-Kit RecommendationRule) is exactly the "cosmetic auto-
    # fill"/"blind-picked default" scope_required_and_edited's own
    # docstring says config_data must keep excluding, even though a fired
    # rule condition is legitimately "active" for the summary's different
    # purpose. Deliberately NOT the same as Tier C (AttrSequence-Required,
    # designed for beautify's Mandatory-section split) -- Tier C would
    # promote genuinely never-edited catalog defaults (Software Release,
    # Solution Type, Duration, Battery Type, ...) into config_data, which
    # is exactly the "blind-picked default" class this payload must
    # exclude; config_data only wants structurally-forced or genuinely
    # decided values, not everything AttrSequence flags Required.
    _CONFIG_DATA_ACTIVE_SOURCES: frozenset[str] = frozenset({
        "user", "hint", "cascade", "cascade-dependent", "country_derived", "product_anchor",
    })

    # 2026-08-19 (docs/CPQ_Beautify_Mandatory_Section_Miscategorization_
    # 2026_08_19.md): every one of these 10 variable names is confirmed,
    # live, against the real APX NEXT UI to appear ONLY under "Recommended
    # Configuration" -- never under "Mandatory User Input" -- even though
    # AttrSequence flags most of them optionOrReqFlag == "R" ("must end up
    # with a value" is not the same claim as "the customer is asked").
    # Excluded from `mandatory_tier_c_vns` for exactly that reason. As with
    # ask_api._NEVER_ASK_RECOMMENDED_ONLY_VNS (the conversational-ask-flow
    # counterpart of this same distinction), there is no
    # BmConfigLayoutAttrAssoc row to derive this from in this catalog
    # (zero rows exist) -- membership is individually verified, not
    # generically derived.
    _RECOMMENDED_CONFIG_ONLY_VNS: frozenset[str] = frozenset({
        "systemEnhancementFeatureType_astro",  # Feature Type
        "serviceTypeAdditionalDMSCoverage_astro",  # Service Type
        "dmsDuration_astro", "dMSDurationYears_astro",  # DMS Duration
        "antennasType_astro",  # Antenna Type
        "beltClipType_astro",  # Carry Type
        "advancedSystemKeyHardwareKey_astro",  # System Key
        "deviceManagementTraining_astro",  # Device Management Training
        "trainTheTrainerTraining_astro",  # Train the Trainer Training
        "packingPackageType_astro",  # Package Type
        "documentationTestResultsRatedAudioPrintoutLabel_astro",  # Test Results/Rated Audio Printout Label
    })

    def mandatory_tier_c_vns(
        self, filled: dict[str, str] | None, workspace_id: int | None,
        catalog_prefix: str = "", cache: dict[tuple[int, str], tuple] | None = None,
    ) -> frozenset[str]:
        return payload_building.mandatory_tier_c_vns(
            self, filled, workspace_id, catalog_prefix, cache)

    def _data_table_resolved_anchor_vns(
        self, filled: dict[str, str] | None, attrs: list["ConfigAttr"] | None,
        workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None, country: str = "",
    ) -> frozenset[str]:
        return payload_building._data_table_resolved_anchor_vns(
            self, filled, attrs, workspace_id, catalog_prefix, cache, country)

    def _is_mandatory_input_attr(
        self, vn: str, attr: "ConfigAttr | None", source: str | None,
        active_sources: frozenset[str] | None = None,
        required_vns: frozenset[str] | None = None,
        exclude_anchor_vns: frozenset[str] | None = None,
        gate_attrseq_confirmed_to_active_source: bool = False,
        rule_forced_active_vns: frozenset[str] | None = None,
        data_table_forced_vns: frozenset[str] | None = None,
        hint_text: str | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        _dt_cache: dict[tuple[int, str], tuple] | None = None,
    ) -> bool:
        return mandatory_input.is_mandatory_input_attr(
            self, vn, attr, source, active_sources, required_vns,
            exclude_anchor_vns, gate_attrseq_confirmed_to_active_source,
            rule_forced_active_vns, data_table_forced_vns,
            hint_text=hint_text, workspace_id=workspace_id,
            catalog_prefix=catalog_prefix, _dt_cache=_dt_cache,
        )


    def build_payload(
        self,
        filled: dict[str, str],
        filled_source: dict[str, str] | None = None,
        filled_multi: dict[str, list[str]] | None = None,
        attrs: list["ConfigAttr"] | None = None,
        hidden_vns: set[str] | None = None,
        rules: list[Any] | None = None,
        display_order: dict[str, int] | None = None,
        product_quantity: int | None = None,
        scope_required_and_edited: bool = False,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        product_anchor_hint: str | None = None,
        _dt_cache: dict[tuple[int, str], tuple] | None = None,
    ) -> dict[str, Any]:
        return payload_build.build_payload(
            self, filled, filled_source, filled_multi, attrs, hidden_vns, rules,
            display_order, product_quantity, scope_required_and_edited,
            workspace_id, catalog_prefix,
            product_anchor_hint=product_anchor_hint, _dt_cache=_dt_cache,
        )

    @staticmethod
    def _rule_condition_edges(
        attrs: list["ConfigAttr"],
        rules: list[Any],
    ) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[int, str]]:
        return rule_specificity_ranking._rule_condition_edges(attrs, rules)

    @staticmethod
    def _attribute_depth_ranks(
        attrs: list["ConfigAttr"],
        rules: list[Any],
    ) -> dict[str, int]:
        return rule_specificity_ranking._attribute_depth_ranks(attrs, rules)

    def rank_rules_by_specificity(
        self,
        attrs: list["ConfigAttr"],
        hiding_rules: list["HidingRule"],
        rec_rules: list["RecommendationRule"],
        con_rules: list["ConstraintRule"],
        display_order: dict[str, int] | None = None,
    ) -> tuple[list["HidingRule"], list["RecommendationRule"], list["ConstraintRule"]]:
        return rule_specificity_ranking.rank_rules_by_specificity(
            self, attrs, hiding_rules, rec_rules, con_rules, display_order)

    @staticmethod
    def _dependency_ordered_keys(
        keys: list[str],
        attr_by_vn: dict[str, "ConfigAttr"],
        rules: list[Any],
    ) -> list[str]:
        return rule_specificity_ranking._dependency_ordered_keys(
            keys, attr_by_vn, rules)

    # ── Summary renderer ──────────────────────────────────────────────────────

    @staticmethod
    def _is_noise_var(variable_name: str) -> bool:
        return summary_display_formatting._is_noise_var(variable_name)

    @staticmethod
    def _attr_hidden_from_submission(attr: "ConfigAttr") -> bool:
        return summary_display_formatting._attr_hidden_from_submission(attr)

    @staticmethod
    def _attr_is_transient_set_type(attr: "ConfigAttr") -> bool:
        return summary_display_formatting._attr_is_transient_set_type(attr)

    # Displayed values that carry no information on their own — a line like
    # "Opt-Out? → false" or "Ruggedized Housing → Yes" restates a toggle, it
    # doesn't communicate a configuration choice.
    _BOOLEAN_DISPLAY_VALUES: frozenset[str] = frozenset({"yes", "no", "true", "false"})

    # Duration-shaped values ("1 Year", "3 Years", "10 Years (Federal ...)")
    # — subscription/service term lines the summary should not list.
    _YEAR_VALUE_RE: re.Pattern[str] = re.compile(r"\byears?\b", re.IGNORECASE)

    # filled_source values that represent a genuine per-turn decision — a
    # rule whose condition actually held (source="rule"/"country_derived"),
    # or the user's own answer/hint/cascade-driven change — as opposed to a
    # bland "default"/"optional"/"auto" fill nobody actually reasoned about
    # this turn. Used to narrow "Associated Options" to attrs that were
    # genuinely decided, not merely targeted by some rule somewhere in the
    # catalog (see _filled_summary_triples).
    #
    # "product_anchor" (ask_api.py) — productSelectionProduct_all seeded
    # from a CONFIRMED product switch (the user explicitly answered "yes")
    # — a genuine decision, just tagged with its own distinct source string
    # rather than "user". Confirmed live: omitting it meant "Product" was
    # missing from the summary right after a switch, only reappearing once
    # a LATER cascade happened to re-tag it "rule" (e.g. a Hardware
    # Version change) — the exact turn where the product was actually
    # decided showed the least information about it.
    _SUMMARY_ACTIVE_SOURCES: frozenset[str] = frozenset({
        "rule", "country_derived", "user", "hint", "cascade", "cascade-dependent",
        "product_anchor",
    })

    def _is_summary_excluded(
        self, variable_name: str, display_label: str, value: str,
        attr: "ConfigAttr | None", source: str | None = None,
        is_mandatory: bool = False,
    ) -> bool:
        return summary_display_formatting._is_summary_excluded(
            self, variable_name, display_label, value, attr, source=source,
            is_mandatory=is_mandatory)

    def _filled_summary_triples(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
        sources: dict[str, str] | None = None,
        display_order: dict[str, int] | None = None,
        required_vns: frozenset[str] | None = None,
        product_anchor_hint: str | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        dt_cache: dict[tuple[int, str], tuple] | None = None,
    ) -> list[tuple[str, str, str]]:
        return summary_display_formatting._filled_summary_triples(
            self, display_filled, attrs, rule_governed_ids, sources, display_order,
            required_vns=required_vns,
            product_anchor_hint=product_anchor_hint, workspace_id=workspace_id,
            catalog_prefix=catalog_prefix, dt_cache=dt_cache)

    def filled_summary_pairs(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
        sources: dict[str, str] | None = None,
        display_order: dict[str, int] | None = None,
        required_vns: frozenset[str] | None = None,
        product_anchor_hint: str | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        dt_cache: dict[tuple[int, str], tuple] | None = None,
    ) -> list[tuple[str, str]]:
        return summary_display_formatting.filled_summary_pairs(
            self, display_filled, attrs, rule_governed_ids, sources, display_order,
            required_vns=required_vns,
            product_anchor_hint=product_anchor_hint, workspace_id=workspace_id,
            catalog_prefix=catalog_prefix, dt_cache=dt_cache)

    @staticmethod
    def _summary_category(variable_name: str) -> str:
        return summary_display_formatting._summary_category(variable_name)

    _BEAUTIFY_MANDATORY_SECTION = "Mandatory User Input"
    _BEAUTIFY_SYSTEM_SECTION = "System-Configured / Recommended"

    def _beautify_sectioned_rows(
        self,
        product_name: str,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None,
        filled_source: dict[str, str] | None,
        required_vns: frozenset[str] | None = None,
        product_anchor_hint: str | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        dt_cache: dict[tuple[int, str], tuple] | None = None,
    ) -> list[tuple[str, str, str]]:
        return summary_display_formatting._beautify_sectioned_rows(
            self, product_name, display_filled, attrs, filled_source,
            required_vns=required_vns,
            product_anchor_hint=product_anchor_hint, workspace_id=workspace_id,
            catalog_prefix=catalog_prefix, dt_cache=dt_cache)

    def beautify_text(
        self,
        product_name: str,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        filled_source: dict[str, str] | None = None,
        required_vns: frozenset[str] | None = None,
        product_anchor_hint: str | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        dt_cache: dict[tuple[int, str], tuple] | None = None,
    ) -> str:
        return summary_display_formatting.beautify_text(
            self, product_name, display_filled, attrs, filled_source,
            required_vns=required_vns,
            product_anchor_hint=product_anchor_hint, workspace_id=workspace_id,
            catalog_prefix=catalog_prefix, dt_cache=dt_cache)

    def beautify_rows(
        self,
        product_name: str,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        filled_source: dict[str, str] | None = None,
        required_vns: frozenset[str] | None = None,
        product_anchor_hint: str | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        dt_cache: dict[tuple[int, str], tuple] | None = None,
    ) -> list[dict[str, str]]:
        return summary_display_formatting.beautify_rows(
            self, product_name, display_filled, attrs, filled_source,
            required_vns=required_vns,
            product_anchor_hint=product_anchor_hint, workspace_id=workspace_id,
            catalog_prefix=catalog_prefix, dt_cache=dt_cache)

    def render_filled_summary(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
        sources: dict[str, str] | None = None,
        product_quantity: int | None = None,
        required_vns: frozenset[str] | None = None,
        product_anchor_hint: str | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        dt_cache: dict[tuple[int, str], tuple] | None = None,
    ) -> str:
        return summary_display_formatting.render_filled_summary(
            self, display_filled, attrs, rule_governed_ids, sources,
            product_quantity=product_quantity, required_vns=required_vns,
            product_anchor_hint=product_anchor_hint, workspace_id=workspace_id,
            catalog_prefix=catalog_prefix, dt_cache=dt_cache)

    def categorized_summary_groups(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
        sources: dict[str, str] | None = None,
        display_order: dict[str, int] | None = None,
        product_quantity: int | None = None,
        required_vns: frozenset[str] | None = None,
        product_anchor_hint: str | None = None,
        workspace_id: int | None = None,
        catalog_prefix: str = "",
        dt_cache: dict[tuple[int, str], tuple] | None = None,
    ) -> list[tuple[str, list[tuple[str, str]]]]:
        return summary_display_formatting.categorized_summary_groups(
            self, display_filled, attrs, rule_governed_ids, sources, display_order,
            product_quantity=product_quantity, required_vns=required_vns,
            product_anchor_hint=product_anchor_hint, workspace_id=workspace_id,
            catalog_prefix=catalog_prefix, dt_cache=dt_cache)
