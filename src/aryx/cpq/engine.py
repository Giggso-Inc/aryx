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
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from aryx.config import get_settings
from aryx.cpq import data_table_bridge
from aryx.cpq.bml import (
    BmlEvaluator, evaluate_declarative_conditions, extract_literal_comparisons,
    _operator_hit,
)
from aryx.cpq.data_table_resolver import resolve_whitelist_values as dt_resolve_whitelist_values
from aryx.cpq.data_table_resolver import resolve_product_cpq_model_family as dt_resolve_product_cpq_model_family
from aryx.cpq.data_table_resolver import resolve_product_cpq_models_from_rows as dt_resolve_product_cpq_models_from_rows
from aryx.cpq.data_table_resolver import resolve_region_allow_value as dt_resolve_region_allow_value
from aryx.cpq.data_table_resolver import resolve_invalid_product_variant as dt_resolve_invalid_product_variant
from aryx.cpq.data_table_resolver import discover_cpq_models_for_base_model as dt_discover_cpq_models_for_base_model
from aryx.cpq.data_table_resolver import governed_attr_names_for_base_model as dt_governed_attr_names_for_base_model
from aryx.cpq.data_table_resolver import governed_required_attr_names_for_base_model as dt_governed_required_attr_names_for_base_model
from aryx.cpq.data_table_resolver import find_inconsistent_filled_pairs as dt_find_inconsistent_filled_pairs
from aryx.cpq.data_table_resolver import (
    find_inconsistent_filled_pairs_detailed as dt_find_inconsistent_filled_pairs_detailed,
)
from aryx.cpq.data_table_resolver import attr_ever_governed_for_cpq_model as dt_attr_ever_governed_for_cpq_model
from aryx.cpq.data_table_cache import _invalidate_on_marker_change
from aryx.cpq.data_table_cache import _cache_write_if_marker_unchanged
from aryx.cpq.layout_source import LayoutFileSource, LocalDirLayoutFileSource
from aryx.cpq.logging_context import install_run_id_logging
from aryx.cpq.rdb import PostgresCpqRdb, get_cpq_rdb
from aryx.cpq import rule_trace
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
# Superseded by _COUNTRY_ALIAS_GROUPS below (2026-08-14) -- the old dict
# only supported the full-name -> abbreviation direction (a lookup keyed by
# the shorthand itself, e.g. `.get("usa", ())`, always returned empty since
# "usa" was never a dict KEY, only ever a value) and covered exactly 2
# countries. Confirmed live: a customer typing "USA" (not "US") to answer
# Ultimate Destination Country failed to match the real "US" option and
# fell through to the generic "251 options, too many to list" prompt with
# no matching branch and no log line anywhere in the process.
#
# _COUNTRY_ALIAS_GROUPS is data-generated (not hand-typed) from pycountry's
# ISO 3166-1 tables -- one frozenset per real country containing its
# common name, official name, alpha-2, and alpha-3 codes -- plus a small,
# explicit set of colloquial names ISO's own name fields don't carry but
# real customers type constantly (uk, uae, russia, vatican, ivory coast,
# swaziland, macedonia, micronesia, burma, turkey, palestine, brunei).
# pycountry itself is NOT a runtime dependency of this project (adding one
# needs its own CVE-checked approval, per this repo's library-approval
# rule) -- it was used ONLY offline, once, to generate this literal, the
# same way _COUNTRY_TO_REGION above is a hand-maintained static table, not
# a live library call. Regenerate by re-running the same generation script
# if pycountry's ISO data is ever updated upstream.
#
# Every group is symmetric by construction, closing the one-directional
# bug above for good: _country_alias_group("usa") and
# _country_alias_group("us") both return the identical frozenset
# containing "united states", "us", "usa", "united states of america".
_COUNTRY_ALIAS_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({'af', 'afg', 'afghanistan', 'islamic republic of afghanistan'}),
    frozenset({'al', 'alb', 'albania', 'republic of albania'}),
    frozenset({'algeria', 'dz', 'dza', "people's democratic republic of algeria"}),
    frozenset({'american samoa', 'as', 'asm'}),
    frozenset({'ad', 'and', 'andorra', 'principality of andorra'}),
    frozenset({'ago', 'angola', 'ao', 'republic of angola'}),
    frozenset({'ai', 'aia', 'anguilla'}),
    frozenset({'antarctica', 'aq', 'ata'}),
    frozenset({'ag', 'antigua and barbuda', 'atg'}),
    frozenset({'ar', 'arg', 'argentina', 'argentine republic'}),
    frozenset({'am', 'arm', 'armenia', 'republic of armenia'}),
    frozenset({'abw', 'aruba', 'aw'}),
    frozenset({'au', 'aus', 'australia'}),
    frozenset({'at', 'austria', 'aut', 'republic of austria'}),
    frozenset({'az', 'aze', 'azerbaijan', 'republic of azerbaijan'}),
    frozenset({'bahamas', 'bhs', 'bs', 'commonwealth of the bahamas'}),
    frozenset({'bahrain', 'bh', 'bhr', 'kingdom of bahrain'}),
    frozenset({'bangladesh', 'bd', 'bgd', "people's republic of bangladesh"}),
    frozenset({'barbados', 'bb', 'brb'}),
    frozenset({'belarus', 'blr', 'by', 'republic of belarus'}),
    frozenset({'be', 'bel', 'belgium', 'kingdom of belgium'}),
    frozenset({'belize', 'blz', 'bz'}),
    frozenset({'ben', 'benin', 'bj', 'republic of benin'}),
    frozenset({'bermuda', 'bm', 'bmu'}),
    frozenset({'bhutan', 'bt', 'btn', 'kingdom of bhutan'}),
    frozenset({'bo', 'bol', 'bolivia', 'bolivia, plurinational state of', 'plurinational state of bolivia'}),
    frozenset({'bes', 'bonaire, sint eustatius and saba', 'bq'}),
    frozenset({'ba', 'bih', 'bosnia and herzegovina', 'republic of bosnia and herzegovina'}),
    frozenset({'botswana', 'bw', 'bwa', 'republic of botswana'}),
    frozenset({'bouvet island', 'bv', 'bvt'}),
    frozenset({'br', 'bra', 'brazil', 'federative republic of brazil'}),
    frozenset({'british indian ocean territory', 'io', 'iot'}),
    frozenset({'bn', 'brn', 'brunei', 'brunei darussalam'}),
    frozenset({'bg', 'bgr', 'bulgaria', 'republic of bulgaria'}),
    frozenset({'bf', 'bfa', 'burkina faso'}),
    frozenset({'bdi', 'bi', 'burundi', 'republic of burundi'}),
    frozenset({'cabo verde', 'cpv', 'cv', 'republic of cabo verde'}),
    frozenset({'cambodia', 'kh', 'khm', 'kingdom of cambodia'}),
    frozenset({'cameroon', 'cm', 'cmr', 'republic of cameroon'}),
    frozenset({'ca', 'can', 'canada'}),
    frozenset({'cayman islands', 'cym', 'ky'}),
    frozenset({'caf', 'central african republic', 'cf'}),
    frozenset({'chad', 'republic of chad', 'tcd', 'td'}),
    frozenset({'chile', 'chl', 'cl', 'republic of chile'}),
    frozenset({'china', 'chn', 'cn', "people's republic of china"}),
    frozenset({'christmas island', 'cx', 'cxr'}),
    frozenset({'cc', 'cck', 'cocos (keeling) islands'}),
    frozenset({'co', 'col', 'colombia', 'republic of colombia'}),
    frozenset({'com', 'comoros', 'km', 'union of the comoros'}),
    frozenset({'cg', 'cog', 'congo', 'republic of the congo'}),
    frozenset({'cd', 'cod', 'congo, the democratic republic of the'}),
    frozenset({'ck', 'cok', 'cook islands'}),
    frozenset({'costa rica', 'cr', 'cri', 'republic of costa rica'}),
    frozenset({'croatia', 'hr', 'hrv', 'republic of croatia'}),
    frozenset({'cu', 'cub', 'cuba', 'republic of cuba'}),
    frozenset({'curaçao', 'cuw', 'cw'}),
    frozenset({'cy', 'cyp', 'cyprus', 'republic of cyprus'}),
    frozenset({'cz', 'cze', 'czech republic', 'czechia'}),
    frozenset({'ci', 'civ', "côte d'ivoire", 'ivory coast', "republic of côte d'ivoire"}),
    frozenset({'denmark', 'dk', 'dnk', 'kingdom of denmark'}),
    frozenset({'dj', 'dji', 'djibouti', 'republic of djibouti'}),
    frozenset({'commonwealth of dominica', 'dm', 'dma', 'dominica'}),
    frozenset({'do', 'dom', 'dominican republic'}),
    frozenset({'ec', 'ecu', 'ecuador', 'republic of ecuador'}),
    frozenset({'arab republic of egypt', 'eg', 'egy', 'egypt'}),
    frozenset({'el salvador', 'republic of el salvador', 'slv', 'sv'}),
    frozenset({'equatorial guinea', 'gnq', 'gq', 'republic of equatorial guinea'}),
    frozenset({'er', 'eri', 'eritrea', 'the state of eritrea'}),
    frozenset({'ee', 'est', 'estonia', 'republic of estonia'}),
    frozenset({'eswatini', 'kingdom of eswatini', 'swaziland', 'swz', 'sz'}),
    frozenset({'et', 'eth', 'ethiopia', 'federal democratic republic of ethiopia'}),
    frozenset({'falkland islands (malvinas)', 'fk', 'flk'}),
    frozenset({'faroe islands', 'fo', 'fro'}),
    frozenset({'fiji', 'fj', 'fji', 'republic of fiji'}),
    frozenset({'fi', 'fin', 'finland', 'republic of finland'}),
    frozenset({'fr', 'fra', 'france', 'french republic'}),
    frozenset({'french guiana', 'gf', 'guf'}),
    frozenset({'french polynesia', 'pf', 'pyf'}),
    frozenset({'atf', 'french southern territories', 'tf'}),
    frozenset({'ga', 'gab', 'gabon', 'gabonese republic'}),
    frozenset({'gambia', 'gm', 'gmb', 'republic of the gambia'}),
    frozenset({'ge', 'geo', 'georgia'}),
    frozenset({'de', 'deu', 'federal republic of germany', 'germany'}),
    frozenset({'gh', 'gha', 'ghana', 'republic of ghana'}),
    frozenset({'gi', 'gib', 'gibraltar'}),
    frozenset({'gr', 'grc', 'greece', 'hellenic republic'}),
    frozenset({'gl', 'greenland', 'grl'}),
    frozenset({'gd', 'grd', 'grenada'}),
    frozenset({'glp', 'gp', 'guadeloupe'}),
    frozenset({'gu', 'guam', 'gum'}),
    frozenset({'gt', 'gtm', 'guatemala', 'republic of guatemala'}),
    frozenset({'gg', 'ggy', 'guernsey'}),
    frozenset({'gin', 'gn', 'guinea', 'republic of guinea'}),
    frozenset({'gnb', 'guinea-bissau', 'gw', 'republic of guinea-bissau'}),
    frozenset({'guy', 'guyana', 'gy', 'republic of guyana'}),
    frozenset({'haiti', 'ht', 'hti', 'republic of haiti'}),
    frozenset({'heard island and mcdonald islands', 'hm', 'hmd'}),
    frozenset({'holy see (vatican city state)', 'va', 'vat', 'vatican', 'vatican city'}),
    frozenset({'hn', 'hnd', 'honduras', 'republic of honduras'}),
    frozenset({'hk', 'hkg', 'hong kong', 'hong kong special administrative region of china'}),
    frozenset({'hu', 'hun', 'hungary'}),
    frozenset({'iceland', 'is', 'isl', 'republic of iceland'}),
    frozenset({'in', 'ind', 'india', 'republic of india'}),
    frozenset({'id', 'idn', 'indonesia', 'republic of indonesia'}),
    frozenset({'ir', 'iran', 'iran, islamic republic of', 'irn', 'islamic republic of iran'}),
    frozenset({'iq', 'iraq', 'irq', 'republic of iraq'}),
    frozenset({'ie', 'ireland', 'irl'}),
    frozenset({'im', 'imn', 'isle of man'}),
    frozenset({'il', 'isr', 'israel', 'state of israel'}),
    frozenset({'it', 'ita', 'italian republic', 'italy'}),
    frozenset({'jam', 'jamaica', 'jm'}),
    frozenset({'japan', 'jp', 'jpn'}),
    frozenset({'je', 'jersey', 'jey'}),
    frozenset({'hashemite kingdom of jordan', 'jo', 'jor', 'jordan'}),
    frozenset({'kaz', 'kazakhstan', 'kz', 'republic of kazakhstan'}),
    frozenset({'ke', 'ken', 'kenya', 'republic of kenya'}),
    frozenset({'ki', 'kir', 'kiribati', 'republic of kiribati'}),
    frozenset({"democratic people's republic of korea", "korea, democratic people's republic of", 'kp', 'north korea', 'prk'}),
    frozenset({'kor', 'korea, republic of', 'kr', 'south korea'}),
    frozenset({'kuwait', 'kw', 'kwt', 'state of kuwait'}),
    frozenset({'kg', 'kgz', 'kyrgyz republic', 'kyrgyzstan'}),
    frozenset({'la', 'lao', "lao people's democratic republic", 'laos'}),
    frozenset({'latvia', 'lv', 'lva', 'republic of latvia'}),
    frozenset({'lb', 'lbn', 'lebanese republic', 'lebanon'}),
    frozenset({'kingdom of lesotho', 'lesotho', 'ls', 'lso'}),
    frozenset({'lbr', 'liberia', 'lr', 'republic of liberia'}),
    frozenset({'lby', 'libya', 'ly'}),
    frozenset({'li', 'lie', 'liechtenstein', 'principality of liechtenstein'}),
    frozenset({'lithuania', 'lt', 'ltu', 'republic of lithuania'}),
    frozenset({'grand duchy of luxembourg', 'lu', 'lux', 'luxembourg'}),
    frozenset({'mac', 'macao', 'macao special administrative region of china', 'mo'}),
    frozenset({'madagascar', 'mdg', 'mg', 'republic of madagascar'}),
    frozenset({'malawi', 'mw', 'mwi', 'republic of malawi'}),
    frozenset({'malaysia', 'my', 'mys'}),
    frozenset({'maldives', 'mdv', 'mv', 'republic of maldives'}),
    frozenset({'mali', 'ml', 'mli', 'republic of mali'}),
    frozenset({'malta', 'mlt', 'mt', 'republic of malta'}),
    frozenset({'marshall islands', 'mh', 'mhl', 'republic of the marshall islands'}),
    frozenset({'martinique', 'mq', 'mtq'}),
    frozenset({'islamic republic of mauritania', 'mauritania', 'mr', 'mrt'}),
    frozenset({'mauritius', 'mu', 'mus', 'republic of mauritius'}),
    frozenset({'mayotte', 'myt', 'yt'}),
    frozenset({'mex', 'mexico', 'mx', 'united mexican states'}),
    frozenset({'federated states of micronesia', 'fm', 'fsm', 'micronesia', 'micronesia, federated states of'}),
    frozenset({'md', 'mda', 'moldova', 'moldova, republic of', 'republic of moldova'}),
    frozenset({'mc', 'mco', 'monaco', 'principality of monaco'}),
    frozenset({'mn', 'mng', 'mongolia'}),
    frozenset({'me', 'mne', 'montenegro'}),
    frozenset({'montserrat', 'ms', 'msr'}),
    frozenset({'kingdom of morocco', 'ma', 'mar', 'morocco'}),
    frozenset({'moz', 'mozambique', 'mz', 'republic of mozambique'}),
    frozenset({'burma', 'mm', 'mmr', 'myanmar', 'republic of myanmar'}),
    frozenset({'na', 'nam', 'namibia', 'republic of namibia'}),
    frozenset({'nauru', 'nr', 'nru', 'republic of nauru'}),
    frozenset({'federal democratic republic of nepal', 'nepal', 'np', 'npl'}),
    frozenset({'kingdom of the netherlands', 'netherlands', 'nl', 'nld'}),
    frozenset({'nc', 'ncl', 'new caledonia'}),
    frozenset({'new zealand', 'nz', 'nzl'}),
    frozenset({'ni', 'nic', 'nicaragua', 'republic of nicaragua'}),
    frozenset({'ne', 'ner', 'niger', 'republic of the niger'}),
    frozenset({'federal republic of nigeria', 'ng', 'nga', 'nigeria'}),
    frozenset({'niu', 'niue', 'nu'}),
    frozenset({'nf', 'nfk', 'norfolk island'}),
    frozenset({'macedonia', 'mk', 'mkd', 'north macedonia', 'republic of north macedonia'}),
    frozenset({'commonwealth of the northern mariana islands', 'mnp', 'mp', 'northern mariana islands'}),
    frozenset({'kingdom of norway', 'no', 'nor', 'norway'}),
    frozenset({'om', 'oman', 'omn', 'sultanate of oman'}),
    frozenset({'islamic republic of pakistan', 'pak', 'pakistan', 'pk'}),
    frozenset({'palau', 'plw', 'pw', 'republic of palau'}),
    frozenset({'palestine', 'palestine, state of', 'ps', 'pse', 'the state of palestine'}),
    frozenset({'pa', 'pan', 'panama', 'republic of panama'}),
    frozenset({'independent state of papua new guinea', 'papua new guinea', 'pg', 'png'}),
    frozenset({'paraguay', 'pry', 'py', 'republic of paraguay'}),
    frozenset({'pe', 'per', 'peru', 'republic of peru'}),
    frozenset({'ph', 'philippines', 'phl', 'republic of the philippines'}),
    frozenset({'pcn', 'pitcairn', 'pn'}),
    frozenset({'pl', 'pol', 'poland', 'republic of poland'}),
    frozenset({'portugal', 'portuguese republic', 'prt', 'pt'}),
    frozenset({'pr', 'pri', 'puerto rico'}),
    frozenset({'qa', 'qat', 'qatar', 'state of qatar'}),
    frozenset({'ro', 'romania', 'rou'}),
    frozenset({'ru', 'rus', 'russia', 'russian federation'}),
    frozenset({'rw', 'rwa', 'rwanda', 'rwandese republic'}),
    frozenset({'re', 'reu', 'réunion'}),
    frozenset({'bl', 'blm', 'saint barthélemy'}),
    frozenset({'saint helena, ascension and tristan da cunha', 'sh', 'shn'}),
    frozenset({'kn', 'kna', 'saint kitts and nevis'}),
    frozenset({'lc', 'lca', 'saint lucia'}),
    frozenset({'maf', 'mf', 'saint martin (french part)'}),
    frozenset({'pm', 'saint pierre and miquelon', 'spm'}),
    frozenset({'saint vincent and the grenadines', 'vc', 'vct'}),
    frozenset({'independent state of samoa', 'samoa', 'ws', 'wsm'}),
    frozenset({'republic of san marino', 'san marino', 'sm', 'smr'}),
    frozenset({'democratic republic of sao tome and principe', 'sao tome and principe', 'st', 'stp'}),
    frozenset({'kingdom of saudi arabia', 'sa', 'sau', 'saudi arabia'}),
    frozenset({'republic of senegal', 'sen', 'senegal', 'sn'}),
    frozenset({'republic of serbia', 'rs', 'serbia', 'srb'}),
    frozenset({'republic of seychelles', 'sc', 'seychelles', 'syc'}),
    frozenset({'republic of sierra leone', 'sierra leone', 'sl', 'sle'}),
    frozenset({'republic of singapore', 'sg', 'sgp', 'singapore'}),
    frozenset({'sint maarten (dutch part)', 'sx', 'sxm'}),
    frozenset({'sk', 'slovak republic', 'slovakia', 'svk'}),
    frozenset({'republic of slovenia', 'si', 'slovenia', 'svn'}),
    frozenset({'sb', 'slb', 'solomon islands'}),
    frozenset({'federal republic of somalia', 'so', 'som', 'somalia'}),
    frozenset({'republic of south africa', 'south africa', 'za', 'zaf'}),
    frozenset({'gs', 'sgs', 'south georgia and the south sandwich islands'}),
    frozenset({'republic of south sudan', 'south sudan', 'ss', 'ssd'}),
    frozenset({'es', 'esp', 'kingdom of spain', 'spain'}),
    frozenset({'democratic socialist republic of sri lanka', 'lk', 'lka', 'sri lanka'}),
    frozenset({'republic of the sudan', 'sd', 'sdn', 'sudan'}),
    frozenset({'republic of suriname', 'sr', 'sur', 'suriname'}),
    frozenset({'sj', 'sjm', 'svalbard and jan mayen'}),
    frozenset({'kingdom of sweden', 'se', 'swe', 'sweden'}),
    frozenset({'ch', 'che', 'swiss confederation', 'switzerland'}),
    frozenset({'sy', 'syr', 'syria', 'syrian arab republic'}),
    frozenset({'taiwan', 'taiwan, province of china', 'tw', 'twn'}),
    frozenset({'republic of tajikistan', 'tajikistan', 'tj', 'tjk'}),
    frozenset({'tanzania', 'tanzania, united republic of', 'tz', 'tza', 'united republic of tanzania'}),
    frozenset({'kingdom of thailand', 'th', 'tha', 'thailand'}),
    frozenset({'democratic republic of timor-leste', 'timor-leste', 'tl', 'tls'}),
    frozenset({'tg', 'tgo', 'togo', 'togolese republic'}),
    frozenset({'tk', 'tkl', 'tokelau'}),
    frozenset({'kingdom of tonga', 'to', 'ton', 'tonga'}),
    frozenset({'republic of trinidad and tobago', 'trinidad and tobago', 'tt', 'tto'}),
    frozenset({'republic of tunisia', 'tn', 'tun', 'tunisia'}),
    frozenset({'tkm', 'tm', 'turkmenistan'}),
    frozenset({'tc', 'tca', 'turks and caicos islands'}),
    frozenset({'tuv', 'tuvalu', 'tv'}),
    frozenset({'republic of türkiye', 'tr', 'tur', 'turkey', 'türkiye'}),
    frozenset({'republic of uganda', 'ug', 'uga', 'uganda'}),
    frozenset({'ua', 'ukr', 'ukraine'}),
    frozenset({'ae', 'are', 'uae', 'united arab emirates'}),
    frozenset({'gb', 'gbr', 'uk', 'united kingdom', 'united kingdom of great britain and northern ireland'}),
    frozenset({'united states', 'united states of america', 'us', 'usa'}),
    frozenset({'um', 'umi', 'united states minor outlying islands'}),
    frozenset({'eastern republic of uruguay', 'uruguay', 'ury', 'uy'}),
    frozenset({'republic of uzbekistan', 'uz', 'uzb', 'uzbekistan'}),
    frozenset({'republic of vanuatu', 'vanuatu', 'vu', 'vut'}),
    frozenset({'bolivarian republic of venezuela', 've', 'ven', 'venezuela', 'venezuela, bolivarian republic of'}),
    frozenset({'socialist republic of viet nam', 'viet nam', 'vietnam', 'vn', 'vnm'}),
    frozenset({'british virgin islands', 'vg', 'vgb', 'virgin islands, british'}),
    frozenset({'vi', 'vir', 'virgin islands of the united states', 'virgin islands, u.s.'}),
    frozenset({'wallis and futuna', 'wf', 'wlf'}),
    frozenset({'eh', 'esh', 'western sahara'}),
    frozenset({'republic of yemen', 'ye', 'yem', 'yemen'}),
    frozenset({'republic of zambia', 'zambia', 'zm', 'zmb'}),
    frozenset({'republic of zimbabwe', 'zimbabwe', 'zw', 'zwe'}),
    frozenset({'ala', 'ax', 'åland islands'}),
)


def _country_alias_group(value: str) -> frozenset[str] | None:
    """The alias group containing `value` (already expected lowercased/
    stripped), or None if it isn't a recognized country name/code in any
    of the 249 real ISO entries + colloquial supplements above. Shared by
    every consumer (auto_fill's hint-priority path, apply_answer's direct-
    reply path) so a fix here closes the gap everywhere at once, instead
    of two independently-drifting copies."""
    for group in _COUNTRY_ALIAS_GROUPS:
        if value in group:
            return group
    return None


def _normalize_country_candidate(value: str) -> str:
    """Lowercase/strip a raw country candidate and collapse the specific
    punctuation ISSUE-007 (docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_
    2026_08_17.md) identified as the live bug class -- periods used as
    abbreviation markers ("U.S.A", "US.A", "U.K", "U.A.E") -- down to the
    same plain token `_COUNTRY_ALIAS_GROUPS` already keys on (e.g. "usa",
    "uk", "uae"). Deliberately generic string normalization only (case,
    periods, whitespace) -- never a per-country substitution list, so it
    applies identically to all 249 real countries above, not just the
    US/UK/UAE examples the bug was originally reported against."""
    collapsed = value.strip().lower().replace(".", "")
    return re.sub(r"\s+", " ", collapsed).strip()


def _country_canonical_name(group: frozenset[str]) -> str:
    """Pick a human-readable canonical common name out of an alias group,
    generically -- never a per-country hardcoded lookup table.

    Every group is a flat, unordered frozenset mixing alpha-2 (2 chars),
    alpha-3 (3 chars), common name, and official name -- the original
    pycountry generation order (engine.py:387+ comment) isn't preserved
    once the data became a frozenset. Codes are always <=3 chars by ISO
    3166-1 construction; every common/official name in this table is
    longer than that. Among whatever's left after dropping the codes,
    the common name is reliably the SHORTEST remaining member, since
    official names are always longer superset phrasings of the common
    form ("republic of X", "kingdom of X", "X of America", ...).
    Verified against every group in `_COUNTRY_ALIAS_GROUPS` above (e.g.
    "united states" beats "united states of america"; "south korea"
    beats "korea, republic of"; "ivory coast" beats "republic of côte
    d'ivoire") -- this function's logic never names a specific country."""
    candidates = [member for member in group if len(member) > 3] or list(group)
    return min(candidates, key=len).title()

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

# Verb-anchored country CHANGE command, mirroring _QUANTITY_CHANGE_VERB_RE's
# shape but scoped to "country" -- _COUNTRY_PREP above only recognizes
# DESCRIPTIVE phrasing ("customer in X", "destination country is X"), never
# a change COMMAND ("change country to X"), so a customer explicitly asking
# to change the country mid-session had no detector at all before this
# (docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md follow-up -- live
# bug: "Change country to United States unless the quantity is 10" fell
# through to the generic attribute-disambiguation clarify prompt instead of
# ever being recognized as a country-change request). The negative
# lookahead keeps this from firing on an unrelated change command that
# merely happens to mention "country" later in a longer sentence about
# something else entirely -- "country" must appear within a short span of
# the verb.
_COUNTRY_CHANGE_RE = re.compile(
    r"(?i:\b(?:change|set|update|make\s+it)\b(?:(?!\b(?:quantity|qty)\b).){0,25}?"
    r"\bcountry\b\s+(?:to|as|is)\s+)"
    r"((?:[A-Z]{2}|[A-Z][a-z]+)(?:\s+[A-Z][a-z]+)*)"
)


def detect_country_change_request(question: str) -> str | None:
    """Deterministic detector for an explicit "change country to X" command.

    Returns the as-typed, validated country name (e.g. "United States"),
    or None when no verb-anchored country-change command is present, or
    the captured text isn't a country the engine actually recognizes
    (`CpqEngine.is_recognized_country`) -- never a bare regex fragment.
    """
    m = _COUNTRY_CHANGE_RE.search(question or "")
    if not m:
        return None
    candidate = m.group(1).strip()
    if not CpqEngine.is_recognized_country(candidate):
        return None
    return candidate


# Region hints (abbreviations the generic extractor won't catch as country names)
_REGION_PATTERNS: list[tuple[str, str]] = [
    (r"\b(north\s+america|namer)\b", "NA"),
    (r"\bemea\b", "EMEA"),
    (r"\bapac\b", "APAC"),
    (r"\blatin\s+america\b", "LA"),
]

# Session-level product quantity extraction (docs/CPQ_QUANTITY_SLOTFILLING_
# AND_UI_ISSUES_PLAN_2026_08_11.md) -- a number adjacent to a quantity-
# indicating word or "units"/product-noun phrasing, never a bare number
# anywhere in the message (a model code, a year, a street address digit
# would all be wrongly captured otherwise). Longest/most specific patterns
# first so "50 in qty" doesn't get short-circuited by a looser alternative.
# PR #186 review, critical #1: every pattern's digit group needs a LEFT
# boundary too, not just the trailing `(?!\.\d)` guard -- `\d+` has no
# built-in word-start requirement, so it can start matching mid-identifier.
# Confirmed live: "quote me 5 APX8000 radios" -- the real "5" isn't
# directly followed by "radios" (that "APX8000" is in the way) so it never
# matches, but "8000" lifted straight out of "APX8000" IS directly
# followed by " radios" and matches instead, silently becoming the
# quantity. `(?<![\w.\-])` immediately before the digit group rejects any
# match whose digit run is glued onto a preceding letter/digit/word
# character OR a hyphen (a model code like "APX8000" or "APX-5000", a
# decimal fraction) -- redundant but harmless on patterns that already
# require preceding whitespace via a literal keyword phrase. The hyphen
# exclusion (review follow-up) still allows a genuine negative quantity
# ("quantity is -5") since that "-" is itself preceded by whitespace, not
# by the digit group's own left edge.
# Named separately (not inline in the list literal) so `extract_quantity_
# hint` can identify it by reference and apply the year exclusion against
# the FULL captured digit string -- see the comment where it's used in
# `_QUANTITY_PATTERNS` below.
_MODEL_QUANTITY_PATTERN = re.compile(
    r"(?<![\w.\-])(-?\d+)(?!\.\d)\s*(?i:models?)\b"
)

_QUANTITY_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i:\bqty\s+of\s+)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    re.compile(r"(?i:\bquantity\s+of\s+)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    re.compile(r"(?i:\bquantity\s+(?:is|to|as)\s+)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    re.compile(r"(?i:\bqty\s*[:=]?\s*)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    # "qty to N" -- live-verified gap, 2026-08-13 (docs/CPQ_QUANTITY_
    # EXTRACTION_DEFECTS_PLAN_2026_08_13.md cluster 6): the "quantity"
    # pattern above already supports "is|to|as", but "qty" (its own
    # common shorthand) only ever supported the bare/colon/equals form,
    # so "update qty to 30" silently matched nothing while "update
    # quantity to 30" worked.
    re.compile(r"(?i:\bqty\s+(?:is|to|as)\s+)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    re.compile(r"(?i:\bquantity\s*[:=]?\s*)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    re.compile(r"(?<![\w.\-])(-?\d+)(?!\.\d)\s*(?i:in\s+qty)\b"),
    re.compile(r"(?<![\w.\-])(-?\d+)(?!\.\d)\s*(?i:qty)\b"),
    re.compile(r"(?<![\w.\-])(-?\d+)(?!\.\d)\s*(?i:units?)\b"),
    re.compile(r"(?i:\bi\s+want\s+)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    re.compile(r"(?i:\bneed\s+)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    # "I need pricing for a dozen X" / "...for 12 X" -- live-verified gap,
    # 2026-08-13: the bare "need N" pattern above requires the number
    # RIGHT after "need", so "need pricing for N" (a very common real
    # quoting phrasing) never matched at all, regardless of digit vs
    # word-form. Anchored on the fixed phrase "pricing for" specifically
    # (not a general "for N" pattern) to keep the same narrow-adjacency
    # safety discipline as every other pattern here -- never a bare number
    # anywhere in the message.
    re.compile(r"(?i:\bpricing\s+for\s+(?:an?\s+)?)(?<![\w.\-])(-?\d+)(?!\.\d)\b"),
    # Tolerates up to 3 intervening words between the number and the unit
    # noun ("15 APX NEXT radios") -- live-verified gap, 2026-08-13 (docs/
    # CPQ_QUANTITY_EXTRACTION_DEFECTS_PLAN_2026_08_13.md cluster 5): every
    # pattern here used to require the number strictly ADJACENT to its
    # context word, so a product name sitting between them (the single
    # most common real quoting phrasing) matched nothing at all. Each
    # intervening word must be PURELY alphabetic (no digit anywhere in
    # it) -- a model code glued to digits ("APX8000") must still block
    # the match entirely (PR #186 review, critical #1's existing guard),
    # never be treated as an acceptable "product name" word, and this
    # can never stretch across into an unrelated, separately-stated
    # number later in the same sentence either.
    re.compile(
        r"(?<![\w.\-])(-?\d+)(?!\.\d)\s+(?:[A-Za-z][A-Za-z'-]*\s+){0,3}"
        r"(?i:radios?|devices?|pieces?|pcs)\b"
    ),
    # "model(s)" -- live-verified gap, 2026-08-13 (docs/CPQ_QUANTITY_
    # EXTRACTION_DEFECTS_PLAN_2026_08_13.md cluster 4): "the 2026 model"
    # stated no order quantity at all, but the combined pattern above
    # matched "2026" as if it were one, since a year and a genuine
    # quantity look identical to a bare regex. The year exclusion itself
    # is NOT encoded in this pattern (a fixed-width lookbehind here would
    # only ever inspect the last 4 characters of an arbitrarily long
    # digit run, wrongly rejecting real 5+-digit quantities like 12026 or
    # 32026 whose TRAILING 4 digits happen to look like a year -- PR
    # review finding, 2026-08-13) -- it's applied in `extract_quantity_
    # hint` below, which can check the FULL captured digit string's
    # length before deciding it's a year.
    _MODEL_QUANTITY_PATTERN,
]

# PR #186 review, medium: decimal variants of the same patterns above,
# checked BEFORE the integer patterns run. Without this, a decimal like
# "10.0" gets rejected from matching as "10" by `(?!\.\d)` as intended,
# but the regex engine then backtracks and matches the trailing "0" after
# the decimal point instead of failing outright -- silently turning
# "change quantity to 10.0" into quantity=0. Derived by substituting each
# pattern's own `(-?\d+)(?!\.\d)` integer group for a `(-?\d+\.\d+)`
# decimal group, so the two lists can never drift out of sync with each
# other.
_QUANTITY_DECIMAL_PATTERNS: list[re.Pattern] = [
    re.compile(
        p.pattern.replace(r"(?<![\w.\-])(-?\d+)(?!\.\d)", r"(?<![\w.\-])(-?\d+\.\d+)")
    )
    for p in _QUANTITY_PATTERNS
]

# PR #186 review, critical #2: a thousands-separator comma between two
# digit groups ("1,000") sits at a real word boundary, so an integer
# pattern happily matches just the "1" before it and silently truncates
# the stated quantity -- no rejection, no indication anything was
# mangled. Stripped before any pattern runs, so "1,000" is treated
# exactly like "1000" was always the input. Deliberately narrow (exactly
# 3 digits after the comma, comma glued to digits on both sides) so it
# never touches an ordinary list separator like "5, 1000 items".
_THOUSANDS_SEPARATOR_RE = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")

# A real order is somewhere between "at least one" and "not an absurd
# typo/overflow" -- callers use this to decide whether an extracted number
# is a plausible quantity at all, distinct from "no number found" (None).
# 100,000 units of a single product line is already far beyond any real
# order this catalog has ever seen; treated as a probable typo, not a
# genuine bulk order, same "never silently accept an implausible value"
# discipline the rest of this module already applies elsewhere.
MIN_PRODUCT_QUANTITY = 1
MAX_PRODUCT_QUANTITY = 100_000


def is_valid_product_quantity(value: int) -> bool:
    """True for a real, plausible order quantity -- rejects zero, negative,
    and absurdly large values. Never silently coerces (e.g. clamps a
    negative to 0 or a huge number down to the max) -- callers must reject
    and ask again, not guess what the customer actually meant."""
    return MIN_PRODUCT_QUANTITY <= value <= MAX_PRODUCT_QUANTITY


# Spelled-out quantities ("I want ten APX Next", "twenty-five units") --
# a customer typing the number as a word is exactly as valid as typing a
# digit, and neither the client's report nor a reasonable customer would
# expect one to work and not the other. Deliberately covers "and" only as
# glue between words already in a real number run ("one hundred and
# fifty"), never as a standalone match -- "one" is a valid START token,
# "and" is not, so ordinary text containing "and" is never mistaken for a
# number.
_ONES_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS_WORDS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALE_WORDS = {"hundred": 100, "thousand": 1000, "dozen": 12}
_NUMBER_WORDS = {**_ONES_WORDS, **_TENS_WORDS, **_SCALE_WORDS}
_SIGN_WORDS = {"negative", "minus"}
# Fraction/count modifiers before a scale word ("half a dozen" -> 6, "a
# couple dozen" -> 24) -- live-verified gap, 2026-08-13 (docs/CPQ_
# QUANTITY_EXTRACTION_DEFECTS_PLAN_2026_08_13.md cluster 2): neither
# "half" nor "couple" is a number word, so `_NUMBER_WORD_RUN_RE` used to
# match only the bare scale word ("dozen"), silently dropping the
# modifier and reporting 12 instead of 6/24.
_FRACTION_MODIFIERS = {"half": 0.5}
_COUNT_MODIFIERS = {"couple": 2}
_NUM_WORD_ALT = "|".join(_NUMBER_WORDS)
_MODIFIER_ALT = r"(?:half\s+(?:a\s+)?|(?:a\s+)?couple\s+(?:of\s+)?)"
_NUMBER_WORD_RUN_RE = re.compile(
    rf"\b(?:(?:negative|minus)[\s-]+)?(?:{_MODIFIER_ALT})?(?:{_NUM_WORD_ALT})"
    rf"(?:[\s-]+(?:and[\s-]+)?(?:{_NUM_WORD_ALT}))*\b",
    re.IGNORECASE,
)


def _words_to_number(phrase: str) -> int | None:
    """"twenty-five" -> 25, "one hundred and fifty" -> 150,
    "negative five" -> -5, "half a dozen" -> 6, "a couple dozen" -> 24 --
    None if any token isn't a recognized number word (never guess a
    partial parse). A leading sign word must produce a real negative
    result, never silently drop the sign and return the magnitude as if
    it were positive."""
    tokens = [
        t for t in re.split(r"[\s-]+", phrase.strip().lower())
        if t and t not in ("and", "a", "of")
    ]
    if not tokens:
        return None
    negative = tokens[0] in _SIGN_WORDS
    if negative:
        tokens = tokens[1:]
    if not tokens:
        return None
    multiplier: float = 1
    if tokens[0] in _FRACTION_MODIFIERS:
        multiplier = _FRACTION_MODIFIERS[tokens[0]]
        tokens = tokens[1:]
    elif tokens[0] in _COUNT_MODIFIERS:
        multiplier = _COUNT_MODIFIERS[tokens[0]]
        tokens = tokens[1:]
    if not tokens:
        return None
    total = 0
    current = 0
    for tok in tokens:
        if tok in _NUMBER_WORDS:
            val = _NUMBER_WORDS[tok]
            # Identity check (which WORD it is), never a value check --
            # "twelve" (a _ONES_WORDS entry worth 12) must never be
            # mistaken for the scale word "dozen" just because they share
            # the same numeric value (docs/CPQ_QUANTITY_EXTRACTION_
            # DEFECTS_PLAN_2026_08_13.md cluster 1: "one hundred and
            # twelve" was silently becoming 1200, treating "twelve" as a
            # second multiplier applied on top of "hundred").
            if tok in _SCALE_WORDS:
                current = (current or 1) * val
                if val >= 1000:
                    total += current
                    current = 0
            else:
                current += val
        else:
            return None  # unrecognized token -- abort, never guess
    result = (total + current) * multiplier
    if isinstance(result, float):
        if not result.is_integer():
            return None  # a fractional quantity is never a valid whole count
        result = int(result)
    return -result if negative else result


def _substitute_number_words(text: str) -> str:
    """Replaces every recognizable number-word run with its digit form so
    the existing digit-anchored _QUANTITY_PATTERNS can match it unchanged
    -- e.g. "I want ten APX Next" -> "I want 10 APX Next". A run whose
    words don't form a valid number (shouldn't happen given the regex only
    matches known number words, but kept as a safety net) is left as-is."""
    def _replace(m: re.Match) -> str:
        value = _words_to_number(m.group(0))
        return str(value) if value is not None else m.group(0)
    return _NUMBER_WORD_RUN_RE.sub(_replace, text)


# A sign WORD directly before a DIGIT ("minus 5", "negative 12") --
# live-verified gap, 2026-08-13 (docs/CPQ_QUANTITY_EXTRACTION_DEFECTS_
# PLAN_2026_08_13.md cluster 3): `_SIGN_WORDS` is only ever consulted
# inside `_words_to_number`, which only runs on a matched number-WORD
# run -- a bare digit after a sign word never reaches it at all, so
# "minus 5 units" silently became +5 (the digit-only pattern `(-?\d+)`
# only recognizes a literal "-" character glued to the digit, never the
# word "minus" with a space before the digit). Normalized to the
# literal sign form ("minus 5" -> "-5") before either the decimal or
# integer patterns run, so both paths see it identically.
_SIGN_WORD_DIGIT_RE = re.compile(r"(?i:\b(?:negative|minus)\b)[\s-]+(?=\d)")


def _normalize_quantity_text(text: str) -> str:
    """Shared preprocessing for both the decimal check and the integer
    patterns -- quote-stripping and thousands-separator removal must
    happen identically for both, or a comma/quote could dodge one path
    and not the other."""
    text = re.sub(
        r"[\"'‘’“”]([A-Za-z0-9-]+)[\"'‘’“”]",
        r"\1", text,
    )
    text = _SIGN_WORD_DIGIT_RE.sub("-", text)
    return _THOUSANDS_SEPARATOR_RE.sub("", text)


def extract_quantity_decimal_hint(text: str) -> str | None:
    """The exact decimal substring (e.g. "10.0", "-3.5") when a decimal
    number sits in one of the same quantity-context positions
    `_QUANTITY_PATTERNS` matches integers in -- None otherwise.

    PR #186 review, medium: exists so a caller building a customer-facing
    rejection message can quote what the customer actually typed ("10.0")
    instead of the wrong, confusing digit `extract_quantity_hint`'s own
    regex backtracking used to produce ("0", the fractional remainder).
    Checked BEFORE `extract_quantity_hint` runs its integer patterns at
    all -- this is a short-circuit, not just an alternate lookup.
    """
    normalized = _normalize_quantity_text(text)
    for pattern in _QUANTITY_DECIMAL_PATTERNS:
        m = pattern.search(normalized)
        if m:
            return m.group(1)
    return None


def _is_year_shaped_model_quantity(digits: str) -> bool:
    """True only when `digits` (the exact captured string, sign included)
    is EXACTLY a 4-digit 19xx/20xx run -- never for a longer number whose
    trailing 4 digits merely happen to look like a year. PR review
    finding, 2026-08-13: a fixed-width regex lookbehind can only ever see
    the last 4 characters before the match position, so it can't tell
    "2026" (a real year, no quantity stated) apart from "...2026" at the
    tail of a longer real quantity like "12026" or "32026" -- both would
    wrongly be rejected if the exclusion were encoded purely as a
    lookbehind inside the pattern itself. Checking the FULL captured
    group's length here, in Python, after the match, gets this right."""
    unsigned = digits[1:] if digits.startswith("-") else digits
    return len(unsigned) == 4 and unsigned[:2] in ("19", "20")


def extract_quantity_hint(text: str) -> int | None:
    """The overall product quantity stated in free text, e.g. "50 in qty",
    "qty of 50", "i want 50", "50 radios" -- None when no supported phrasing
    matches. Deliberately narrow (a number must be adjacent to a quantity-
    indicating word) rather than "the first number found anywhere" -- a raw
    number scan would misread a model code, a year, or an unrelated count
    (like a street address) as the quantity.

    Also recognizes the number spelled out as words ("I want ten APX
    Next", "twenty-five units") -- exactly as valid as a digit from a
    customer's point of view, so it must work exactly the same way. Tried
    only as a fallback (digit forms first): the number-word text is
    substituted with its digit equivalent and re-run through the same
    digit-anchored patterns above, so both forms share one set of
    quantity-context rules rather than duplicating each pattern twice.

    Returns the raw parsed integer, including zero/negative when the text
    actually says so ("change quantity to -5") -- callers must validate
    with `is_valid_product_quantity` before accepting, never assume a
    return value here is automatically a sane quantity. A decimal like
    "1.5"/"10.0" is deliberately never matched at all -- checked via
    `extract_quantity_decimal_hint` FIRST and short-circuited to None
    here, rather than relying solely on each integer pattern's own
    `(?!\\.\\d)` guard, which blocks the direct "10" match but does not
    stop the regex engine from backtracking into the fractional
    remainder instead (PR #186 review, medium: "10.0" was silently
    becoming quantity 0 without this).
    """
    text = _normalize_quantity_text(text)
    if extract_quantity_decimal_hint(text) is not None:
        return None
    for pattern in _QUANTITY_PATTERNS:
        m = pattern.search(text)
        if m:
            if pattern is _MODEL_QUANTITY_PATTERN and _is_year_shaped_model_quantity(m.group(1)):
                continue
            try:
                return int(m.group(1))
            except ValueError:
                continue
    substituted = _substitute_number_words(text)
    if substituted == text:
        return None
    for pattern in _QUANTITY_PATTERNS:
        m = pattern.search(substituted)
        if m:
            if pattern is _MODEL_QUANTITY_PATTERN and _is_year_shaped_model_quantity(m.group(1)):
                continue
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


# Any mention of the word "quantity"/"qty"/"how many" at all -- the cheap,
# deterministic pre-filter for even bothering to consider quantity routing.
# Purely a "is it worth looking at this turn at all" gate, not a judgment
# call -- the actual product-vs-catalog-attribute disambiguation (a real
# judgment call, not something a keyword list can reliably make) is an LLM
# decision, made in ask_api.py's _llm_resolve_quantity_target, mirroring
# this file's other single-purpose LLM helpers rather than the big
# generic intent gateway (whose schema has no way to represent "the
# overall product quantity" at all -- it only ever names real ConfigAttr
# variable_names). docs/CPQ_QUANTITY_TARGET_MISROUTE_FIX_PLAN_2026_08_17.md:
# that prompt is reinforced with each candidate's filled_source
# provenance and explicit anti-digit-coincidence guidance, rather than
# routing this decision through pattern-matching instead.
_QUANTITY_WORD_RE = re.compile(r"(?i:\bqty\b|\bquantity\b|\bhow\s+many\b)")
# "change/set/update the quantity to N" vs. a plain question ("what's my
# quantity") -- deterministic, not a judgment call: these are unambiguous
# verb cues, unlike WHICH quantity is meant.
_QUANTITY_CHANGE_VERB_RE = re.compile(
    r"(?i:\b(?:change|set|update|make\s+it|adjust)\b)"
)


def question_mentions_quantity(question: str) -> bool:
    """Cheap, regex-only pre-check: is this turn even worth loading the
    catalog for to consider quantity routing? Callers must check this
    BEFORE loading attrs -- loading the full product config on every
    single turn regardless of content is wasteful and, in a caller with a
    test-double reader, can fail for reasons unrelated to quantity at all.
    """
    return bool(_QUANTITY_WORD_RE.search(question))


def find_catalog_quantity_attrs(attrs: list[ConfigAttr]) -> list[ConfigAttr]:
    """Real catalog attributes shaped like a per-item quantity field: no
    catalog menu (a genuine free-text/numeric attribute), select_type
    integer/float, and "quantity" or "qty" in the display label or variable
    name -- e.g. "Quantity (VX650 Item Type)". These are never asked
    proactively (the session-level product_quantity is), but stay
    reachable when the customer names one directly or picks one via
    disambiguation.
    """
    out = []
    for a in attrs:
        if a.options:
            continue
        if a.select_type not in ("integer", "float"):
            continue
        haystack = f"{a.display_label} {a.variable_name}".lower()
        if "quantity" in haystack or "qty" in haystack:
            out.append(a)
    return out


def quantity_turn_precheck(question: str, attrs: list[ConfigAttr]) -> dict[str, Any] | None:
    """Cheap, deterministic first pass for a quantity-related turn -- None
    when the message isn't about quantity at all (caller falls through to
    normal handling). Otherwise returns the facts the caller needs to
    decide routing:
      {"is_change": bool, "value": int | None, "decimal_value": str | None,
       "candidates": list[ConfigAttr]}

    `decimal_value` (PR #186 review, medium) is set when the message
    stated a decimal quantity ("change quantity to 10.0") -- `value`
    stays None for these (a decimal is never a valid quantity), but
    `is_change` is still True so the caller can reject with a message
    quoting the real decimal text instead of silently doing nothing.

    Deliberately does NOT decide "which quantity does the customer mean" --
    that's a real judgment call once `candidates` is non-empty, made by an
    LLM (ask_api._llm_resolve_quantity_target), not a keyword heuristic
    (docs/CPQ_QUANTITY_SLOTFILLING_AND_UI_ISSUES_PLAN_2026_08_11.md step 3).
    """
    if not _QUANTITY_WORD_RE.search(question):
        return None
    value = extract_quantity_hint(question)
    decimal_value = extract_quantity_decimal_hint(question)
    _has_change_verb = bool(_QUANTITY_CHANGE_VERB_RE.search(question))
    return {
        "is_change": _has_change_verb
        and (value is not None or decimal_value is not None),
        # docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md row
        # 23: exposed separately from `is_change` so a caller can tell
        # "explicit change verb, but nothing parseable at all" ("change
        # quantity to a couple dozen") apart from "not a change attempt
        # in the first place" -- the former is exactly the case an LLM
        # extraction fallback should be tried for; the latter never
        # should be.
        "has_change_verb": _has_change_verb,
        "value": value,
        "decimal_value": decimal_value,
        "candidates": find_catalog_quantity_attrs(attrs),
    }


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

# Process-wide, keyed by (workspace_id, catalog_prefix) — see
# CpqEngine._build_flag_keyword_index. Depends only on the catalog's own
# static rules/attrs, so it's safe to build once per catalog per process
# lifetime rather than re-scanning every BML script on every turn (same
# reasoning as bml.py's _SHARED_SCRIPT_CACHE).
_FLAG_KEYWORD_INDEX_CACHE: dict[tuple[int, str], dict[str, tuple[str, str]]] = {}

# Process-wide, keyed by (workspace_id, catalog_prefix) — see
# CpqEngine._detect_layout_tier / resolve_ui_layout_scope
# (docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md). Layout placement is static
# ingested data, safe to compute once per catalog per process lifetime.
_LAYOUT_TIER_CACHE: dict[tuple[int, str], int] = {}
_LAYOUT_SCOPE_CACHE: dict[tuple[int, str], dict[str, Any] | None] = {}

# docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md — {variable_name: rank} for a
# catalog's decoded native-UI layout export (distinct from the above: this
# carries the `hide` bit and document order the raw relational layout
# tables never decoded). Same process-lifetime caching rationale.
_LAYOUT_COMPONENTS_CACHE: dict[tuple[int, str], list[dict[str, Any]] | None] = {}
_LAYOUT_DISPLAY_ORDER_CACHE: dict[tuple[int, str], dict[str, int] | None] = {}
_LAYOUT_FULL_ORDER_CACHE: dict[tuple[int, str], dict[str, int] | None] = {}
_DEFAULT_LAYOUT_FILE_SOURCE: LayoutFileSource = LocalDirLayoutFileSource()

# docs/CPQ_RULE_JOIN_DATA_CACHING_PERFORMANCE_PLAN_2026_08_10.md — module-
# level, short-TTL cache for CpqEngine._load_rule_join_data, keyed by
# (workspace_id, catalog_prefix). Mirrors data_table_resolver._TABLES_CACHE
# exactly (same problem, same fix): confirmed live a single /ask HTTP
# request calls load_hiding_rules() + load_recommendation_and_constraint_
# rules() + load_validation_rules() back to back, each independently
# re-running the same 4 join-table queries from scratch -- 3+ full re-fetches
# of ~1,300 rules' worth of join data from ONE block of code, in every turn,
# with 14 total call sites across ask_api.py. A short TTL (rather than pure
# process-lifetime) keeps this safe against rule data being re-ingested
# mid-session.
_RULE_JOIN_DATA_CACHE: dict[tuple[int, str], tuple[float, tuple]] = {}
# docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md -- widened from 30.0.
# 30s is shorter than realistic time between two conversational turns (a
# customer reading a question and typing a reply), so this cache was almost
# never actually hit across turns in practice, only within one turn's own
# back-to-back call sites. The staleness risk this TTL guards against (a
# mid-session rule re-ingest) is an occasional admin action, not something
# that happens every 30s -- 300s is a real cross-turn win while still
# bounding staleness to 5 minutes worst-case if the invalidation hook
# (doc_discovery.ingest_confirmed) is ever bypassed.
_RULE_JOIN_DATA_CACHE_TTL_SECONDS = 300.0


def _clear_rule_join_data_cache() -> None:
    """Test-isolation hook -- call from an autouse fixture to prevent this
    process-lifetime cache from leaking fake/monkeypatched rule data
    between tests that reuse the same (workspace_id, catalog_prefix) key.
    Mirrors data_table_resolver._clear_tables_cache."""
    _RULE_JOIN_DATA_CACHE.clear()


# 2026-08-18 perf fix: _load_value_rules' own raw-data dependency
# (_load_rule_join_data, above) was already cached, but _load_value_rules
# ITSELF -- the CPU-bound classification pass that builds 500+ Recommendation/
# Constraint/Validation/Hiding rule objects from those (cached) raw rows --
# was not. Confirmed live: this exact classification work re-runs from
# scratch on every one of its 5 call sites within engine.py (load_
# recommendation_and_constraint_rules, load_validation_rules, load_
# recommendation_rules, ...), which every real CPQ turn calls back-to-back --
# ~28s of pure CPU re-work per turn for a large catalog, not DB latency
# (confirmed live: workspace 93, 500 rec + 186 constraint + 105 hiding
# rules). Same short-TTL, leak-safe pattern as _RULE_JOIN_DATA_CACHE.
_VALUE_RULES_CACHE: dict[tuple[int, str], tuple[float, tuple]] = {}

# 2026-08-28 perf fix: _data_table_forced_vns has NO cache parameter at any
# of its 4 real call sites (build_payload never threads one through), so
# every call re-runs its full _ATTRSEQ_CONFIRMED_REQUIRED_VNS x candidate-
# CPQ-models cross-product from scratch, each candidate lookup only hitting
# data_table_resolver's module-level TABLE cache (no DB re-query) but still
# paying real Python-level function-call/dict-lookup/logging overhead --
# confirmed live: 3,580 such lookups logged within a single APX Next
# Product-selection turn (elapsed_s=177.75 for that turn's rule-eval step
# alone). Same short-TTL, leak-safe pattern as _RULE_JOIN_DATA_CACHE and
# _VALUE_RULES_CACHE above -- keyed on exactly the inputs the function
# actually reads (workspace/catalog/base_model/product plus each
# _ATTRSEQ_CONFIRMED_REQUIRED_VNS member's own filled/filled_multi value),
# so a real change to any of those inputs naturally misses and recomputes;
# nothing else can go stale under this key.
_DATA_TABLE_FORCED_VNS_CACHE: dict[tuple, tuple[float, frozenset]] = {}
_DATA_TABLE_FORCED_VNS_CACHE_TTL_SECONDS = 300.0


def _clear_data_table_forced_vns_cache() -> None:
    """Test-isolation hook -- call from an autouse fixture to prevent this
    process-lifetime cache from leaking fake/monkeypatched data between
    tests that reuse the same cache key. Mirrors _clear_rule_join_data_cache."""
    _DATA_TABLE_FORCED_VNS_CACHE.clear()


# 2026-08-28 perf fix (P5, follow-up to the P2 fix above): _substitute_util_
# get_constraint_vals has no memoization of its own -- confirmed live it
# alone cost 82s/59s/37s across 3 real APX Next passes before
# apply_constraint_rules' own whole-function cache (_constraint_cache)
# stabilized, and on any genuine cache-miss (a real narrowing/resync)
# still re-walks the full _cpq_model_candidates cross-product once per
# script-backed ConstraintRule. Keyed on the full `filled`-state signature
# (not just base_model/product) because resolve_whitelist_values' own
# multi-condition row matching (_row_conditions_match) can depend on ANY
# filled attribute, not just the two obviously-relevant ones -- see
# _fill_signature's own docstring for why a narrower signature is unsafe
# here (same failure class as the Package Type bug it was written to
# prevent).
_SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE: dict[tuple, tuple[float, str]] = {}
_SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE_TTL_SECONDS = 300.0


def _clear_substitute_util_get_constraint_vals_cache() -> None:
    """Test-isolation hook -- mirrors _clear_data_table_forced_vns_cache."""
    _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE.clear()


_RULE_JOIN_DATA_CACHE_LAST_SEEN_MARKER: list[float | None] = [None]
_VALUE_RULES_CACHE_LAST_SEEN_MARKER: list[float | None] = [None]
_DATA_TABLE_FORCED_VNS_CACHE_LAST_SEEN_MARKER: list[float | None] = [None]
_SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE_LAST_SEEN_MARKER: list[float | None] = [None]
# docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md -- widened from 30.0,
# same reasoning as _RULE_JOIN_DATA_CACHE_TTL_SECONDS above.
_VALUE_RULES_CACHE_TTL_SECONDS = 300.0


def _clear_value_rules_cache() -> None:
    """Test-isolation hook -- same purpose as _clear_rule_join_data_cache."""
    _VALUE_RULES_CACHE.clear()


# docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_BLIND_PICK_PLAN_2026_08_10.md -- a
# CANDIDATE registry of data tables known to be missing from AT LEAST ONE
# ingested workspace historically (not attribute names -- a hiding rule
# anywhere, for any attribute, that structurally depends on one of these
# tables can never resolve THERE, so auto_fill warns and skips rather than
# asking forever). Extend this tuple if another candidate-missing table
# surfaces; never hardcode which attributes are affected -- that's derived
# generically from which hiding rules reference the table.
#
# 2026-08-18 (Raven PR #211 review, finding #4): this was briefly emptied
# to `()` on a single-workspace verification (workspace 93 -- 511
# UserGroupMapping rows confirmed ingested there). Cross-workspace check
# (docs/CPQ_MULTISELECT_AUTOFILL_AND_COUNTRY_CONFIGDATA_PLAN_2026_08_18.md)
# found UserGroupMapping ingested ONLY for workspace 93 -- 16 other live
# workspaces (1, 27, 28, 29, 31, 38, 51, 61, 63, 64, 73, 85, 88, 90, 91, 92)
# have ZERO UserGroupMapping rows. Emptying this constant globally would
# have silently defeated Group 1's skip for every one of those workspaces --
# `dHSAssetTagLabel_astro`/`cBPQRCode_astro`/`fedQRCode_astro` would blind-
# pick a wrong value there instead of correctly staying skipped. Fixed
# properly instead: this list is now just the CANDIDATE names to check --
# `_hiding_rule_needs_missing_data_table` verifies actual ingestion PER
# WORKSPACE (live query, cached) rather than assuming one workspace's
# ingestion status applies globally.
_KNOWN_MISSING_DATA_TABLES = ("UserGroupMapping",)

# workspace_id -> {table_name.lower(): is_ingested_bool}, short-TTL so a
# newly-completed ingestion run is picked up without a process restart,
# same convention as this file's other per-workspace caches (_DT_CACHE,
# _LAYOUT_*_CACHE).
_TABLE_INGESTED_CACHE: dict[int, dict[str, bool]] = {}
_TABLE_INGESTED_CACHE_TTL_SECONDS = 300.0
_TABLE_INGESTED_CACHE_TS: dict[int, float] = {}


def _table_ingested_for_workspace(table_name: str, workspace_id: int | None) -> bool:
    """True if `table_name` has at least one real ingested entity in
    `workspace_id`. `workspace_id=None` (no workspace context available,
    e.g. an offline/unit-test caller) conservatively returns False -- same
    "assume missing, never assume present" default `_KNOWN_MISSING_DATA_
    TABLES` always used before this was workspace-scoped."""
    if workspace_id is None:
        return False
    key = table_name.lower()
    now = time.monotonic()
    cached_ts = _TABLE_INGESTED_CACHE_TS.get(workspace_id, 0.0)
    if now - cached_ts >= _TABLE_INGESTED_CACHE_TTL_SECONDS:
        _TABLE_INGESTED_CACHE.pop(workspace_id, None)
    per_ws = _TABLE_INGESTED_CACHE.setdefault(workspace_id, {})
    if key in per_ws:
        return per_ws[key]
    try:
        rows = get_cpq_rdb().fetch_entities_by_type(workspace_id, table_name)
        ingested = bool(rows)
    except Exception:
        logger.debug(
            "cpq: table-ingestion check failed for %r ws=%s -- assuming "
            "not ingested (never assume present on a lookup failure)",
            table_name, workspace_id, exc_info=True,
        )
        ingested = False
    per_ws[key] = ingested
    _TABLE_INGESTED_CACHE_TS[workspace_id] = now
    return ingested


def _hiding_rule_needs_missing_data_table(
    rule: "HidingRule", workspace_id: int | None = None,
) -> bool:
    """True if `rule`'s script (declarative or condition-script form)
    references a data table that is NOT ingested for `workspace_id` -- see
    `_KNOWN_MISSING_DATA_TABLES` for the candidate list and
    `_table_ingested_for_workspace` for the per-workspace check. Such a
    rule can never resolve to a real hide/show outcome in THIS workspace,
    so its target should never be silently asked about forever here --
    even though the exact same table may be genuinely ingested (and this
    same rule shape genuinely resolvable) in a different workspace.

    `workspace_id=None` (no caller passes it) preserves the original,
    fully conservative behavior: every candidate table is treated as
    missing everywhere, identical to today's behavior for any caller that
    doesn't supply a workspace.
    """
    script = (rule.script or "") + (getattr(rule, "condition_script", None) or "")
    if not script:
        return False
    script_lower = script.lower()
    return any(
        table.lower() in script_lower
        and not _table_ingested_for_workspace(table, workspace_id)
        for table in _KNOWN_MISSING_DATA_TABLES
    )


def _parenthetical_suffix(text: str) -> str | None:
    """The content of a trailing "(...)" segment in `text`, or None.

    Catalog display names often encode a distinguishing variant this way —
    "APX NEXT (4G LTE+5G)": a common family name outside the parens, the
    specific variant inside. extract_catalog_hints' D2 verbatim rule
    requires the WHOLE glued option text to appear in the question; a
    customer answering with only the variant ("I'll take the 4G LTE+5G
    version") — the most natural way to name it — never satisfies that,
    even though the variant is exactly what distinguishes this option from
    its siblings. Exposing the inner segment as an additional candidate
    text lets the existing ambiguity/negation/never-guess machinery in
    extract_catalog_hints treat it exactly like any other option text —
    this is plain string parsing (no pattern list, no per-product
    special-casing), so it generalizes to any catalog option shaped this
    way, not just this one product.

    Only a single, unnested trailing "(...)" is trusted — returns None on
    anything else (nested parens, an unmatched "(" earlier in the segment,
    empty parens), so a shape this helper can't safely parse is simply
    never offered as a candidate rather than risk extracting a corrupted
    fragment (e.g. a literal trailing ")" left over from a nested group).
    """
    stripped = text.rstrip()
    if "(" not in stripped or not stripped.endswith(")"):
        return None
    _before, _, after = stripped.rpartition("(")
    inner = after[:-1].strip()
    if "(" in inner or ")" in inner:
        return None
    return inner or None


def _normalize_for_hint(text: str) -> str:
    return _HINT_STRIP_RE.sub("", text.lower())


def _normalize_for_hint_with_map(text: str) -> tuple[str, list[int]]:
    """Same stripping as _normalize_for_hint, but also returns index_map
    where index_map[i] is the original `text` position that the i-th
    character of the normalized string came from — lets a match found in
    the glued/stripped string be traced back to its real location, e.g. to
    inspect the words that precede it (see _is_negated_before)."""
    lowered = text.lower()
    kept: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(lowered):
        if ch.isalnum():
            kept.append(ch)
            index_map.append(i)
    return "".join(kept), index_map


# Cue words that flip a literal option-text match into an exclusion rather
# than a selection — "exclude any... carry solutions" contains the exact
# text of the real option "Carry Solutions", but means the opposite
# (confirmed live: accessoriesSolutionSet_astro was auto-filled to "CARRY
# SOLUTIONS" from that sentence). Word-bounded so short cues ("no", "not")
# don't fire inside unrelated words ("know", "notification").
_NEGATION_RE = re.compile(
    r"\b(exclud\w*|without|no|not|never|omit\w*|remov\w*|minus)\b",
    re.IGNORECASE,
)
_NEGATION_WINDOW_CHARS = 40


def _is_negated_before(question_lower: str, orig_pos: int) -> bool:
    window_start = max(0, orig_pos - _NEGATION_WINDOW_CHARS)
    return bool(_NEGATION_RE.search(question_lower[window_start:orig_pos]))


def _find_plural_tolerant(q_norm: str, phrase: str) -> int:
    """q_norm.find(phrase), tolerating a missing/extra trailing "s".

    Confirmed live: option text "CARRY SOLUTIONS" (normalized
    "carrysolutions") never matched a customer writing "no carry solution"
    (singular) — an exact-substring search on "carrysolution" fails against
    "carrysolutions" by exactly one character, so the negation guard never
    saw it and accessoriesSolutionSet_astro was silently auto-filled with
    the very thing the customer excluded. Trying the phrase with its
    trailing "s" added/removed catches this without weakening the
    real length/ambiguity guards elsewhere (this only changes WHERE a
    phrase is found in the question, not which attrs are eligible).
    """
    idx = q_norm.find(phrase)
    if idx != -1:
        return idx
    variant = phrase[:-1] if phrase.endswith("s") else phrase + "s"
    if len(variant) < _HINT_MIN_PHRASE_LEN:
        return -1
    return q_norm.find(variant)


# Attr key fragments that represent "decision-required" choices — never
# auto-fill via first-option fallback or rule-governed default-or-first (D2),
# regardless of rule coverage. Only filled via explicit hint or valid
# default_value. hwVersion was removed per D1
# (CPQ_CASCADE_CONVERSATION_PLAN.md §2) — it's no longer a special-cased
# anchor, it resolves through the normal rule cascade like any other
# dependent variable.
_DECISION_REQUIRED_KEYS: frozenset[str] = frozenset({
    "country", "region",
})

# Public alias so ask_api can access it without importing a private name.
DECISION_REQUIRED_KEYS = _DECISION_REQUIRED_KEYS

# Core navigational anchors -- never suppressed by the attrSequence-driven
# "doesn't apply to this base model" check (CpqEngine._suppress_ungoverned_
# attrs), even when a real ingested attrSequence table has no row for one
# of these at the active base model. These decide WHICH base model/product
# is even active, so attrSequence coverage for them is beside the point;
# generic fragment match, same convention as _DECISION_REQUIRED_KEYS.
_NEVER_SUPPRESS_FRAGMENTS: frozenset[str] = frozenset({
    "basemodel", "product", "country", "region", "hwversion", "hardwareversion",
})

# The exact (not fragment-matched) variable names of this catalog's real
# decision anchors -- used by evaluate_rules_loop to tell "hidden because an
# anchor is still blank" (merely gating, values dormant/preserved) apart
# from "hidden with every anchor already answered" (a real, current-state
# conflict, values stripped exactly as before). See the strip-vs-preserve
# comment at its one call site for the live-confirmed regression this
# narrower, exact-name check exists to avoid repeating.
_DECISION_ANCHOR_VNS: tuple[str, ...] = (
    "ultimateDestinationCountry", "hWVersion_astro",
    "productSelectionProduct_all", "modelSelectionbaseModel_astro",
)

# Attrs confirmed live (2026-08-16, cross-checked against real native-UI
# screenshots for APX NEXT Enhanced/XE 4G LTE+5G) to be orphaned/legacy --
# they have ZERO attrSequence rows anywhere in the workspace (any CPQModel,
# any base model), so _suppress_ungoverned_attrs's "total silence, not a
# confident exclusion" carve-out normally leaves them visible. For these
# specific, verified-dead attrs that default is wrong: native CPQ never
# renders modelSelectionFrequencyBands_astro (20-option legacy single-
# select) or modelSelectionFrequencyBandPlus_astro for any APX NEXT
# product -- modelSelectionFrequencyBandMsl_astro is the real, attrSequence-
# governed control. Narrow allowlist, not a change to the general silence
# carve-out, since most attrs with zero attrSequence coverage genuinely are
# ambiguous rather than confirmed-dead.
_CONFIRMED_DEAD_ATTRS: frozenset[str] = frozenset({
    "modelSelectionFrequencyBands_astro",
    "modelSelectionFrequencyBandPlus_astro",
})

# Multi-select attrs confirmed live (2026-08-16) to default to EVERY
# Whitelist/Data-Table-confirmed-legal option checked, not just one --
# real-world meaning is "which of these apply" (coverage), not "pick one
# among many". See the one call site (auto_fill's narrowed-legal-values
# branch) for why this is a narrow, named allowlist rather than a change
# to that branch's default behavior for every multi-select.
_SELECT_ALL_NARROWED_LEGAL_MULTI_VNS: frozenset[str] = frozenset({
    "modelSelectionFrequencyBandMsl_astro",
})

# Live-confirmed (2026-08-16): additionalSystemEnhancementFeatureType_
# astro got blind-picked to its first menu option with NOTHING in the
# catalog behind it -- required=False, no real default_value, zero
# recommendation rules ever targeting it -- and that guess silently
# cascaded into narrowing an unrelated, real question (Application
# Services) down to the wrong 5-option set. `_no_real_fill_justification`
# is the dynamic, catalog-agnostic test for this exact shape, computed
# per-attribute at call time rather than a hardcoded attribute-name list
# -- any attribute anywhere in this (or another) catalog with the same
# profile gets the same protection automatically, with no code change
# needed to name it. Checked at the two specific auto_fill call sites
# that had no other real-data guard at all: the unconditional multi-
# select "nothing to justify a subset" fallback, and the two single-
# select first-by-order fallbacks (display-order-based and the final
# bare-menu-order one). Every earlier, more specific branch in the same
# method (satisfied recommendation, Data Table single-match, confirmed-
# valid default under an active constraint, exactly-one-remaining-
# option) is left completely untouched and still fires normally for any
# attr whenever real data actually supports it -- this only blocks the
# LAST-resort "guess from the whole unconstrained menu" step.
def _no_real_fill_justification(
    attr: "ConfigAttr", rec_by_target: dict[int, list[Any]],
) -> bool:
    if attr.required:
        return False
    if _valid(attr.default_value):
        return False
    if rec_by_target.get(attr.entity_id) or rec_by_target.get(attr.source_id):
        return False
    return True


def _fill_signature(
    filled: dict[str, str],
    filled_multi: dict[str, list[str]],
    visible_ids: set[int],
) -> tuple:
    """docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md — a broad, unhashed
    snapshot of everything a "default_first_available" blind guess could
    plausibly depend on: every filled single/multi value plus the current
    visible-attribute-id set (a hiding-rule-driven visibility change can
    alter legal options too, not just a value change). Deliberately NOT
    scoped down to "only attrs this one plausibly depends on" -- no safe
    dependency graph exists yet for script-backed rules (docs/CPQ_TURN_
    LATENCY_FIX_CORRECTNESS_RISK_2026_08_19.md), so a narrower signature
    risks silently missing a real narrowing, the same failure class as the
    Package Type bug. Compared by direct tuple equality, never hashed --
    sidesteps Python's per-process-randomized hash() entirely.
    """
    return (
        tuple(sorted(filled.items())),
        tuple(sorted((k, tuple(sorted(v))) for k, v in filled_multi.items())),
        tuple(sorted(visible_ids)),
    )

# Explicit, named business-accepted exceptions to the dynamic check
# above -- NOT a technical classification, a deliberate product decision
# to trade guess-risk for fewer prompts on ONE specific attribute.
# accessoriesSolutionSet_astro (2026-08-16): its real constraint
# ("Constraint solution set based on product") depends on Oracle_
# BomItemMap/Oracle_BomItemDef, not yet ingested -- until they are, it
# blind-picks the first menu option instead of asking. No further change
# needed once ingestion lands: the confident branches this exception
# doesn't touch (recommendation match, Data Table single-match, exactly-
# one-remaining-option) all run BEFORE the blind-pick fallback, so a
# real constraint narrowing this to one legal category will auto-fill
# through one of those first and the blind guess simply stops firing.
#
# 2026-08-18: three siblings added, each individually confirmed via live
# rule-action data (not assumed from a shared code shape) to have the
# identical constraint-only governance profile as accessoriesSolutionSet_
# astro above -- a real rule (recommendation OR constraint) targets the
# attribute's own value, but _no_real_fill_justification's recommendation-
# only check can't see the constraint, so it was blocked from ever
# reaching the confident branches even though real catalog governance
# exists:
#   - relatedServicesType_astro ("Service Type"): real script-backed
#     constraint querying the real Data Table relSoftAndServcParts for
#     the current CPQ model (rule 18654807132, constraint_type=1).
#   - relatedServiceCategory_astro ("Service Category"): real constraint
#     (rule 17691443159, script-backed) plus a declarative one (rule
#     17691443165) -- hidden until relatedServicesType_astro resolves.
#   - selectEndUserType_astro ("Select End User Type"): one real
#     constraint (rule with attribute_id 17691442... verified via live
#     rule-action query), zero recommendations.
# A GENERIC fix (letting rule_governed_ids' hiding+recommendation+
# constraint union satisfy this check for every attr) was tried and
# reverted the same day -- it also let additionalSystemEnhancementFeature
# Type_astro (the documented "9-of-11, never guess" incident this whole
# check exists to prevent) bypass the gate, and separately let Group-1
# hiding-only-governed attrs (e.g. cBPQRCode_astro) skip their
# missing-data-table warn-and-skip. This named-allowlist approach only
# grants the exception to attributes individually verified safe.
_BLIND_FILL_RISK_ACCEPTED_VNS: frozenset[str] = frozenset({
    "accessoriesSolutionSet_astro",
    "relatedServicesType_astro",
    "relatedServiceCategory_astro",
    "selectEndUserType_astro",
    # 2026-08-19: four siblings added, each individually confirmed via the
    # real Attrsequence Data Table (per-base-model AttrName+CPQModel+
    # BaseModel+optionOrReqFlag rows, workspace 93) to be Required for
    # nearly every base model -- a real governance signal
    # _no_real_fill_justification can't see, since it only checks
    # ConfigAttr.required (sourced from bm_config_attr.required, confirmed
    # live to be 0/unreliable for essentially every attribute in this
    # catalog, not the real per-base-model flag) and rec_by_target. Each
    # was live-verified separately, not assumed from a shared shape:
    #   - baselineReleaseSW_astro ("Software Release"): 448/449
    #     Attrsequence rows marked Required.
    #   - applicationServicesSelection_astro ("Application Services
    #     Selection"): 28/28 rows marked Required (always).
    #   - carrierSelectionMultiSelect_astro ("Carrier Selection"): 3/3
    #     rows marked Required (always) -- also cited by name in this
    #     file's own auto_fill multi-select branch as governed via real
    #     attrSequence coverage.
    #   - wirelessCarrier_astro ("Wireless Carrier"): Required (flag "R")
    #     under real APX NEXT CPQModels (APXNEXTSINGLE, APXNEXTXNALL,
    #     APXNEXTINTLFED, APXNEXTINTL, ...) for 9 base models -- confirmed
    #     live to share ZERO base models with carrierSelectionMultiSelect_
    #     astro's own Required coverage (single base model H55TGT9PW8BN).
    #     The two are mutually-exclusive per-base-model siblings for the
    #     same real-world "carrier" concept (single-select on some base
    #     models, multi-select on others), not one legacy/one real -- both
    #     genuinely required, just never for the same base model.
    #   - packingPackageType_astro ("Package Type"): 452/453 Attrsequence
    #     rows marked Required. Distinct from its own real constraint
    #     rule (18131370895, script-backed on additionalSystemEnhancement
    #     FeatureType_astro/ICE KIT) which already auto-fills it when that
    #     rule resolves to exactly one legal value -- this allowlist entry
    #     only covers the fallback case where that constraint hasn't
    #     narrowed anything yet.
    # Two siblings from the same investigation were deliberately NOT
    # added: solutionTypeDuration_astro (6/215 Required -- mostly
    # optional, base-model dependent) and applicationServicesIntroBundle_
    # astro (12/86 Required -- same caveat). promoApplicationServices_
    # astro/additionalApplicationServices_astro/aTAKNonPromoApplication
    # Services_astro were also checked and confirmed genuinely optional
    # (0 Required rows each) -- correctly excluded, not an oversight.
    "baselineReleaseSW_astro",
    "applicationServicesSelection_astro",
    "carrierSelectionMultiSelect_astro",
    "packingPackageType_astro",
})

# Subset of _BLIND_FILL_RISK_ACCEPTED_VNS's 2026-08-19 additions that were
# individually confirmed Required (not just "safe to blind-fill via real
# governance rules", the reason the set's other four members are in it) —
# see that set's docstring for the per-attribute Attrsequence row counts.
# Used by `_is_mandatory_input_attr` for beautify's Mandatory/System split
# instead of the unreliable flat ConfigAttr.required/bm_config_attr.
# required column (same docstring, "confirmed live to be 0/unreliable for
# essentially every attribute in this catalog").
#
# packingPackageType_astro deliberately excluded (2026-08-19, rebase-time
# reconciliation with docs/CPQ_PackageType_HardExclude_RCA_2026-08-19.docx
# and docs/CPQ_Beautify_Mandatory_Section_Miscategorization_2026_08_19.md):
# a high Attrsequence Required row-count alone does NOT mean a real
# Mandatory-User-Input UI field -- Package Type is one of the confirmed
# exceptions (`_RECOMMENDED_CONFIG_ONLY_VNS` below), live-verified against
# the real native APX NEXT screenshot to appear ONLY under "Recommended
# Configuration," never under "Mandatory User Input," regardless of its
# Attrsequence row count. Including it here would have unconditionally
# (no per-consumer gate) leaked it back into `config_data` too, directly
# contradicting that already-verified classification.
_ATTRSEQ_CONFIRMED_REQUIRED_VNS: frozenset[str] = frozenset({
    "baselineReleaseSW_astro",
    "applicationServicesSelection_astro",
    "carrierSelectionMultiSelect_astro",
    "wirelessCarrier_astro",
})

# Multi-select attrs individually confirmed (Attrsequence: 0 Required rows
# across every base model checked, workspace 93) to be genuinely optional
# add-on choices with no active governance forcing a selection --
# "customer wants none of these" is itself a real, valid, low-risk answer
# for these three, unlike blind-picking a real business choice among them.
# Distinct from _sole_opt_out_option (which finds a literal "None"/"not
# needed" MENU ITEM the catalog authored): none of these three carry such
# an option, so that existing mechanism can't resolve them -- this is a
# separate case, "the attr itself can validly stay empty," not "the menu
# declares an opt-out value." Never applied generically: an attr not
# individually verified genuinely optional here still falls through to
# the existing blind-pick-first-option fallback (or asks), same as
# before this addition.
#   - promoApplicationServices_astro ("Promo Application Services"):
#     0/12 Attrsequence rows Required.
#   - additionalApplicationServices_astro ("Additional Application
#     Services"): 0/85 Attrsequence rows Required.
#   - aTAKNonPromoApplicationServices_astro ("ATAK Non-Promo Application
#     Services"): zero Attrsequence rows at all (also hidden by its own
#     rule unless ATAK is explicitly enabled).
_OPTIONAL_EMPTY_FILL_ACCEPTED_VNS: frozenset[str] = frozenset({
    "promoApplicationServices_astro",
    "additionalApplicationServices_astro",
    "aTAKNonPromoApplicationServices_astro",
})

# Catalog-agnostic "this is the opt-out choice" phrasing -- an attr with
# no real fill justification (`_no_real_fill_justification`) still has a
# safe, non-guessed answer available when exactly one of its menu options
# itself says "nothing needed here" (e.g. preSalesEnggAcknowledgement_
# astro's "Add-on sale, new system components or SI services are not
# required"). This is fundamentally different from blind-picking among
# several real business choices (_BLIND_FILL_RISK_ACCEPTED_VNS) -- it's
# recognizing the customer's own catalog already offers a declared
# "skip" answer, the same concept next_question_prompt's own "(Optional
# — say 'skip' or 'none needed')" hint already surfaces conversationally.
# Deliberately requires EXACTLY one match -- 2+ matches means the menu's
# phrasing is ambiguous about which is the real opt-out, and guessing
# between them would be exactly the guess-risk this whole mechanism
# exists to avoid, so it falls through to asking instead.
_OPT_OUT_OPTION_RE = re.compile(
    r"\bnot\s+(?:required|needed|applicable)\b"
    r"|\bnone\s+(?:needed|required)\b"
    r"|\bn/?a\b"
    r"|\bno(?:t)?\s+(?:action|service|item)s?\s+(?:required|needed)\b",
    re.IGNORECASE,
)


def _sole_opt_out_option(valid_opts: list[Any]) -> Any | None:
    matches = [
        o for o in valid_opts
        if _OPT_OUT_OPTION_RE.search(o.display_name or "")
        or _OPT_OUT_OPTION_RE.search(o.item_value or "")
    ]
    return matches[0] if len(matches) == 1 else None


# Some catalog attributes carry two menu options with the IDENTICAL
# display_name but different item_value (a real BigMachines authoring
# duplicate, not an ingestion artifact -- confirmed live in the raw XML
# export for applicationServicesIntroBundle_astro: item_value "5 YEAR"
# (order 5) and "5 YEARS" (order 8) both display as "5 Year"). Before
# this fix, apply_answer's exact-display-name match returned whichever
# duplicate came first in option order, regardless of which one any
# governing rule actually keys off. Live-traced: the hiding rule that
# keeps additionalApplicationServices_astro visible only recognizes the
# literal "5 YEARS" (plural) -- matching the singular "5 YEAR" duplicate
# left the attribute stuck hidden even after the customer answered the
# duration question. Named per-attribute map (not a generic
# first/last-wins heuristic) so only individually verified duplicates
# get resolved; an unlisted attribute's duplicate options still fall
# through to first-match, same as before.
_DUPLICATE_DISPLAY_NAME_CANONICAL_ITEM_VALUE: dict[str, str] = {
    "applicationServicesIntroBundle_astro": "5 YEARS",
}

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
from aryx.cpq import auto_fill_hw_order
from aryx.cpq import catalog_hints
from aryx.cpq import mandatory_input
from aryx.cpq import auto_fill_postpass
from aryx.cpq import auto_fill_resolve

_DEFAULT_CPQ_MODEL_CANDIDATES: tuple[str, ...] = ("APXNEXT", "APXNEXT_BOM")


def _cpq_model_candidates(
    product_name: str, workspace_id: int | None = None, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None, base_model: str = "",
) -> tuple[str, ...]:
    return data_table_bridge._cpq_model_candidates(
        product_name, workspace_id, catalog_prefix, cache, base_model,
    )


# Matches `put(<dictVar>,"Attribute Variable Name","<attrName>")` -- the
# real BML idiom rule scripts use to name their own target attribute.
# Case/quote-style-tolerant since real scripts vary ("inputparam" vs
# "inputParam", "Attribute Variable Name" is always this exact label
# though -- confirmed across every traced rule).
_UTIL_ATTR_VAR_NAME_RE = re.compile(
    r'put\(\s*\w+\s*,\s*"Attribute Variable Name"\s*,\s*"([^"]+)"\s*\)',
)
# Matches the actual `util.getConstraintVals(<dictVar>, <listVar>)` call
# site to replace -- same idiom every real constraint-rule script uses
# (docs/CPQ_UTIL_LIBRARY_FUNCTION_INVENTORY_2026_08_13.md). This is a
# NATIVE, compiled Oracle Java platform function with no BML source in
# any export ever seen -- the BML evaluator correctly can't execute it and
# returns "unknown" (never guess), which is why a constraint rule calling
# it silently narrows nothing instead of erroring. Confirmed live
# (2026-08-14): "Restrict Model Selection Attributes (Portable)" targeting
# modelSelectionFrequencyBands_astro returns None from
# BmlEvaluator.allowed_values_for_script for exactly this reason, leaving
# the raw catalog menu unfiltered instead of the real, narrowed legal set.
_UTIL_GET_CONSTRAINT_VALS_CALL_RE = re.compile(
    r'util\.getConstraintVals\s*\(\s*\w+\s*,\s*\w+\s*\)',
)


def _substitute_util_get_constraint_vals(
    script: str, filled: dict[str, str],
    workspace_id: int | None, catalog_prefix: str,
    cache: dict[tuple[int, str], tuple] | None,
) -> str:
    """Precompute `util.getConstraintVals(...)` and splice the real,
    ingested legal-value set into `script` as a pipe-delimited string
    literal (the same delimiter convention BmlEvaluator's own Tier-2
    prompt already documents: "determine which values the script allows
    (its returnVal, split on '|')"), so the shared Tier-1/Tier-2 evaluator
    sees a script with NO `util.` reference left and can parse the
    surrounding if/elif chain (or, for the common single-statement idiom,
    the bare `return "<literal>"`) normally instead of being forced to
    Tier-2 LLM guessing purely because of this one call.

    `util.getConstraintVals`'s real backing data (docs/CPQ_UTIL_LIBRARY_
    FUNCTION_INVENTORY_2026_08_13.md) is the same already-ingested
    constraint-shaped Data Table `resolve_whitelist_values` already
    queries for the narrowed-ask/blind-pick paths elsewhere in this file
    (the "Constrain Master String" the real script reads from is itself
    built from these same rows) -- reused directly here rather than
    reimplementing the AND-condition matching a second time.

    Deliberately narrow: only substitutes when (a) the call is present at
    all, (b) the script's own "Attribute Variable Name" param names the
    real target attr, (c) CPQModel/base model both resolve from `filled`,
    and (d) `resolve_whitelist_values` finds real ingested rows for this
    exact (cpq_model, base_model, attr_var_name) combination -- `None` (no
    rows at all, e.g. the confirmed-live APX NEXT Enhanced/Frequency Bands
    gap) leaves the script unchanged, still falling through to Tier-2
    exactly as before; only a genuine `None`-vs-list distinction changes
    behavior, never a guess. An empty list (`[]`, real rows exist but none
    match the current filled context) still substitutes -- a confirmed
    "nothing legal right now" is real information, not an unknown.
    """
    if "util.getConstraintVals" not in script or workspace_id is None:
        return script
    attr_match = _UTIL_ATTR_VAR_NAME_RE.search(script)
    if not attr_match:
        return script
    attr_var_name = attr_match.group(1)
    base_model = filled.get("modelSelectionbaseModel_astro", "")
    product = filled.get("productSelectionProduct_all", "")
    if not base_model:
        return script

    # 2026-08-28 perf fix: called once per script-backed ConstraintRule on
    # every apply_constraint_rules cache-miss (its own RC6 whole-function
    # cache -- see _constraint_cache -- only avoids re-running this when
    # NOTHING relevant changed; a genuine narrowing/resync still forces a
    # full recompute here). Each call independently re-walks the full
    # _cpq_model_candidates cross-product for its own attr_var_name --
    # confirmed live: this alone cost 82s/59s/37s across 3 passes for APX
    # Next before the per-pass constraint cache stabilized (see the
    # narrowing_rec_rules loop's own comment a few lines below this
    # function's second call site). Memoized here on exactly what
    # resolve_whitelist_values actually reads -- the full `filled` dict
    # (via _row_conditions_match's multi-condition row matching, NOT just
    # base_model/product) -- using the same broad, provably-safe
    # _fill_signature already used elsewhere in this file for this exact
    # class of problem (RC1: a narrower signature risks silently missing a
    # real narrowing). Still a real win: this function is called from two
    # sites within apply_constraint_rules, and apply_constraint_rules
    # itself has 4 call sites across a turn -- an identical (script,
    # filled-state) pair recurring across any of those no longer re-walks
    # the candidate list.
    _cache_key = (
        workspace_id, catalog_prefix, script, _fill_signature(filled, {}, frozenset()),
    )
    _marker_at_read = _invalidate_on_marker_change(
        _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE,
        _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE_LAST_SEEN_MARKER,
    )
    _hit = _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE.get(_cache_key)
    if _hit is not None:
        _ts, _cached_result = _hit
        if time.monotonic() - _ts < _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE_TTL_SECONDS:
            return _cached_result

    _result = script
    for cpq_model in _cpq_model_candidates(
        product, workspace_id, catalog_prefix, cache, base_model=base_model,
    ):
        values = dt_resolve_whitelist_values(
            cpq_model, base_model, attr_var_name, filled, workspace_id, catalog_prefix, cache,
        )
        if values is not None:
            joined = "|".join(values)
            escaped = joined.replace("\\", "\\\\").replace('"', '\\"')
            _result = _UTIL_GET_CONSTRAINT_VALS_CALL_RE.sub(f'"{escaped}"', script)
            break
    _cache_write_if_marker_unchanged(
        _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE, _cache_key, (time.monotonic(), _result), _marker_at_read,
    )
    return _result
    return script

# Summary categories (§ render_filled_summary grouping) — structural
# fragment-matching against variable_name, same convention as
# _DECISION_REQUIRED_KEYS above. Generic across any ingested catalog:
# never a literal per-catalog field name (e.g. "modelSelectionSelectModel_
# viSoln" or "serviceType_astro"), only the fragment every catalog's own
# naming happens to share ("model"/"product", "service"/"billing"/"plan",
# "quantity"/"duration"). Checked in this fixed order — the first category
# whose fragments match wins, so "serviceDuration_astro" (Service Plan
# fragment "service" checked before "duration") lands in Service Plan, not
# Quantity & Duration, matching how a sales rep would actually group it.
_SUMMARY_CATEGORY_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Narrow, specific fragments only — "model" alone is too broad: both
    # catalogs prefix MANY unrelated attrs with "modelSelection*" (frequency
    # bands, keypad type, display type share APX's naming convention with
    # its actual model/product attr), so a loose "model" substring sweeps
    # those in too. These fragments target the attr that names the product
    # itself, not siblings that merely share its naming prefix.
    # "hwversion" added live-verified (2026-07-24): hWVersion_astro matched
    # none of the original fragments, so it fell into the fallback
    # "Associated Options" category — which the LLM narrator is explicitly
    # allowed to only PARTIALLY cover (never claims completeness, by
    # design, to avoid hallucinated placeholders for omitted facts). That
    # meant a customer's own explicit "change the hardware version to X"
    # could silently vanish from the "Configuration complete" summary even
    # though the JSON payload had it correctly — a real product-identifying
    # decision deserves the same always-fully-shown treatment as Base
    # Model/Product Name, not partial-coverage treatment.
    ("Product Name", ("selectmodel", "basemodel", "modelname", "productname",
                       "productselection", "producttype", "hwversion")),
    ("Service Plan", ("service", "billing", "plan", "solutiontype", "archetype")),
    ("Quantity & Duration", ("quantity", "duration", "qty")),
)
_SUMMARY_FALLBACK_CATEGORY = "Associated Options"

# Curated "business-relevant" fragments for the catch-all Associated
# Options section ONLY — Product Name/Service Plan/Quantity & Duration
# stay unaffected (already narrow by category definition). Generic
# technical/customer-facing configuration dimensions common across every
# catalog this engine has ingested (APX NEXT, SVX, DM4400, SL3500e) — a
# sales rep would actually read these out loud. Deliberately excludes
# internal/administrative fields a rule may well govern but nobody
# customer-facing cares about (validation org, order type, software
# release, provisioning-agency status, config-process markers, "agency
# has Motorola evidence solution" style CRM context) — narrower than
# "any rule fired" (product decision, confirmed live: that scope still
# left ~24 largely-administrative items in a real APX NEXT quote).
_ASSOCIATED_OPTIONS_KEY_FRAGMENTS: frozenset[str] = frozenset({
    "frequency", "band", "antenna", "battery", "carrier", "keypad",
    "housing", "channel", "hardware", "video", "mount", "training",
    "wireless", "display", "knob", "packaging", "packing", "spare",
    "endusertype", "coverage", "accidentaldamage", "rsm", "region",
    "color", "voltage", "certification", "connector", "cable", "earpiece",
    "case", "bracket", "screenprotector", "manual", "charger", "power",
})

# Public alias so ask_api can identify the catch-all category by name
# (e.g. to tighten its own narration instructions for it) without a
# private-name cross-module import.
SUMMARY_FALLBACK_CATEGORY = _SUMMARY_FALLBACK_CATEGORY

# Public alias for the real, non-catch-all category names
# (`categorized_summary_groups`'s own grouping) -- Raven review on PR
# #236 (Medium): ask_api's Mandatory-section boundary regex used to
# duplicate these as hardcoded string literals, which would silently
# under-match again if a category were ever renamed or a new one added
# here without updating that copy. Derived directly from
# _SUMMARY_CATEGORY_KEYS (the one place these names are actually
# defined) instead.
SUMMARY_CATEGORY_NAMES = tuple(category for category, _fragments in _SUMMARY_CATEGORY_KEYS)

# Live-confirmed gap (2026-08-19): in the narrowed "sales rep talking
# points" scope (rule_governed_ids supplied), `_filled_summary_triples`
# already narrows its whole item list down to exactly
# `_is_mandatory_input_attr`'s Tier A/B/C set (PR #222) -- but
# `categorized_summary_groups` still buckets any of those items that don't
# match Product Name/Service Plan/Quantity & Duration's fragments under
# the OLD catch-all name, "Associated Options", and `render_filled_summary`
# / `ask_api._cpq_summary_text` still give that category its old "ONE
# short, intentionally-partial plain-text line, free to omit any fact"
# treatment -- appropriate for a genuine grab-bag of cosmetic/accessory
# facts, but every item reaching this bucket in the narrowed scope is now,
# by construction, a confirmed Mandatory User Input fact (e.g. Software
# Release, Ultimate Destination Country) that must be fully and reliably
# listed, never partially narrated. `categorized_summary_groups` renames
# this bucket to `_SUMMARY_MANDATORY_CATEGORY` whenever `rule_governed_ids`
# is supplied; the full-detail-dump scope (rule_governed_ids=None) keeps
# the original "Associated Options" name and one-line rendering unchanged,
# since that scope is NOT narrowed to mandatory-only and can still be a
# genuine 20-50+ item catch-all.
_SUMMARY_MANDATORY_CATEGORY = "Mandatory User Input"

# Deferred for the same circular-import reason as the imports above:
# `summary_display_formatting` imports this module BACK (to reach the
# `_SUMMARY_CATEGORY_KEYS` / `_SUMMARY_FALLBACK_CATEGORY` /
# `_SUMMARY_MANDATORY_CATEGORY` tables just above through the engine
# MODULE object, so the original bare-global references — and any patch
# of them — still resolve at call time). The name is only ever resolved
# when a method runs, never at import time.
from aryx.cpq import summary_display_formatting  # noqa: E402


# Country -> standard sales-region abbreviation. Deliberately covers only
# the unambiguous majority; countries not listed here fall through to the
# normal "ask" behavior rather than guess. Two catalog-observed codes are
# intentionally NOT targeted by this map: "AP" and "EA" overlap with APAC
# for Asian countries with no reliable way to disambiguate from country
# name alone — Asian countries resolve to "APAC" (the more universal code)
# and AP/EA stay reachable only by explicit user answer. This is a business
# judgment call, not a technical limitation; revisit if wrong.
_COUNTRY_TO_REGION: dict[str, str] = {
    # North America
    "united states": "NA", "us": "NA", "usa": "NA", "u.s.": "NA", "u.s.a.": "NA",
    "canada": "NA", "mexico": "NA",
    # Latin America
    "brazil": "LA", "argentina": "LA", "chile": "LA", "colombia": "LA", "peru": "LA",
    "venezuela": "LA", "ecuador": "LA", "uruguay": "LA", "paraguay": "LA", "bolivia": "LA",
    "costa rica": "LA", "panama": "LA", "guatemala": "LA", "honduras": "LA",
    "el salvador": "LA", "nicaragua": "LA", "dominican republic": "LA", "jamaica": "LA",
    # EMEA (Europe + Africa — Middle East kept separate, see below)
    "united kingdom": "EMEA", "uk": "EMEA", "germany": "EMEA", "france": "EMEA",
    "italy": "EMEA", "spain": "EMEA", "netherlands": "EMEA", "belgium": "EMEA",
    "switzerland": "EMEA", "austria": "EMEA", "sweden": "EMEA", "norway": "EMEA",
    "denmark": "EMEA", "finland": "EMEA", "poland": "EMEA", "ireland": "EMEA",
    "portugal": "EMEA", "greece": "EMEA", "czech republic": "EMEA", "romania": "EMEA",
    "south africa": "EMEA", "nigeria": "EMEA", "kenya": "EMEA", "egypt": "EMEA",
    # Middle East
    "saudi arabia": "ME", "united arab emirates": "ME", "uae": "ME", "qatar": "ME",
    "israel": "ME", "kuwait": "ME", "bahrain": "ME", "oman": "ME", "jordan": "ME",
    # Asia Pacific
    "china": "APAC", "japan": "APAC", "india": "APAC", "australia": "APAC",
    "singapore": "APAC", "south korea": "APAC", "korea": "APAC", "indonesia": "APAC",
    "malaysia": "APAC", "thailand": "APAC", "philippines": "APAC", "vietnam": "APAC",
    "new zealand": "APAC", "taiwan": "APAC", "hong kong": "APAC",
}

# CPQ layout-noise types — exclude from configuration conversation.
_LAYOUT_TYPE_FRAGMENTS: frozenset[str] = frozenset({
    "layout", "prop", "css", "display_type", "view",
})

# Noise attr variable_name fragments — skip these entirely at load time.
# Catches TestPager, TestPager2, Error, dummy_* etc.
_NOISE_VAR_FRAGMENTS: frozenset[str] = frozenset({
    "test", "pager", "error", "dummy",
})

# Noise item_value / display_name fragments — strip these options at load time.
_NOISE_ITEM_FRAGMENTS: frozenset[str] = frozenset({
    "test", "dummy", "pager",
})

# aryx.cpq.constraint_rules's submodules import _substitute_util_get_
# constraint_vals/_condition_value_matches BACK from this module by name
# -- this line must sit after both are already defined above (the last
# being _substitute_util_get_constraint_vals, right above).
from aryx.cpq import constraint_rules  # noqa: E402
from aryx.cpq import rules_loop  # noqa: E402
from aryx.cpq import payload_build  # noqa: E402
from aryx.cpq import value_rules_load  # noqa: E402


def classify_select_type(attrs: dict[str, Any]) -> str:
    """Classify a config attr's UI/selection shape from its raw BM attrs.

    Confirmed derivation (CPQ_CASCADE_CONVERSATION_PLAN.md §4). The
    multi-select branch was exercised end-to-end for the first time against
    a real submission: the reference sample this classifier was originally
    verified against had is_array_control_attr uniformly "0", so multi-select
    coverage relied solely on that one flag — untested and, it turned out,
    incomplete. A real payload submission confirmed 13 attributes with
    is_array_control_attr=="0" were rejected by the live CPQ API expecting
    an array-set payload, including one ("Carrier Selection") whose own
    variable_name literally contains "MultiSelect". Checking
    display_type in {"6","8"} and attr_type=="1" (both confirmed live to be
    100% exclusive to the rejected attributes — zero overlap with any of
    the 83 that were accepted) closes that gap.

    Priority matters: array-control signals checked first, then the boolean
    pair, then the scalar data_type codes, else default to "single" —
    dropdowns (display_type=="3") and any other shape (free-text, etc.)
    both fall through to "single" safely.

    date/currency/integer/float — added per the real CPQ API payload
    contract (docs/CPQ_RULE_TOOL_FLOW_PLAN.md §15b/16): these were
    previously invisible to this classifier (falling through to "single"
    and serialized like a menu value) despite real attrs of each type
    existing in a real ingested catalog — confirmed via data_type samples:
    5="subscriptionStartDate"/"subscriptionEndDate" (date), 7=
    "solutionCategoryListPrice_astro" (currency/price), 3=ID/counter
    fields like "_configuration_id" (integer), 2="_BM_USER_EXCHANGE_RATE"
    (float). Checked AFTER multi/boolean (those signals are more specific
    and must win on any overlap) but BEFORE the "single" fallback.
    """
    if (str(attrs.get("is_array_control_attr", "")).strip() == "1"
            or str(attrs.get("attr_type", "")).strip() == "1"
            or str(attrs.get("display_type", "")).strip() in ("6", "8")):
        return "multi"
    if (str(attrs.get("display_type", "")).strip() == "10"
            or str(attrs.get("data_type", "")).strip() == "4"):
        return "boolean"
    data_type = str(attrs.get("data_type", "")).strip()
    if data_type == "5":
        return "date"
    if data_type == "7":
        return "currency"
    if data_type == "3":
        return "integer"
    if data_type == "2":
        return "float"
    return "single"


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
from aryx.cpq import auto_fill_run  # noqa: E402
from aryx.cpq import auto_fill_setup  # noqa: E402
from aryx.cpq import product_config_load  # noqa: E402


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

    def resolve_pending_grid_quantities(
        self, attrs: list[ConfigAttr], filled: dict[str, str],
        filled_multi: dict[str, list[str]],
        constrained_opts: dict[int, list[str]] | None = None,
        selector_vns: set[str] | None = None,
    ) -> list[ConfigAttr]:
        return grid_quantity.resolve_pending_grid_quantities(
            attrs, filled, filled_multi, constrained_opts, selector_vns,
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
    ) -> list[ConfigAttr]:
        return grid_quantity.append_pending_grid_quantities(
            self, pending, attrs, filled, filled_multi, filled_source,
            constrained_opts, selector_vns,
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


    def load_hiding_rules(self, workspace_id: int, catalog_prefix: str = "") -> list[HidingRule]:
        return hiding_rules.load_hiding_rules(self, workspace_id, catalog_prefix)

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
    ) -> tuple[list[ConfigAttr], list[str], set[str]]:
        return hiding_rules.apply_hiding_rules(
            attrs, filled, rules, bml_eval, filled_multi,
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
                return _cache_result

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
        except Exception:
            ingest_store = None
            existing_questions = {}
        _result = value_rules_load.load_value_rules(
            self, workspace_id, catalog_prefix, ingest_store, existing_questions, _t0,
        )
        _cache_write_if_marker_unchanged(_VALUE_RULES_CACHE, _cache_key, (time.monotonic(), _result), _marker_at_read)
        return _result

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

    def build_bml_evaluator(self, workspace_id: int, catalog_prefix: str = "") -> BmlEvaluator:
        return rec_con_rules.build_bml_evaluator(workspace_id, catalog_prefix)

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
    ) -> dict[int, list[str]]:
        return constraint_rules.apply_constraint_rules(
            self, attrs, rules, filled, bml_eval, filled_multi,
            workspace_id, catalog_prefix, _dt_cache, _constraint_cache,
            _signature_exclude_vns, narrowing_rec_rules,
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
    ) -> tuple[list[ConfigAttr], dict[str, str], dict[str, str], dict[int, list[str]]]:
        return rules_loop.evaluate_rules_loop(
            self, attrs, hints, filled, hiding_rules, rec_rules, con_rules,
            bml_eval, filled_source, filled_multi, dropped_multi, country,
            negated_vns, skip_always_ask, rule_conflict_order, display_order,
            workspace_id, catalog_prefix,
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
    ) -> tuple[set[str], list[ConfigAttr]]:
        return gov_sibling.exclusive_sibling_family_exclusions(
            self, attrs, filled, filled_multi, filled_source, all_attrs,
            catalog_confirmed_vns,
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
    ) -> list[ConfigAttr]:
        return gov_sibling.enforce_exclusive_sibling_families(
            self, attrs, filled, filled_multi, filled_source, display_filled,
            pending, all_attrs, catalog_confirmed_vns,
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
    ) -> tuple[dict[str, str], dict[str, str], list[ConfigAttr]]:
        return auto_fill_run.run_auto_fill(
            self, attrs, hints, already_filled, constrained_opts, filled_source,
            governed_ids, already_filled_multi, dropped_multi, rule_governed_ids,
            country, rec_rules, negated_vns, skip_always_ask, bml_eval,
            validation_rules, display_order, workspace_id, catalog_prefix,
            _dt_cache, hiding_rules, _default_fill_signatures, _signature_exclude_vns,
            grid_declined_vns,
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
    ) -> list["ConfigAttr"]:
        return auto_fill_hw_order.order_pending_hardware_before_product(
            self, pending, filled, attrs, display_order,
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
    ) -> bool:
        return mandatory_input.is_mandatory_input_attr(
            self, vn, attr, source, active_sources, required_vns,
            exclude_anchor_vns, gate_attrseq_confirmed_to_active_source,
            rule_forced_active_vns, data_table_forced_vns,
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
    ) -> dict[str, Any]:
        return payload_build.build_payload(
            self, filled, filled_source, filled_multi, attrs, hidden_vns, rules,
            display_order, product_quantity, scope_required_and_edited,
            workspace_id, catalog_prefix,
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
    ) -> list[tuple[str, str, str]]:
        return summary_display_formatting._filled_summary_triples(
            self, display_filled, attrs, rule_governed_ids, sources, display_order,
            required_vns=required_vns)

    def filled_summary_pairs(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
        sources: dict[str, str] | None = None,
        display_order: dict[str, int] | None = None,
        required_vns: frozenset[str] | None = None,
    ) -> list[tuple[str, str]]:
        return summary_display_formatting.filled_summary_pairs(
            self, display_filled, attrs, rule_governed_ids, sources, display_order,
            required_vns=required_vns)

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
    ) -> list[tuple[str, str, str]]:
        return summary_display_formatting._beautify_sectioned_rows(
            self, product_name, display_filled, attrs, filled_source,
            required_vns=required_vns)

    def beautify_text(
        self,
        product_name: str,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        filled_source: dict[str, str] | None = None,
        required_vns: frozenset[str] | None = None,
    ) -> str:
        return summary_display_formatting.beautify_text(
            self, product_name, display_filled, attrs, filled_source,
            required_vns=required_vns)

    def beautify_rows(
        self,
        product_name: str,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        filled_source: dict[str, str] | None = None,
        required_vns: frozenset[str] | None = None,
    ) -> list[dict[str, str]]:
        return summary_display_formatting.beautify_rows(
            self, product_name, display_filled, attrs, filled_source,
            required_vns=required_vns)

    def render_filled_summary(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
        sources: dict[str, str] | None = None,
        product_quantity: int | None = None,
        required_vns: frozenset[str] | None = None,
    ) -> str:
        return summary_display_formatting.render_filled_summary(
            self, display_filled, attrs, rule_governed_ids, sources,
            product_quantity=product_quantity, required_vns=required_vns)

    def categorized_summary_groups(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
        sources: dict[str, str] | None = None,
        display_order: dict[str, int] | None = None,
        product_quantity: int | None = None,
        required_vns: frozenset[str] | None = None,
    ) -> list[tuple[str, list[tuple[str, str]]]]:
        return summary_display_formatting.categorized_summary_groups(
            self, display_filled, attrs, rule_governed_ids, sources, display_order,
            product_quantity=product_quantity, required_vns=required_vns)
