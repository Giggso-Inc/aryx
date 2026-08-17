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
from typing import Any

from aryx.config import get_settings
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
from aryx.cpq.data_table_resolver import find_inconsistent_filled_pairs as dt_find_inconsistent_filled_pairs
from aryx.cpq.data_table_resolver import (
    find_inconsistent_filled_pairs_detailed as dt_find_inconsistent_filled_pairs_detailed,
)
from aryx.cpq.data_table_resolver import attr_ever_governed_for_cpq_model as dt_attr_ever_governed_for_cpq_model
from aryx.cpq.layout_source import LayoutFileSource, LocalDirLayoutFileSource
from aryx.cpq.logging_context import install_run_id_logging
from aryx.cpq.rdb import get_cpq_rdb
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


def _label_mention_span(
    label_lower: str, q_lower: str, max_dropped_leading: int = 2,
) -> "tuple[int, int] | None":
    """(start, end) of the label's first match in q_lower, or None.

    Three tiers, each stricter than the risk of the next: full-phrase
    substring, then up to `max_dropped_leading` leading words dropped
    (both preserve the label's own word ORDER), then — only if neither
    finds anything — a word-SET fallback requiring EVERY one of the
    label's own words to appear as a whole word somewhere in q_lower,
    order-independent. Factored out so callers that need WHERE the label
    was mentioned (not just whether) can scope a search to nearby text
    instead of the whole message. See `_label_mentioned`'s docstring for
    why the dropped-leading-words retry exists, and the word-set tier's
    own docstring note below for why it's safe to add.
    """
    if label_lower in q_lower:
        idx = q_lower.index(label_lower)
        return idx, idx + len(label_lower)
    words = label_lower.split()
    # Floor of 1, not 2 — a genuine 2-word label (e.g. SVX's "Select
    # Model") naturally gets its generic leading qualifier dropped just
    # like longer labels do ("change the model to X" for "Select Model"),
    # but the old floor of 2 meant a 2-word label could NEVER drop any
    # word at all (max(2, 2-2)=2, requiring the exact 2-word phrase
    # verbatim) — confirmed live: "change the model to SVX Video Remote
    # Speaker Mic TAA" fell through to "I didn't quite catch that"
    # because "select" never appears in the message. Docstring's own
    # "at least half the label's own words remain" already implies a
    # floor of 1 for a 2-word label; this was an off-by-one versus that
    # stated intent.
    min_words = max(1, len(words) - max_dropped_leading)
    if len(words) > min_words:
        for start in range(1, len(words) - min_words + 1):
            suffix = " ".join(words[start:])
            if suffix in q_lower:
                idx = q_lower.index(suffix)
                return idx, idx + len(suffix)
    # Word-set fallback (Raven-flagged, previously deferred pending a
    # false-positive review): a REORDERED phrase — "change the quantity of
    # jacket magnetic mount" states the quantity word BEFORE the mount name,
    # reversed from the label's own "...Jacket Magnetic Mount Quantity"
    # order, AND drops the generic "mounting type" prefix in the same
    # breath — never matches either tier above (which only ever drop
    # leading words WITHOUT reordering the rest), nor a naive order-blind
    # check requiring every word INCLUDING the dropped prefix (confirmed
    # still failing after c570bf4, see docs/CPQ_SESSION_2_OPEN_ISSUES.md
    # item 1). Combines both tolerances: try progressively shorter
    # leading-word-dropped SUFFIXES of the label's word list (same
    # min_words bound as the tier above), but check each suffix's words
    # as a SET (any order) instead of a contiguous phrase — the least
    # permissive candidate (full word list, order-blind) is tried first,
    # only dropping more leading words if that still doesn't match. Safe
    # to add here because this function only ever gates a coarse "is this
    # attr even relevant" pre-filter (detect_change_request still requires
    # apply_answer/the numeric-extraction span to independently confirm a
    # real value nearby before ever resolving anything) — a false-positive
    # span here costs an extra attr considered, never a wrongly-resolved
    # value. Each candidate still requires ALL its words present (not a
    # fuzzy majority) — same "match fully or bail" discipline as every
    # other matcher in this file, just order-blind within the candidate.
    for start in range(0, len(words) - min_words + 1):
        candidate = words[start:]
        spans: list[tuple[int, int]] = []
        for w in candidate:
            m = re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", q_lower)
            if not m:
                spans = []
                break
            spans.append((m.start(), m.end()))
        if spans:
            return min(s for s, _e in spans), max(e for _s, e in spans)
    return None


def _label_mentioned(label_lower: str, q_lower: str, max_dropped_leading: int = 2) -> bool:
    """True when the user's message plausibly names this attr's label.

    A full-phrase substring match is tried first (existing behavior). Some
    display labels are auto-generated compound names carrying a generic
    leading qualifier shared by many sibling attrs (confirmed live: every
    per-mount-type quantity attr on the SVX catalog is literally named
    "mounting type {Mount Name} Quantity" — six attrs, one per mount
    option). A user naturally drops that generic prefix ("change the
    jacket magnetic mount quantity to 15") since it adds nothing
    discriminating — but the exact-phrase check rejected it entirely,
    silently falling through to "I didn't quite catch that" instead of
    recognizing a clearly-named change (confirmed live). Retries with up
    to `max_dropped_leading` leading words dropped, requiring at least half
    the label's own words to remain — bounded so a short label (e.g. two
    words) can't be matched by an almost-empty remainder.
    """
    return _label_mention_span(label_lower, q_lower, max_dropped_leading) is not None


def _label_mentioned_strict(label_lower: str, q_lower: str) -> bool:
    """Exact-phrase match, or a leading-word-dropped suffix that NEVER
    degrades to a single generic shared word (e.g. "Type"/"Package").

    Live-verified gap: `_label_mentioned`'s word-set fallback tier is
    explicitly safe only as a coarse pre-filter (its own docstring: "a
    false-positive span here costs an extra attr considered, never a
    wrongly-resolved value") because `detect_change_request` always
    requires a SEPARATE value-match (apply_answer/numeric extraction)
    before actually resolving anything — a loose label match alone never
    directly causes a wrong resolution there. `detect_attr_activation`/
    `detect_attr_clear` (docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md D2/D4)
    have no such secondary check: the label match itself IS the final
    decision. Confirmed live: "add surveillance package type" — meant for
    "Surveillance Package Type" — instead matched an unrelated "Customer
    Type" attr, because dropping "Customer" leaves the single word
    "type", which trivially appears in almost any message mentioning any
    "*Type"-suffixed attr. This helper keeps the same leading-word-drop
    tolerance for 3+-word labels (dropping down to 2+ remaining words is
    still discriminating) but requires the FULL label verbatim for a
    2-word label — no single-word degradation, ever.
    """
    if label_lower in q_lower:
        return True
    words = label_lower.split()
    if len(words) < 3:
        return False  # 2-word (or shorter) labels: exact phrase only
    for start in range(1, len(words) - 1):  # always leaves >= 2 words
        suffix = " ".join(words[start:])
        if suffix in q_lower:
            return True
    return False


def _condition_value_matches(
    current_val: str, condition_value: str, operator: str = "4",
) -> bool:
    """True when current_val satisfies a single condition_attr/condition_value
    pair, under the given BM-native operator (default "4" = "=" — the
    majority code, and the only one every existing caller assumed before
    docs/CPQ_DECLARATIVE_CONDITION_OPERATOR_PLAN_2026_08_05.md).

    condition_value is sometimes a "~"-delimited OR-list (same convention
    already handled for ConstraintRule.allowed_values, e.g. "PREMIER~ADVANCED
    SOFTWARE ONLY~ESSENTIAL SOFTWARE ONLY") rather than one literal value.
    A bare case-insensitive equality check against the whole string can
    never match any single real value in that case, so any hiding/
    constraint/recommendation rule using this encoding silently never
    fires (confirmed live: this is exactly why "Hide Include Accidental
    Damage for certain Service Type" never hid includeAccidentalDamageAddDMSCoverage_astro
    despite serviceTypeAdditionalDMSCoverage_astro="PREMIER" matching one of
    its 3 listed values — docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §3).
    Single-value condition_value strings behave identically to a plain
    equality check (a 1-element split set), so this is a strict superset
    fix, not a behavior change for the common case.

    A None result from the shared _operator_hit (a numeric operator that
    couldn't parse either side) is treated as "does not match" here rather
    than propagated as "unresolved" — every caller of this scalar path
    already treats a plain False the same as "condition not met, skip,"
    so collapsing None into False changes nothing observable for the
    handful of real rows that would hit this edge case, while keeping this
    function's simple bool return type callers already depend on.
    """
    return bool(_operator_hit(current_val, [condition_value], operator))


# Ontology types ingested from an XML source are named '{SourceStem}Bm{Tag}'
# (e.g. 'ApxNextConfigBmConfigAttr', 'Sl3500EConfigBmConfigAttr') because every
# BigMachines/Oracle CPQ export element tag begins with 'bm_' — the PascalCase
# text before that marker is the ingested-source/catalog boundary.
_CATALOG_PREFIX_RE = re.compile(r"^(.*?)Bm[A-Z]")


def _catalog_prefix(type_name: str) -> str:
    """Source-derived catalog prefix of an ingested ontology type name.

    Used to keep two ingested product catalogs sharing one workspace (e.g.
    an APX Next export and an SL3500e export) from being treated as a
    single undifferentiated attribute/rule pool — see load_product_config's
    catalog scoping. Returns "" when no 'Bm<Upper>' marker is found (a
    workspace with no source-prefixed types, or a naming convention outside
    this pipeline's own PascalCase scheme) — callers must treat "" as
    "unknown catalog", never as a valid scope to filter on.
    """
    m = _CATALOG_PREFIX_RE.match(type_name or "")
    return m.group(1) if m else ""


def _strip_catalog_name_noise(norm: str) -> str:
    """Strip the internal-naming wrapper from a normalized BmPrdFamily/
    BmCatalog name so it can substring-match a natural-language sentence.

    Confirmed live: EVERY real family/catalog name across both ingested
    catalogs (77 total) ends in "bom" ("autoDGM8500E_BOM", "aPXNext_BOM",
    "mOTOTRBO_BOM", ...), and many also start with "auto" — neither
    fragment is something a customer ever says ("quote an auto DGM 8500 E
    bom radio"), so leaving them in place meant a full sentence like
    "quote DGM 8500e radios for a US customer" could never substring-match
    "autodgm8500ebom" even though the meaningful part ("dgm8500e") is right
    there in the sentence.
    """
    if norm.endswith("bom"):
        norm = norm[:-3]
    if norm.startswith("auto"):
        norm = norm[4:]
    return norm


# BigMachines variable_names are camelCase concatenations of the UI group an
# attribute lives under plus its own field name (e.g. "carrySolutionsType_apcr"
# groups under "Carry Solutions", field "Type") — the group name is what a
# customer actually says ("carry solutions"), so detect_attr_query needs the
# split words, not just the raw string, to resolve those questions.
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
_ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_GENERIC_ATTR_WORDS = frozenset({
    "type", "types", "selection", "option", "options", "all", "config",
    "attr", "value", "values",
})


def _variable_words(variable_name: str) -> list[str]:
    """CamelCase/underscore-split words from a variable_name, catalog-suffix
    and generic filler words (type/selection/option/...) dropped.

    Used only as a fallback signal in detect_attr_query — never for exact
    matching, since dropping generic words is intentionally lossy.
    """
    words: list[str] = []
    for part in variable_name.split("_"):
        if not part:
            continue
        spaced = _CAMEL_BOUNDARY_RE.sub(r"\1 \2", part)
        spaced = _ACRONYM_BOUNDARY_RE.sub(r"\1 \2", spaced)
        words.extend(w.lower() for w in spaced.split())
    return [w for w in words if len(w) > 1 and w not in _GENERIC_ATTR_WORDS]


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
# variable_names).
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
_RULE_JOIN_DATA_CACHE_TTL_SECONDS = 30.0


def _clear_rule_join_data_cache() -> None:
    """Test-isolation hook -- call from an autouse fixture to prevent this
    process-lifetime cache from leaking fake/monkeypatched rule data
    between tests that reuse the same (workspace_id, catalog_prefix) key.
    Mirrors data_table_resolver._clear_tables_cache."""
    _RULE_JOIN_DATA_CACHE.clear()


# docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_BLIND_PICK_PLAN_2026_08_10.md -- a
# small, explicit registry of data tables CONFIRMED absent from every
# ingested catalog (not attribute names -- a hiding rule anywhere, for any
# attribute, that structurally depends on one of these tables can never
# resolve, so auto_fill warns and skips rather than asking forever). Extend
# this tuple if another confirmed-missing table surfaces; never hardcode
# which attributes are affected -- that's derived generically from which
# hiding rules reference the table.
_KNOWN_MISSING_DATA_TABLES = ("UserGroupMapping",)


def _hiding_rule_needs_missing_data_table(rule: "HidingRule") -> bool:
    """True if `rule`'s script (declarative or condition-script form)
    references a data table confirmed absent from every ingested catalog --
    see `_KNOWN_MISSING_DATA_TABLES`. Such a rule can never resolve to a
    real hide/show outcome, so its target should never be silently asked
    about forever."""
    script = (rule.script or "") + (getattr(rule, "condition_script", None) or "")
    if not script:
        return False
    script_lower = script.lower()
    return any(table.lower() in script_lower for table in _KNOWN_MISSING_DATA_TABLES)


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

_DEFAULT_CPQ_MODEL_CANDIDATES: tuple[str, ...] = ("APXNEXT", "APXNEXT_BOM")


def _cpq_model_candidates(
    product_name: str, workspace_id: int | None = None, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None, base_model: str = "",
) -> tuple[str, ...]:
    """CPQModel code(s) to try for `product_name`, in priority order:
    1. The real, ingested constraint-shaped Data Table rows' own
       productSelectionProduct_all attr/val pairs
       (data_table_resolver.resolve_product_cpq_models_from_rows) --
       catalog-agnostic and fully data-driven, no per-catalog hardcoding.
       Explicit instruction (2026-08-10): a hand-authored per-catalog
       override map (formerly `_PRODUCT_TO_CPQ_MODEL` here) is not an
       acceptable substitute for real ingested data, even for a single
       catalog -- any catalog needing this fine-grained split must get it
       from its own rows, the same way every other catalog does.
    2. Otherwise, the ingested CPQModelHierarchy-shaped Data Table's real
       Product -> cpqModelName mapping, when `workspace_id` is available --
       real, catalog-wide reference data, though only family-level, not
       per-product (e.g. "APXNEXT" for both "APX NEXT MULTI" and "APX NEXT
       ENHANCED", where tier 1 above would have found the finer
       "APXNEXTENHANCED" for the latter). Both the bare family code and its
       "_BOM" variant are tried, since every real export seen so far
       ingests both under the same family.
    3. The static APXNEXT/APXNEXT_BOM fallback, unchanged, when none of the
       above applies (no workspace_id, or the product is in no ingested
       source at all) -- identical to this function's original behavior.
       A product landing here with zero real coverage is a genuine data
       gap, to be documented and flagged, never papered over with a new
       hardcoded entry for that one catalog.

    `base_model`, when supplied, appends every CPQModel code the real
    ingested Data Tables actually use for that EXACT base model (see
    data_table_resolver.discover_cpq_models_for_base_model) AFTER whichever
    of 1-3 above already matched -- never replacing the primary,
    product-derived candidates, only supplementing them. Confirmed live
    (2026-08-08): a base model can appear under a more specific variant
    code than its product name maps to (H45TGU9PW8AN's real whitelist/
    attrSequence rows are keyed to "APXNEXTXNSINGLE" even though "APX NEXT
    Single Band" maps to "APXNEXTSINGLE") -- a genuine cross-SKU
    base-model-sharing case in the source catalog. Omitting `base_model`
    (the default) keeps this function's behavior identical to before this
    parameter existed.
    """
    primary = None
    if workspace_id is not None:
        from_rows = dt_resolve_product_cpq_models_from_rows(
            product_name, workspace_id, catalog_prefix, cache,
        )
        if from_rows:
            primary = from_rows
    if primary is None and workspace_id is not None:
        family = dt_resolve_product_cpq_model_family(
            product_name, workspace_id, catalog_prefix, cache,
        )
        if family:
            primary = (family, f"{family}_BOM")
    if primary is None:
        primary = _DEFAULT_CPQ_MODEL_CANDIDATES
    if not (base_model and workspace_id is not None):
        return primary
    discovered = dt_discover_cpq_models_for_base_model(
        base_model, workspace_id, catalog_prefix, cache,
    )
    extra = tuple(cm for cm in discovered if cm not in primary)
    return primary + extra if extra else primary

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


class CpqEngine:
    """Drives guided CPQ configuration within the Ask conversation."""

    # Maximum turns before declaring complete (even if attrs remain)
    MAX_TURNS: int = 5

    # ── Intent detection ──────────────────────────────────────────────────────

    def is_cpq_question(self, question: str, reader: Any = None, workspace_id: int = 1) -> bool:
        """True when the question is a CPQ configuration / quote request.

        Two independent signals: the generic CPQ-vocabulary regex (fixed
        English words, not ingested data), OR a mention of any product
        actually ingested in this workspace (dynamic — same live-graph
        source as detect_product_mention). A question naming a product
        with no other CPQ-domain word (e.g. just "MOTOTRBO?") still routes
        to CPQ without needing that product's name hardcoded here.

        Live-confirmed gap (2026-07-27, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_
        PLAN.md): the dynamic fallback used to check ONLY
        _ingested_product_names — internal BOM family codes
        ("aSTRO25_bom", "softwareSolutions_BOM"), never the real,
        customer-facing product name ("APX Next") a customer actually
        types. "I want to order APX Next radios..." named a real,
        ingested product by its real name and STILL fell through
        entirely to the generic non-CPQ pipeline. Switched to
        ingested_product_alias_map — the same catalog-tree-derived alias
        source detect_product_mention already relies on successfully,
        which carries both the family code AND every real product/line
        name from each catalog's own bm_catalog tree.
        """
        if _CPQ_TRIGGER.search(question):
            return True
        if reader is None:
            return False
        q_norm = re.sub(r"[^a-z0-9]", "", question.lower())
        if not q_norm:
            return False
        alias_map = self.ingested_product_alias_map(reader, workspace_id)
        candidates = set(alias_map) | set(alias_map.values()) | set(
            self._ingested_product_names(reader, workspace_id)
        )
        return any(
            len(norm) >= _HINT_MIN_PHRASE_LEN and norm in q_norm
            for name in candidates
            if name
            for norm in (re.sub(r"[^a-z0-9]", "", name.lower()),)
        )

    def extract_hints(self, question: str) -> dict[str, str]:
        """Extract attribute value hints from natural language.

        Returns {attr_key_fragment: hint_value} where hint_value is matched
        word-boundary against DB option display names — no hardcoded country list.

        Contract callers must honor for `hints["country"]` specifically
        (review finding, docs/CPQ_COUNTRY_LLM_ONLY_PLAN_2026_08_13.md):
        this is a raw, UNVALIDATED regex candidate, not a confirmed country.
        When no `_COUNTRY_PREP` match in the sentence is a real, recognized
        country, this still returns the leftmost match anyway (so a caller
        that wants to reject explicitly has something to reject, rather than
        a silent absence indistinguishable from "no country mentioned at
        all"). Every caller MUST re-validate via `is_recognized_country`
        before trusting this value for anything — never assign it to
        `session.country` (or equivalent) directly. Both current callers
        (`ask_api.py`'s turn-1 hint block and `_mine_history_for_cpq_
        context`) already do this; a new caller that reads `hints.get(
        "country")` without the same check would silently reintroduce the
        exact bug class this whole plan closes.
        """
        hints: dict[str, str] = {}

        # Specific shortcut patterns — first match wins per key; more specific
        # patterns must be listed first in _HINT_PATTERNS (see ordering comment there).
        for key, pattern, value in _HINT_PATTERNS:
            if key not in hints and re.search(pattern, question, re.IGNORECASE):
                hints[key] = value

        # Generic country extraction: "customer in Australia", "located in New Zealand"
        # Captures the proper-noun after a preposition and matches it against DB display names.
        #
        # Tries every match in the sentence, not just the first -- fallback-
        # path hardening, 2026-08-13 (docs/CPQ_COUNTRY_LLM_ONLY_PLAN_2026_
        # 08_13.md review finding). `re.search` only ever returns the
        # LEFTMOST match; a bogus earlier trigger ("for APX Next" -> "AP")
        # used to shadow a real, later, correctly-stated country in the
        # same sentence ("...in the United States") because nothing ever
        # looked past the first hit. Prefers the first candidate that's a
        # real, recognized country; falls back to the plain leftmost match
        # (this method's original behavior) only when NONE of them
        # validate, so callers that intend to validate downstream
        # themselves still get a candidate to reject, not a silent None.
        if "country" not in hints:
            valid_match = None
            first_match = None
            for m in _COUNTRY_PREP.finditer(question):
                candidate = m.group(1).strip().title()
                if first_match is None:
                    first_match = candidate
                if self.is_recognized_country(candidate):
                    valid_match = candidate
                    break
            if valid_match is not None:
                hints["country"] = valid_match
            elif first_match is not None:
                hints["country"] = first_match

        # Region hints (abbreviations)
        if "region" not in hints:
            for pattern, value in _REGION_PATTERNS:
                if re.search(pattern, question, re.IGNORECASE):
                    hints["region"] = value
                    break

        return hints

    def extract_catalog_hints(
        self, question: str, attrs: list["ConfigAttr"],
    ) -> tuple[dict[str, str], set[str]]:
        """Extract hints by matching real menu-option text against the question.

        Complements extract_hints()'s fixed pattern list (hwversion/country
        concepts only now — product detection moved to the dynamic
        _ingested_product_names lookup) — confirmed live, a fixed list
        silently drops anything outside the concepts it names.

        Rather than adding a hardcoded pattern per concept, this scans every
        visible, single/boolean attr's real options and checks whether that
        option's own text (item_value or display_name) appears verbatim in
        the question, punctuation/casing stripped. Returns
        (hints, negated_vns):
          - hints — {variable_name: item_value}, keyed by the exact
            variable_name (unlike extract_hints()'s fragment keys) since the
            match already identifies the specific attribute, no fuzzy
            fragment lookup needed.
          - negated_vns — variable_names whose concept appeared in the
            question immediately after a negation cue ("exclude", "no",
            "without", ...) rather than as a positive selection. Callers
            must not silently auto-fill these via blind first-by-order —
            confirmed live: "exclude any multikey capability" produced zero
            positive hint for multikeyType_astro (see single-word rule
            below), so it fell through to auto_fill's ungoverned fallback
            and landed on the literal opposite, "MULTIKEY", even though a
            "No Multikey" option exists.
            When a negated phrase's real catalog also spells out the
            negation as its own option — "no{phrase}" (or its plural-flip)
            found as a key in `candidates`, same-attr or a sibling — that
            option IS asserted into `hints` too (not just recorded in
            negated_vns), since passive suppression alone doesn't stop an
            attr's own unconditional default_value from applying (confirmed
            live: beltClipType_astro kept its "2.0 INCH / 5.08 CM
            (STANDARD)" default after "exclude any... carry solutions" even
            though "NO CARRY SOLUTION" is a real option on that very attr).
            Same len(owners)==1 never-guess guard as the rest of this method.

        Never guesses (D2), several ways:
          - If the same option text is real for two or more different attrs,
            neither is hinted. A tie-break using a distinguishing word from
            the attr's own variable_name was tried and REJECTED after
            confirmed false positives: "software" in "baseline release
            software" incorrectly anchored softwareBundlesBundleType_astro
            (self-referential — the word only overlapped because it's also
            in that attr's own name, unrelated to what the customer meant),
            and "SIM" incorrectly anchored selectSecondarySIMCard_astro over
            the intended sIMCardSelection_astro (an artifact of how the
            latter's leading lowercase "s" splits under camelCase parsing).
            A heuristic that's already produced two confirmed wrong guesses
            in normal testing isn't safe to keep — better to leave both
            unresolved than guess wrong.
          - A candidate phrase must be multi-word (its real item_value or
            display_name contains a space) OR contain a digit/slash to be
            trusted as a positive hint, even with a single owner. A lone
            single word is too easily a coincidence (e.g. "SOFTWARE" is a
            real, sole-owner option for relatedServicesType_astro, but
            appearing inside "baseline release software" has nothing to do
            with related services). Multi-word phrases ("NO MULTIKEY",
            "BASELINE RELEASE") aren't at meaningful risk of this — a
            specific multi-word phrase appearing verbatim is not the kind of
            thing that happens by accident. Neither is a punctuation-joined
            code like "ATT/FIRSTNET" (confirmed live: excluding it as a bare
            "single word" dropped the hint for wirelessCarrier_astro even
            though the customer wrote "AT&T/FirstNet" verbatim) — English
            prose essentially never contains a digit or an internal slash by
            accident, unlike a common dictionary word.
          - A positive-looking match is discarded (never turned into a
            hint) if a negation cue sits in the ~40 chars right before it in
            the real question text — "exclude ... carry solutions" must not
            select "Carry Solutions" just because that literal phrase
            appears in the sentence.

        Longer/more specific option text is tried first so a short phrase
        can't shadow a longer, more specific one that also appears in the
        question. Options coded by a generic boolean item_value (YES/NO) are
        excluded even when their display_name is elaborate (e.g.
        item_value="YES", display_name="Baseline Release") — matching those
        via display text alone is exactly the ambiguous-duplicate case D2
        exists to avoid; the real, specifically-named option should win.
        """
        q_norm, q_index_map = _normalize_for_hint_with_map(question)
        q_lower = question.lower()
        candidates: dict[str, list[tuple[str, str]]] = {}
        # Every real option's normalized text and its owning attr(s) — used
        # for negation-suppression below regardless of word count or
        # ambiguity (suppressing a blind fallback is low-risk: worst case is
        # an extra question asked, not a wrong value silently picked, so
        # it's fine to be broader here than the positive-hint match below).
        all_owners: dict[str, set[str]] = {}
        for attr in attrs:
            if attr.hidden:
                continue
            for opt in attr.options:
                if opt.item_value.strip().lower() in self._BOOLEAN_DISPLAY_VALUES:
                    continue
                _texts = [(opt.item_value, False), (opt.display_name, False)]
                _suffix = _parenthetical_suffix(opt.display_name)
                if _suffix and _suffix not in (opt.item_value, opt.display_name):
                    _texts.append((_suffix, True))
                for text, _is_suffix in _texts:
                    stripped = text.strip()
                    is_code = any(c.isdigit() for c in stripped) or "/" in stripped
                    norm = _normalize_for_hint(text)
                    if len(norm) < _HINT_MIN_PHRASE_LEN:
                        continue
                    # Multi-select attrs still register here (needed so a
                    # negated category on a multi-select attr, e.g.
                    # accessoriesSolutionSet_astro's "CARRY SOLUTIONS", can be
                    # detected as negated below and used to look up a
                    # sibling's "NO <X>" option) but are excluded from
                    # `candidates` just below — never a positive-hint target,
                    # unchanged from before.
                    all_owners.setdefault(norm, set()).add(attr.variable_name)
                    if attr.select_type == "multi":
                        continue
                    if len(stripped.split()) < 2 and not is_code:
                        # Single-word dictionary-style options are never
                        # trusted as a positive hint (see docstring) — still
                        # recorded above for negation-suppression, just not
                        # added to `candidates` below.
                        continue
                    if _is_suffix and not is_code:
                        # A parenthetical suffix is a much shorter, more
                        # generic-sounding fragment than the full option
                        # text it's plucked from ("Best Value", "Recommended
                        # for most users") — multi-word alone isn't enough
                        # distinctiveness evidence the way it is for a
                        # full, catalog-specific item_value/display_name
                        # (raven review, PR follow-up). Only trust it when
                        # it also looks like a technical/distinguishing
                        # code (contains a digit or slash) — "4G LTE+5G"
                        # qualifies, ordinary marketing prose does not.
                        continue
                    candidates.setdefault(norm, []).append(
                        (attr.variable_name, opt.item_value))

        hints: dict[str, str] = {}
        for phrase in sorted(candidates, key=len, reverse=True):
            idx = _find_plural_tolerant(q_norm, phrase)
            if idx == -1:
                continue
            entries = candidates[phrase]
            owners = {vn for vn, _iv in entries}
            if len(owners) > 1:
                continue  # real option for 2+ different attrs — never guess
            if len(set(entries)) > 1:
                # Same attr, but 2+ genuinely different real values share
                # this exact phrase (e.g. two hardware-version options both
                # display a "(4G LTE+5G)" variant suffix on siblings like
                # "APX NEXT" and "APX NEXT XE") — this widens once
                # _parenthetical_suffix starts contributing candidate text,
                # since a shared variant suffix is common across sibling
                # products. Never guess which one the customer meant.
                continue
            vn, item_value = entries[0]
            if vn in hints:
                continue  # a longer, more specific phrase already matched this attr
            if _is_negated_before(q_lower, q_index_map[idx]):
                continue  # "exclude ... <phrase>" — not a selection
            hints[vn] = item_value

        # docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md row
        # 17: a deterministic sanity check, not an LLM call — negating an
        # attr's ONLY real (non-boolean) option is contradictory (there's
        # nothing left to fall back to), so it must never silently
        # suppress the whole attribute the way a genuine "exclude X, use
        # Y instead" negation among 2+ real options correctly does.
        # Cheap: reuses `attrs` already scoped to this call, no new rule
        # evaluation or threading needed.
        _attr_by_vn = {a.variable_name: a for a in attrs}

        def _has_only_one_real_option(vn: str) -> bool:
            attr = _attr_by_vn.get(vn)
            if attr is None:
                return False
            real_opts = [
                o for o in attr.options
                if o.item_value.strip().lower() not in self._BOOLEAN_DISPLAY_VALUES
            ]
            return len(real_opts) <= 1

        negated_vns: set[str] = set()
        for phrase, owners in all_owners.items():
            idx = _find_plural_tolerant(q_norm, phrase)
            if idx == -1:
                continue
            if not _is_negated_before(q_lower, q_index_map[idx]):
                continue
            negated_vns.update(vn for vn in owners if not _has_only_one_real_option(vn))
            # Passive suppression (negated_vns) only stops auto_fill's blind
            # first-by-order fallback — it does nothing about an attr whose
            # own default_value applies unconditionally regardless of
            # negation. Confirmed live: after "exclude any... carry
            # solutions", beltClipType_astro's declarative default "2.0 INCH
            # / 5.08 CM (STANDARD)" still applied (auto_fill's default-value
            # step has no negation check at all), and multikeyType_astro was
            # simply left unfilled after "exclude any multikey capability"
            # even though both attrs have their own literal "NO <X>" option
            # in the real catalog. When the option text spells the negation
            # out explicitly — on the SAME attr (multikeyType_astro:
            # "MULTIKEY" negated -> "NO MULTIKEY" also on multikeyType_astro)
            # or a SIBLING one in this catalog (accessoriesSolutionSet_astro's
            # "CARRY SOLUTIONS" negated -> beltClipType_astro's "NO CARRY
            # SOLUTION") — assert that option directly instead of leaving the
            # field to a default or an unfilled gap. Reuses `candidates`
            # (already built above from this same catalog-scoped `attrs`,
            # multi-word/code trust filter already applied) — no extra scan
            # of the catalog, and the same len(owners)==1 guard as every
            # other match in this method: never guess which attr "NO X"
            # belongs to if more than one real option has it.
            no_key = f"no{phrase}"
            no_key_variant = f"no{phrase[:-1]}" if phrase.endswith("s") else f"no{phrase}s"
            for key in (no_key, no_key_variant):
                no_entries = candidates.get(key)
                if not no_entries:
                    continue
                no_owners = {vn for vn, _iv in no_entries}
                if len(no_owners) != 1:
                    continue  # real "NO X" option on 2+ attrs — never guess
                target_vn, target_value = no_entries[0]
                if target_vn not in hints:
                    hints[target_vn] = target_value
                break
        return hints, negated_vns

    def _build_flag_keyword_index(
        self, attrs: list["ConfigAttr"], workspace_id: int, catalog_prefix: str,
    ) -> dict[str, tuple[str, str]]:
        """{normalized_keyword: (variable_name, literal_value)} for
        option-less attrs whose value a real BML script actually checks.

        Confirmed live this closes a real gap extract_catalog_hints cannot:
        attrs like customerType have no menu options at all, so there is no
        curated option text to match a phrase like "federal customer"
        against — yet a real hiding rule's script literally checks
        customerType=="FEDERAL". The keyword itself is read directly off
        the script's own comparison (via extract_literal_comparisons), not
        derived from the attribute's name — customerType's own name
        ("customer", "type") contains nothing resembling "federal", so
        camelCase-splitting the attribute name would find nothing useful
        here; the useful signal only exists in the script body.

        Never guesses (D2), two ways:
          - A candidate value is dropped if 2+ different option-less
            fields' scripts compare against the same normalized text —
            same "ambiguous → don't guess" principle as extract_catalog_hints.
          - A candidate value is ALSO dropped if it collides with any real,
            curated menu option's text anywhere in the catalog (confirmed
            live: "FEDERAL" is itself a real option on
            systemEnhancementFeatureType_astro, plus a substring of several
            others) — this fuzzy, script-derived mechanism must never
            disagree with extract_catalog_hints about which attribute a
            word belongs to.

        Cached per (workspace_id, catalog_prefix) — this depends only on
        the catalog's own static rules/attrs, not on conversation state, so
        it is built once per catalog per process lifetime rather than
        re-scanning every script on every turn.
        """
        cache_key = (workspace_id, catalog_prefix)
        cached = _FLAG_KEYWORD_INDEX_CACHE.get(cache_key)
        if cached is not None:
            return cached

        by_vn = {a.variable_name: a for a in attrs}
        option_less = {
            vn for vn, a in by_vn.items() if not a.options and not a.hidden
        }

        scripts = get_cpq_rdb().fetch_function_scripts(workspace_id, catalog_prefix)
        candidates: dict[str, set[str]] = {}
        literal_by_norm_and_var: dict[tuple[str, str], str] = {}
        for script in scripts.values():
            if not script:
                continue
            for var, value in extract_literal_comparisons(script):
                if var not in option_less:
                    continue
                norm = _normalize_for_hint(value)
                if len(norm) < _HINT_MIN_PHRASE_LEN:
                    continue
                candidates.setdefault(norm, set()).add(var)
                literal_by_norm_and_var[(norm, var)] = value

        index: dict[str, tuple[str, str]] = {
            norm: (next(iter(vns)), literal_by_norm_and_var[(norm, next(iter(vns)))])
            for norm, vns in candidates.items() if len(vns) == 1
        }

        for a in attrs:
            if a.hidden or a.select_type == "multi":
                continue
            for opt in a.options:
                for text in (opt.item_value, opt.display_name):
                    index.pop(_normalize_for_hint(text), None)

        _FLAG_KEYWORD_INDEX_CACHE[cache_key] = index
        return index

    def extract_flag_hints(
        self, question: str, attrs: list["ConfigAttr"],
        workspace_id: int, catalog_prefix: str,
    ) -> dict[str, str]:
        """{variable_name: literal_value} for option-less, BML-referenced
        fields whose expected literal value appears (un-negated) in the
        question. See _build_flag_keyword_index for the safety guards.

        Negation drops the match entirely rather than inventing an
        "opposite" literal — unlike a real YES/NO option pair, there is no
        second value the script defines for "not federal", so the safe
        behavior is to leave the field unfilled (same as any other
        genuinely unresolvable case), not guess one.
        """
        index = self._build_flag_keyword_index(attrs, workspace_id, catalog_prefix)
        if not index:
            return {}
        q_norm, q_index_map = _normalize_for_hint_with_map(question)
        q_lower = question.lower()
        hints: dict[str, str] = {}
        for norm_value, (vn, literal_value) in index.items():
            idx = _find_plural_tolerant(q_norm, norm_value)
            if idx == -1:
                continue
            if _is_negated_before(q_lower, q_index_map[idx]):
                continue
            hints[vn] = literal_value
        return hints

    def find_unresolvable_context_attrs(
        self,
        attrs: list["ConfigAttr"],
        filled: dict[str, str],
        workspace_id: int,
        catalog_prefix: str,
        rec_rules: list["RecommendationRule"],
        con_rules: list["ConstraintRule"],
    ) -> list[dict[str, Any]]:
        """Surface every option-less, script-referenced, still-unfilled attr
        that NO rule in this catalog can ever set (the customerType-class
        gap — generalized from a single confirmed instance, docs/
        APX_Next_RootCause_And_Fix_Report).

        Never guesses a value (D2) — this only reports WHICH attrs are
        structurally unresolvable and what literal values scripts elsewhere
        compare them to, so a caller (a standalone payload-construction
        workflow, or a live turn) can decide what to do, instead of the
        gap being invisible the way it was for customerType. Distinct from
        an attr a recommendation rule targets but simply hasn't been run
        yet — call evaluate_recommendation_rules/evaluate_rules_loop
        first; only what remains missing after that pass is a genuine gap
        this method is meant to catch.

        Catalog-agnostic: uses only the same generic option-less/script-
        literal-comparison scan _build_flag_keyword_index already performs,
        and the same rule-target check any catalog's rec/con rules go
        through — no attribute or rule name is hardcoded.

        Returns a list of {variable_name, literal_values_referenced,
        num_referencing_scripts}, one entry per genuinely unresolvable,
        still-missing attr — empty when nothing needs attention.
        """
        by_vn = {a.variable_name: a for a in attrs}
        option_less = {
            vn for vn, a in by_vn.items() if not a.options and not a.hidden
        }
        if not option_less:
            return []

        settable_by_rule: set[int] = set()
        for r in (*rec_rules, *con_rules):
            target_id = getattr(r, "target_attr_id", None)
            if target_id:
                settable_by_rule.add(target_id)

        scripts = get_cpq_rdb().fetch_function_scripts(workspace_id, catalog_prefix)
        referenced: dict[str, set[str]] = {}
        referencing_count: dict[str, int] = {}
        for script in scripts.values():
            if not script:
                continue
            seen_this_script: set[str] = set()
            for var, value in extract_literal_comparisons(script):
                if var not in option_less:
                    continue
                referenced.setdefault(var, set()).add(value)
                seen_this_script.add(var)
            for var in seen_this_script:
                referencing_count[var] = referencing_count.get(var, 0) + 1

        result: list[dict[str, Any]] = []
        for vn, values in referenced.items():
            if filled.get(vn):
                continue
            attr = by_vn.get(vn)
            eid = attr.entity_id if attr else None
            sid = attr.source_id if attr else None
            if eid in settable_by_rule or (sid is not None and sid in settable_by_rule):
                continue  # a rule CAN fill this — not this method's concern
            result.append({
                "variable_name": vn,
                "literal_values_referenced": sorted(v for v in values if v.strip()),
                "num_referencing_scripts": referencing_count.get(vn, 0),
            })
        result.sort(key=lambda r: -r["num_referencing_scripts"])
        return result

    def _ingested_product_names(self, reader: Any, workspace_id: int) -> list[str]:
        """Real product/family display names for every catalog currently
        ingested in this workspace — read live from the graph, no hardcoded
        product list.

        Mirrors the BmPrdFamily/BmCatalog lookup _scope_to_catalog already
        does to resolve a hint back to one catalog (see its docstring); here
        we go the other direction — enumerate every ingested catalog's own
        name so a mention of ANY currently-ingested product can be
        recognised, not just ones anticipated when this code was written.
        Returns [] (never raises) when the reader can't answer distinct_types
        or no family/catalog entity is found — callers must treat that as
        "no dynamic candidates available", not an error.
        """
        try:
            all_type_names = reader.distinct_types()
        except AttributeError:
            return []
        # "" (no source-stem prefix) is a legitimate catalog scope too — a
        # workspace with only one ingested catalog may have unprefixed type
        # names (_scope_to_catalog treats this the same way: len(prefixes)<=1
        # returns that one prefix, even when it's ""). Excluding "" here
        # would silently skip the single-catalog case entirely.
        prefixes = sorted({_catalog_prefix(t) for t in all_type_names})
        names: list[str] = []
        for prefix in prefixes:
            family_ents: list[dict] = []
            for family_type in (f"{prefix}BmPrdFamily", f"{prefix}BmCatalog"):
                family_ents.extend(
                    reader.find_entities(ontology_type=family_type, limit=50))
                if family_ents:
                    break
            if not family_ents:
                continue
            family_pg = self._batch_fetch([e["id"] for e in family_ents], workspace_id)
            for fent in family_ents:
                fname = str(
                    family_pg.get(fent["id"], {}).get("name") or fent.get("name") or ""
                ).strip()
                if fname:
                    names.append(fname)
        return names

    def ingested_product_alias_map(self, reader: Any, workspace_id: int) -> dict[str, str]:
        """{alias → owning family name} for every catalog in this workspace.

        _ingested_product_names only surfaces the BmPrdFamily names (e.g.
        "aSTRO25_bom", "videoSolutions_BOM") — internal BOM identifiers a
        client rarely says. But each export also carries its OWN bm_catalog
        tree (family → product line → product), and those names ARE what
        clients say: "APX™ NEXT"/"aPXNext_BOM" lives only in the APX
        export, "SVX Video Remote Speaker Microphone"/"vX650_BOM" only in
        the SVX one (confirmed live, workspace 14). Unlike the flat
        productSelectionProduct_all menu — the identical full-portfolio
        list in every catalog, useless for discrimination — the tree is
        catalog-scoped, so a product/line name maps unambiguously to its
        family.

        Every alias (the family name itself, plus each bm_catalog entity's
        variable name and display name) maps to the family name detection
        should resolve to — the same value _scope_to_catalog matches back
        to one catalog when the config loads. An alias appearing under
        MORE THAN ONE family (a shared tree entry) is dropped entirely:
        ambiguous, never guess. Returns {} (never raises) when the reader
        can't answer — same contract as _ingested_product_names.
        """
        try:
            all_type_names = reader.distinct_types()
        except AttributeError:
            return {}
        prefixes = sorted({_catalog_prefix(t) for t in all_type_names})
        alias_map: dict[str, str] = {}
        ambiguous: set[str] = set()
        for prefix in prefixes:
            fam_ents = reader.find_entities(
                ontology_type=f"{prefix}BmPrdFamily", limit=50)
            cat_ents = reader.find_entities(
                ontology_type=f"{prefix}BmCatalog", limit=200)
            if not fam_ents and not cat_ents:
                continue
            pg = self._batch_fetch(
                [e["id"] for e in fam_ents + cat_ents], workspace_id)
            family_name = ""
            for fent in fam_ents:
                family_name = str(
                    pg.get(fent["id"], {}).get("name") or fent.get("name") or ""
                ).strip()
                if family_name:
                    break
            if not family_name:
                # No family entity in this export — the tree's root catalog
                # node (parent_id=-1) is the closest thing to a family name.
                for cent in cat_ents:
                    a = pg.get(cent["id"], {})
                    if str(a.get("parent_id") or "").strip() == "-1":
                        family_name = str(
                            a.get("name") or cent.get("name") or "").strip()
                        if family_name:
                            break
            if not family_name:
                continue
            aliases = {family_name}
            for cent in cat_ents:
                a = pg.get(cent["id"], {})
                for key in ("name", "bm_name"):
                    nm = str(a.get(key) or "").strip()
                    if nm:
                        aliases.add(nm)
            for nm in aliases:
                existing = alias_map.get(nm)
                if existing is not None and existing != family_name:
                    ambiguous.add(nm)
                else:
                    alias_map[nm] = family_name
        for nm in ambiguous:
            alias_map.pop(nm, None)
        return alias_map

    def single_model_variable_name(
        self, reader: Any, workspace_id: int, catalog_prefix: str,
    ) -> str:
        """The catalog's model variable name — ONLY when its own bm_catalog
        tree has exactly one model leaf; "" otherwise (never guess).

        Recreates the punch-in model context BigMachines injects at runtime
        (the `_bm_model_*` attrs a user enters the configurator through) —
        data that never exists in an XML export. When the tree makes the
        model unambiguous (SVX: family videoSolutions_BOM → line mobile_BOM
        → single leaf vX650_BOM), Aryx can seed it; when several leaves
        exist (APX Next: aPXNext_BOM AND aPXN70_BOM), returns "" and the
        model context stays unfilled — the quote's identity travels in the
        product selection there instead (Issue 11,
        docs/CPQ_PRODUCT_SWITCH_ISSUE.md). A leaf = a bm_catalog node whose
        native id is never another node's parent_id.
        """
        if not catalog_prefix:
            return ""
        cat_ents = reader.find_entities(
            ontology_type=f"{catalog_prefix}BmCatalog", limit=200)
        if not cat_ents:
            return ""
        pg = self._batch_fetch([e["id"] for e in cat_ents], workspace_id)
        nodes: list[tuple[str, str, str]] = []  # (native_id, parent_id, name)
        for cent in cat_ents:
            a = pg.get(cent["id"], {})
            native = str(a.get("id") or "").strip()
            parent = str(a.get("parent_id") or "").strip()
            name = str(a.get("name") or cent.get("name") or "").strip()
            if native and name:
                nodes.append((native, parent, name))
        parent_ids = {p for _n, p, _nm in nodes if p and p != "-1"}
        leaves = [nm for native, _p, nm in nodes if native not in parent_ids]
        return leaves[0] if len(leaves) == 1 else ""

    def model_variable_candidates(
        self, reader: Any, workspace_id: int, catalog_prefix: str,
    ) -> list[str]:
        """Companion to single_model_variable_name: the full list of leaf
        model variable names when the tree has 2+ (the ambiguous case that
        function deliberately returns "" for, rather than guessing).

        Amendment 10 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): a
        catalog like CommandCentral Aware has several model leaves
        (commandCentralAware2024_BOM, commandCentralAware2026_BOM,
        commandCentralDEMS_BOM, ...) under one family — with no single
        unambiguous leaf, _bm_model_variable_name was never seeded at
        all, and no question ever asked which one was meant; the turn
        fell through to unrelated "Product" attrs instead, which don't
        represent this identity in this catalog's data at all.

        Returns [] when there are 0 or exactly 1 leaves (that case is
        single_model_variable_name's job), else the distinct, sorted leaf
        names for the caller to present as a disambiguation choice.
        """
        if not catalog_prefix:
            return []
        cat_ents = reader.find_entities(
            ontology_type=f"{catalog_prefix}BmCatalog", limit=200)
        if not cat_ents:
            return []
        pg = self._batch_fetch([e["id"] for e in cat_ents], workspace_id)
        nodes: list[tuple[str, str, str]] = []
        for cent in cat_ents:
            a = pg.get(cent["id"], {})
            native = str(a.get("id") or "").strip()
            parent = str(a.get("parent_id") or "").strip()
            name = str(a.get("name") or cent.get("name") or "").strip()
            if native and name:
                nodes.append((native, parent, name))
        parent_ids = {p for _n, p, _nm in nodes if p and p != "-1"}
        leaves = sorted({nm for native, _p, nm in nodes if native not in parent_ids})
        return leaves if len(leaves) >= 2 else []

    def detect_product_mention(
        self, question: str, hints: dict[str, str],
        reader: Any = None, workspace_id: int = 1,
        alias_map: dict[str, str] | None = None,
    ) -> str:
        """Best-effort product display label from NL text, or "" if none found.

        Dynamic — no hardcoded product list. Matches against the REAL
        product/family names of every catalog actually ingested into this
        workspace (via _ingested_product_names), so a newly-ingested product
        line is recognised immediately without a code change. Falls back to
        the NL-hint-derived "product" key, then "" (Step 1's normal
        anchor-prompt path takes over when nothing resolves).

        D1 (CPQ_CASCADE_CONVERSATION_PLAN.md §2): the anchor gate is now
        sequential (product, then country) rather than a single-shot block
        requiring product+line+country together — hwVersion (formerly the
        "product line" anchor) resolves through the normal rule cascade
        instead, like any other dependent variable.

        Candidates are tried LONGEST-first (mirrors extract_catalog_hints'
        "longer/more specific option text is tried first so a short phrase
        can't shadow a longer, more specific one"): a workspace can ingest
        both a generic family name ("APX NEXT") and a specific variant
        ("APX NEXT XE") as separate catalog entities, in no guaranteed
        order from the graph — without this ordering, a customer asking
        about "APX NEXT XE" could silently anchor to the generic "APX NEXT"
        depending on which entity the graph happened to return first
        (regression caught in review: this is the same "variant must win
        over generic" guarantee the old hardcoded _PRODUCT_PATTERNS table
        enforced via explicit list ordering).

        Falls back to a FUZZY substring match (deterministic, no LLM) when
        no candidate is an exact substring of the question — catches a
        partial/incomplete mention ("SL 3500" missing the trailing "e") or
        a typo, cases the exact check silently misses, which previously
        left a mid-session product switch undetected with no signal
        anything was wrong. Reuses aryx.resolution.classical.string_score
        (SequenceMatcher-based), the same deterministic scoring already
        used for entity-resolution matching elsewhere in this codebase —
        no new dependency, no network call, no non-determinism. Slides a
        window the length of each candidate's normalized name across the
        normalized question and keeps the best score seen; only a name at
        least _HINT_MIN_PHRASE_LEN chars long is ever considered, same
        guard used elsewhere in this module to stop short names from
        spuriously matching unrelated text. This is purely a widened
        DETECTION signal — the caller (ask_api.py's confirm_switch gate)
        still requires explicit confirmation before anything is reset, so
        a fuzzy false positive costs one extra yes/no turn, never a silent
        wrong-product answer or data loss.

        Matching runs over ingested_product_alias_map's ALIASES (family
        names PLUS each catalog's own bm_catalog tree names — "APX™ NEXT",
        "vX650_BOM", ...) and resolves the matched alias to its owning
        FAMILY name (see that method's docstring for why the tree, not the
        flat product menu, is the only catalog-discriminating signal).
        Both XMLs carry the identical flat product list, so a raw product
        mention can never pick a catalog — the tree names can (confirmed
        live: "Quote APX Next Enhanced radios" matched nothing when only
        the two family identifiers were candidates).

        alias_map — pre-fetched ingested_product_alias_map result. Pass it
        when the caller also needs it for suggest_product_candidates in
        the same turn (review finding P2: the common no-match path loaded
        the same inventory twice through graph+RDB queries). When None,
        self-fetches as before.
        """
        q_norm = re.sub(r"[^a-z0-9]", "", question.lower())
        if alias_map is None and reader is not None and q_norm:
            alias_map = self.ingested_product_alias_map(reader, workspace_id)
        if alias_map and q_norm:
            ordered = sorted(
                ((name, re.sub(r"[^a-z0-9]", "", name.lower())) for name in alias_map),
                key=lambda t: len(t[1]), reverse=True,
            )
            for name, name_norm in ordered:
                if name_norm and name_norm in q_norm:
                    return alias_map[name]
            scored = self._fuzzy_score_candidates(
                q_norm, ordered, question_tokens=self._question_tokens(question),
            )
            if scored and scored[0][1] >= _PRODUCT_FUZZY_MATCH_THRESHOLD:
                return alias_map[scored[0][0]]
        return next((v for k, v in hints.items() if "product" in k), "")

    @staticmethod
    def _question_tokens(question: str) -> frozenset[str]:
        """Individual normalized word tokens from `question`, filtered to
        those long enough to carry brand-abbreviation signal (see
        `_ABBR_PREFIX_MIN_LEN`). Distinct from q_norm, which glues the
        whole question into one string for substring/sliding-window
        checks — this stays word-separated so a short mention ("APX")
        isn't diluted by neighboring filler ("quote", "qty", "10").
        """
        return frozenset(
            t for t in re.findall(r"[a-z0-9]+", (question or "").lower())
            if len(t) >= _ABBR_PREFIX_MIN_LEN
        )

    @staticmethod
    def _fuzzy_score_candidates(
        q_norm: str, ordered: list[tuple[str, str]],
        question_tokens: frozenset[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Best deterministic fuzzy score of each (name, name_norm) pair
        against q_norm — a sliding window the length of the candidate's
        normalized name, scored via aryx.resolution.classical.string_score.
        Shared by detect_product_mention's confirm-worthy match and
        suggest_product_candidates' lower "maybe" band, so both use the
        exact same scoring, just different thresholds. Sorted descending;
        names shorter than _HINT_MIN_PHRASE_LEN are never scored (same
        guard used elsewhere to stop short names from spuriously matching
        unrelated text).

        `question_tokens` (see `_question_tokens`) adds a second, word-level
        signal on top of the whole-string sliding window: any token that is
        a genuine prefix of a candidate's normalized name bumps that
        candidate's score into the "suggest" band via `_ABBR_PREFIX_SCORE`,
        even when the whole-sentence window carries no useful signal for a
        short/vague mention. Purely additive (`max`) — never lowers a score
        the sliding window already found on its own.
        """
        scored: list[tuple[str, float]] = []
        for name, name_norm in ordered:
            if len(name_norm) < _HINT_MIN_PHRASE_LEN:
                continue
            window = len(name_norm)
            span = max(1, len(q_norm) - window + 1)
            best = 0.0
            for i in range(span):
                best = max(best, string_score(name_norm, q_norm[i:i + window]))
            if question_tokens and any(
                name_norm.startswith(tok) for tok in question_tokens
            ):
                best = max(best, _ABBR_PREFIX_SCORE)
            scored.append((name, best))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored

    def suggest_product_candidates(
        self, question: str, reader: Any, workspace_id: int,
        exclude: str = "", limit: int = 5,
        alias_map: dict[str, str] | None = None,
    ) -> list[str]:
        """Up to `limit` real ingested product names whose fuzzy similarity
        to `question` falls in the "maybe, not confident" band — at or
        above _PRODUCT_FUZZY_SUGGEST_THRESHOLD but below
        detect_product_mention's own confirm-worthy _PRODUCT_FUZZY_MATCH_THRESHOLD.

        Used when a mid-conversation message seems to be attempting to
        name a product but doesn't clearly match anything — instead of
        silently ignoring it (today's behavior when detect_product_mention
        returns ""), the caller can offer these as "did you mean one of
        these?" candidates rather than leaving the customer's real intent
        unrecognised with no signal anything was ambiguous.

        Returns [] when nothing scores in that band — either
        detect_product_mention already found a confident match, or the
        message truly has no product-name signal at all (the common case
        for an ordinary configuration answer).

        Scores the same alias inventory detect_product_mention matches
        against (family names + catalog-tree names), then maps each
        in-band alias back to its owning FAMILY name — suggestions are
        always family names, because that's the value a confirmed switch
        anchors the session to. Aliases whose family is `exclude` (the
        session's current product) are skipped; duplicate families from
        multiple in-band aliases are collapsed keeping best-score order.

        alias_map — pre-fetched ingested_product_alias_map result; see
        detect_product_mention. This method runs on EVERY ordinary answer
        turn (the no-match path), so re-fetching here doubled the
        graph+RDB round-trips per turn (review finding P2). When None,
        self-fetches as before.
        """
        q_norm = re.sub(r"[^a-z0-9]", "", question.lower())
        if not q_norm:
            return []
        if alias_map is None:
            if reader is None:
                return []
            alias_map = self.ingested_product_alias_map(reader, workspace_id)
        exclude_norm = exclude.strip().lower()
        ordered = [
            (name, re.sub(r"[^a-z0-9]", "", name.lower()))
            for name, family in alias_map.items()
            if family.strip().lower() != exclude_norm
        ]
        scored = self._fuzzy_score_candidates(
            q_norm, ordered, question_tokens=self._question_tokens(question),
        )
        suggestions: list[str] = []
        for name, score in scored:
            if not (_PRODUCT_FUZZY_SUGGEST_THRESHOLD <= score < _PRODUCT_FUZZY_MATCH_THRESHOLD):
                continue
            family = alias_map[name]
            if family not in suggestions:
                suggestions.append(family)
            if len(suggestions) >= limit:
                break
        return suggestions

    def check_country_availability(
        self,
        attrs: list[ConfigAttr],
        con_rules: list["ConstraintRule"],
        filled: dict[str, str],
        bml_eval: BmlEvaluator,
    ) -> bool:
        """Is the country in `filled` compatible with this catalog's
        product line (variable_name "productSelectionProduct_all" —
        confirmed via real data to be a shared, tenant-wide convention
        present under the IDENTICAL native id in every ingested catalog
        checked so far, same category as ultimateDestinationCountry
        itself, not specific to any one product)?

        Reuses apply_constraint_rules — the SAME machinery already used
        for every other constraint in this engine, handling declarative
        AND script-backed rules identically — rather than reading rule
        conditions directly. Confirmed against real data that the actual
        constraint on the product-selector conditioned on country/region
        is BML-script-based (referencing region/customerType internally),
        not a simple declarative country -> allowed-list lookup; 5 of the
        6 constraint rules targeting this attribute in APX Next are
        script-form. A hand-rolled declarative-only check would silently
        miss all of them and always report "available."

        Returns True whenever there's no active constraint on the
        product-selector at all — no rule means no stated restriction,
        the same default used throughout this engine. Returns False only
        when a constraint actually fires and narrows the product-selector
        down to zero allowed values.

        Deliberately does NOT attempt to enumerate which OTHER countries
        would be valid — doing so would mean re-running this same
        constraint (script evaluation, possibly LLM-backed) once per
        candidate country, up to ~249 times for a single check. Not
        computable cheaply; the caller asks the client for a different
        country instead of listing alternatives.
        """
        selector = next(
            (a for a in attrs if a.variable_name == "productSelectionProduct_all"), None,
        )
        if selector is None:
            return True
        constrained = self.apply_constraint_rules(attrs, con_rules, filled, bml_eval)
        allowed = constrained.get(selector.entity_id)
        if allowed is None:
            return True
        return bool(allowed)

    # ── PostgreSQL attribute fetch ────────────────────────────────────────────

    def _batch_fetch(
        self, entity_ids: list[int], workspace_id: int,
    ) -> dict[int, dict[str, Any]]:
        """Batch-fetch entity attribute JSON from the RDB (dialect-agnostic)."""
        return get_cpq_rdb().fetch_entity_attributes(entity_ids, workspace_id)

    # ── Graph loading ─────────────────────────────────────────────────────────

    def _is_layout_noise(self, ontology_type: str) -> bool:
        t = (ontology_type or "").lower()
        return any(frag in t for frag in _LAYOUT_TYPE_FRAGMENTS)

    def _match_family_name(
        self, reader: Any, workspace_id: int, prefix: str, hint_norm: str,
    ) -> str | None:
        """The real BmPrdFamily/BmCatalog entity name under `prefix` whose
        normalized text substring-matches hint_norm, or None. Shared by
        _scope_to_catalog (family-only scoping) and resolve_product_hint
        (family + product-option scoping) — the family/catalog-name check
        is identical in both; only what else gets checked afterward differs.

        Requires the SHORTER side of the containment check to be at least
        _HINT_MIN_PHRASE_LEN chars — confirmed live that without this, a
        bare 2-char anchor reply like "US" (a country, not a product)
        spuriously matched inside "pCRBusinessLightDevices_bom" (the "us"
        in "business"), resolving a country name to a random catalog.
        """
        family_ents: list[dict] = []
        for family_type in (f"{prefix}BmPrdFamily", f"{prefix}BmCatalog"):
            # High limit, not a handful: a single product family can carry
            # dozens of BmCatalog entities (e.g. a MOTOTRBO/PCR family
            # spanning 70+ individual radio-model catalogs) — the model
            # actually matching product_hint (e.g. "autoSL3500E_BOM") can
            # sort anywhere in an unordered graph result, so a small limit
            # risks silently missing it and falling back to "ambiguous".
            family_ents.extend(
                reader.find_entities(ontology_type=family_type, limit=2000))
        if not family_ents:
            return None
        family_pg = self._batch_fetch([e["id"] for e in family_ents], workspace_id)
        for fent in family_ents:
            fname = str(
                family_pg.get(fent["id"], {}).get("name") or fent.get("name") or ""
            )
            fname_norm = _strip_catalog_name_noise(
                re.sub(r"[^a-z0-9]", "", fname.lower())
            )
            if not fname_norm:
                continue
            shorter_len = min(len(fname_norm), len(hint_norm))
            if shorter_len < _HINT_MIN_PHRASE_LEN:
                continue
            if fname_norm in hint_norm or hint_norm in fname_norm:
                return fname
        return None

    def _scope_to_catalog(
        self, reader: Any, workspace_id: int, attr_types: list[str], product_hint: str,
    ) -> tuple[list[str], str]:
        """Restrict attr_types to the single catalog the requested product belongs to.

        A workspace can hold more than one ingested XML source at once (e.g. an
        APX Next export and an SL3500e export side by side) — without this,
        every product request pulls attributes/rules from ALL of them, producing
        a hybrid config that mixes incompatible product lines (confirmed live:
        asking for "APX Next" returned attrs from both '_astro' and '_apcr'
        catalogs simultaneously).

        Resolution: group attr_types by their source-derived _catalog_prefix,
        look up each prefix's BmPrdFamily/BmCatalog entity name (via
        _match_family_name), and match product_hint against those names.
        Falls back to returning ALL types unscoped (the pre-fix behavior)
        whenever there's only one catalog to begin with, or the hint can't
        be uniquely matched to one — this must never silently return zero
        attrs for an unresolved hint.

        Returns (scoped_attr_types, resolved_catalog_prefix) — the prefix is
        "" when scoping did not narrow to exactly one catalog, and callers
        (rule loaders) must treat that the same as "no catalog filter".
        """
        prefixes = {_catalog_prefix(t) for t in attr_types}
        if "" in prefixes:
            # "" means _catalog_prefix found no PascalCase marker — either a
            # genuinely unprefixed catalog (confirmed live: CommandCentral
            # Aware, ingested via the generic doc_discovery pipeline, emits
            # bare 'BmConfigAttr'/'BmPrdFamily' with no distinguishing
            # prefix at all) or unrecognized noise. Keep "" as a real,
            # matchable catalog only when it resolves to an actual
            # BmPrdFamily/BmCatalog entity; otherwise it's noise and must
            # still be discarded, never treated as a valid scope.
            has_real_family = bool(
                reader.find_entities(ontology_type="BmPrdFamily", limit=1)
                or reader.find_entities(ontology_type="BmCatalog", limit=1)
            )
            if not has_real_family:
                prefixes.discard("")
        if len(prefixes) <= 1:
            return attr_types, (next(iter(prefixes)) if prefixes else "")

        hint_norm = re.sub(r"[^a-z0-9]", "", (product_hint or "").lower())
        if not hint_norm:
            return attr_types, ""

        matched_prefixes = {
            prefix for prefix in prefixes
            if self._match_family_name(reader, workspace_id, prefix, hint_norm)
        }

        if len(matched_prefixes) == 1:
            chosen = next(iter(matched_prefixes))
            scoped = [t for t in attr_types if _catalog_prefix(t) == chosen]
            if scoped:
                return scoped, chosen

        # Family-name matching failed (or was ambiguous) — customers name the
        # real product/model ("SVX Video Remote Speaker Microphone"), not the
        # internal BOM export codename ("videoSolutions_BOM"), which never
        # substring-matches. productSelectionProduct_all's option list (the
        # OTHER fallback used elsewhere) doesn't help either — it's a flat,
        # identical-across-every-catalog portfolio list, not catalog-scoped
        # data. ingested_product_alias_map's bm_catalog TREE names ARE
        # catalog-scoped (confirmed live: "SVX Video Remote Speaker
        # Microphone"/"vX650_BOM" only exist in the SVX export) — reuse that
        # same signal detect_product_mention already relies on successfully,
        # instead of re-deriving a weaker one here (confirmed live this was
        # the actual reason catalog_prefix resolution — and everything
        # downstream that depends on it, e.g. resolve_always_ask_skips —
        # behaved inconsistently for SVX).
        if not matched_prefixes:
            alias_map = self.ingested_product_alias_map(reader, workspace_id)
            ordered = sorted(
                ((name, re.sub(r"[^a-z0-9]", "", name.lower())) for name in alias_map),
                key=lambda t: len(t[1]), reverse=True,
            )
            matched_family: str | None = None
            for name, name_norm in ordered:
                if name_norm and min(len(name_norm), len(hint_norm)) >= _HINT_MIN_PHRASE_LEN \
                        and name_norm in hint_norm:
                    matched_family = alias_map[name]
                    break
            if matched_family:
                # matched_family is the owning FAMILY name (e.g.
                # "videoSolutions_BOM") — resolve it back to a prefix by
                # exact equality against each candidate's own BmPrdFamily
                # entity name, not another substring search.
                for prefix in prefixes:
                    fam_ents = reader.find_entities(
                        ontology_type=f"{prefix}BmPrdFamily", limit=5)
                    fam_pg = self._batch_fetch([e["id"] for e in fam_ents], workspace_id)
                    fname = next(
                        (str(fam_pg.get(e["id"], {}).get("name") or e.get("name") or "").strip()
                         for e in fam_ents), "")
                    if fname == matched_family:
                        scoped = [t for t in attr_types if _catalog_prefix(t) == prefix]
                        if scoped:
                            return scoped, prefix

        logger.warning(
            "cpq: could not uniquely scope product_hint=%r to one catalog among "
            "prefixes=%s — loading ALL catalogs (cross-catalog mixing risk)",
            product_hint, sorted(prefixes),
        )
        return attr_types, ""

    # Fallback structural signal for _fetch_product_option_list when no attr
    # is literally named "productSelectionProduct_all" — see that method's
    # docstring. Matches the common BM naming convention for a product-line
    # variant selector without hardcoding one catalog's exact field name.
    _PRODUCT_FIELD_FALLBACK_RE = re.compile(r"product", re.IGNORECASE)
    _PRODUCT_FIELD_FALLBACK_HINT_RE = re.compile(r"select|line", re.IGNORECASE)

    def _fetch_product_option_list(
        self, reader: Any, workspace_id: int, prefix: str,
    ) -> list[tuple[str, str]]:
        """(item_value, display_name) options for one catalog's customer-
        facing product-name field.

        Confirmed live: both currently-ingested catalogs (ApxNextConfig,
        Sl3500EConfig) name this field productSelectionProduct_all — this is
        the field product-LINE VARIANTS (e.g. "APX NEXT Enhanced", "DGM
        8500e") actually live in, never in BmPrdFamily/BmCatalog names
        (confirmed: "APX NEXT Enhanced" matches no real family/catalog name
        in this catalog at all).

        A THIRD catalog using a different field name for the same concept
        is not hardcoded around: when no attr is literally named
        productSelectionProduct_all, falls back to a structural signal —
        any attr whose variable_name matches both "product" and
        ("select"|"line") (case-insensitive), same naming convention as
        both known catalogs' own field. Multiple candidates pick the one
        with the MOST real menu options (product-variant selectors are
        high-cardinality dropdowns by nature — confirmed 325 real options
        on this catalog's own field), a deterministic tie-break within an
        already-narrowed, name-matched candidate set rather than a blind
        guess across the whole catalog.

        Only called for infrequent product-hint resolution (first message,
        anchor-answer validation) — not the hot per-turn path — so a full
        per-catalog attr scan here (mirroring load_product_config's own
        entity+Postgres fetch) is an acceptable, one-off cost.
        """
        try:
            attr_ents = reader.find_entities(
                ontology_type=f"{prefix}BmConfigAttr", limit=500)
        except Exception:
            return []
        if not attr_ents:
            return []
        attr_pg = self._batch_fetch([e["id"] for e in attr_ents], workspace_id)
        target_id = None
        fallback_ids: list[int] = []
        for ent in attr_ents:
            pg = attr_pg.get(ent["id"], {})
            vn = str(
                pg.get("variable_name") or pg.get("name") or ent.get("name") or ""
            ).strip()
            if vn == "productSelectionProduct_all":
                target_id = ent["id"]
                break
            if (self._PRODUCT_FIELD_FALLBACK_RE.search(vn)
                    and self._PRODUCT_FIELD_FALLBACK_HINT_RE.search(vn)):
                fallback_ids.append(ent["id"])
        if target_id is None and fallback_ids:
            # One batched call instead of one reader.neighbors() per
            # candidate — was up to hundreds of round-trips on catalogs with
            # many attrs matching the fallback regex (mirrors the
            # neighbors_batch() fix already applied to load_product_config's
            # own attribute-neighbor loop a few hundred lines below).
            try:
                neighbors_by_id = reader.neighbors_batch(fallback_ids)
            except Exception:
                neighbors_by_id = {}
            target_id = max(
                fallback_ids, key=lambda eid: len(neighbors_by_id.get(eid, []))
            )
        if target_id is None:
            return []
        try:
            neighbors = reader.neighbors(target_id)
        except Exception:
            return []
        menu_ids = [
            n["id"] for n in neighbors
            if "menuitem" in (n.get("type") or "").lower().replace("_", "")
        ]
        if not menu_ids:
            return []
        menu_pg = self._batch_fetch(menu_ids, workspace_id)
        options: list[tuple[str, str]] = []
        for mid in menu_ids:
            ma = menu_pg.get(mid, {})
            iv = str(ma.get("item_value") or "").strip()
            dt = str(ma.get("item_text") or ma.get("name") or iv).strip()
            if iv:
                options.append((iv, dt))
        return options

    def resolve_product_hint(
        self, reader: Any, workspace_id: int, hint_text: str,
    ) -> tuple[str, str] | None:
        """Resolve free-text to (catalog_prefix, canonical_display_name)
        using only real ingested data — no hardcoded product-name list.

        Replaces reliance on _PRODUCT_PATTERNS' fixed regex list, which
        confirmed-live never recognizes products outside its hardcoded set
        (e.g. "DGM 8500e" — a real, ingested product this method resolves
        correctly with zero code changes, since DGM/MOTOTRBO models are
        genuinely present as BmCatalog entities and productSelectionProduct_all
        options inside the Sl3500EConfig ingestion).

        Two passes, in priority order — NOT merged into one combined check:
          1. BmPrdFamily/BmCatalog entity names (_match_family_name), across
             ALL catalogs. This is genuinely catalog-specific data (an
             internal BOM export code), so a unique match here is trusted
             immediately without even looking at pass 2.
          2. Only if pass 1 matched nothing anywhere: each catalog's
             productSelectionProduct_all option list. Confirmed live this
             field is a SHARED master list duplicated near-identically
             across every ingested catalog (not real per-catalog data), so
             it is deliberately the lower-priority, fallback signal — if
             pass 1 had been checked per-catalog and merged with pass 2
             additively instead, a real match in pass 1 (e.g. "DGM 8500e"
             uniquely matching Sl3500EConfig's BmCatalog entity) would get
             incorrectly reported as ambiguous the moment pass 2 also
             matched the same shared list entry in a second, unrelated
             catalog — confirmed live this exact false ambiguity happened
             before this two-pass ordering was added.

        Returns None if neither pass uniquely resolves to exactly one
        catalog — callers must ask rather than guess (D2), same principle
        as _scope_to_catalog's own "ambiguous → don't pick" behavior.
        """
        hint_norm = _normalize_for_hint(hint_text)
        if not hint_norm:
            return None

        try:
            all_type_names = reader.distinct_types()
        except AttributeError:
            all_type_names = sorted({
                e.get("type") or "" for e in reader.find_entities(limit=1000)
            })
        prefixes = sorted({
            _catalog_prefix(t) for t in all_type_names if _catalog_prefix(t)
        })
        if not prefixes:
            return None

        family_matches: dict[str, str] = {}
        for prefix in prefixes:
            fname = self._match_family_name(reader, workspace_id, prefix, hint_norm)
            if fname:
                family_matches[prefix] = fname
        if len(family_matches) == 1:
            prefix, name = next(iter(family_matches.items()))
            return prefix, name
        if family_matches:
            return None  # ambiguous at the trustworthy signal — never fall through

        option_matches: dict[str, str] = {}
        for prefix in prefixes:
            for item_value, display_name in self._fetch_product_option_list(
                reader, workspace_id, prefix,
            ):
                for text in (item_value, display_name):
                    stripped = text.strip()
                    is_code = any(c.isdigit() for c in stripped) or "/" in stripped
                    if len(stripped.split()) < 2 and not is_code:
                        continue  # same single-word guard as extract_catalog_hints
                    norm = _normalize_for_hint(text)
                    if (
                        min(len(norm), len(hint_norm)) >= _HINT_MIN_PHRASE_LEN
                        and (norm in hint_norm or hint_norm in norm)
                    ):
                        option_matches[prefix] = display_name or item_value
                        break
                if prefix in option_matches:
                    break

        if len(option_matches) == 1:
            prefix, name = next(iter(option_matches.items()))
            return prefix, name
        return None

    def list_ingested_families(
        self, reader: Any, workspace_id: int,
    ) -> list[str]:
        """Real family/catalog display names, one per ingested catalog
        prefix — for building a dynamic "what product family?" prompt
        instead of a hardcoded example string that goes stale the moment a
        new catalog is ingested."""
        try:
            all_type_names = reader.distinct_types()
        except AttributeError:
            all_type_names = sorted({
                e.get("type") or "" for e in reader.find_entities(limit=1000)
            })
        prefixes = sorted({
            _catalog_prefix(t) for t in all_type_names if _catalog_prefix(t)
        })
        names: list[str] = []
        for prefix in prefixes:
            family_ents = reader.find_entities(
                ontology_type=f"{prefix}BmPrdFamily", limit=5)
            if not family_ents:
                continue
            family_pg = self._batch_fetch([e["id"] for e in family_ents], workspace_id)
            fname = str(
                family_pg.get(family_ents[0]["id"], {}).get("name")
                or family_ents[0].get("name") or ""
            ).strip()
            if fname:
                names.append(fname)
        return names

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
        # Step 1 — find config attr entities. XML ingestion prefixes type names
        # per source (e.g. ApxNextConfigBmConfigAttr, Sl3500EDummyConfigBmConfigAttr),
        # so discover the actual type name(s) first via DISTINCT types, then fetch
        # by exact type. Sampling find_entities(limit=1000) instead is unreliable:
        # on a 46k-entity graph the arbitrary first page can contain zero
        # ConfigAttr rows even though hundreds exist.
        def _norm(t: str) -> str:
            return (t or "").lower().replace("_", "")

        try:
            all_type_names = reader.distinct_types()
        except AttributeError:  # reader without distinct_types — legacy fallback
            all_type_names = sorted({
                e.get("type") or "" for e in reader.find_entities(limit=1000)
            })
        attr_types = [t for t in all_type_names if _norm(t).endswith("configattr")]
        if not attr_types:
            attr_types = [
                t for t in all_type_names
                if "configattr" in _norm(t) and not self._is_layout_noise(t)
            ]

        # Scope to the single catalog the requested product belongs to —
        # a workspace may hold more than one ingested product catalog at
        # once (see _scope_to_catalog docstring). resolved_catalog_prefix
        # is stamped onto every ConfigAttr below so rule loaders can apply
        # the same scoping without needing a second graph round-trip.
        attr_types, resolved_catalog_prefix = self._scope_to_catalog(
            reader, workspace_id, attr_types, product_hint,
        )

        attr_ents: list[dict] = []
        for attr_type in attr_types:
            # Paginate past find_entities' capped limit — confirmed live
            # (2026-07-27, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md
            # Amendment 13): a single limit=500 call silently truncated
            # CommandCentral Aware's 906 real BmConfigAttr rows down to
            # 324 loaded, dropping hundreds of attrs including
            # hiddenHidingRuleMasterStringForCommandCentral_swSoln — the
            # exact gotcha find_entities' own docstring already documents
            # for BmMenuItem (SL3500e's >2000 rows), just never applied
            # here. Loop until a short page confirms there's nothing left.
            offset = 0
            while True:
                page = reader.find_entities(ontology_type=attr_type, limit=500, offset=offset)
                attr_ents.extend(page)
                if len(page) < 500:
                    break
                offset += 500

        if not attr_ents:
            logger.info("cpq: no bm_config_attr entities found in graph "
                        "(workspace_id=%s, types_seen=%d)",
                        workspace_id, len(all_type_names))
            return [], product_hint

        # Step 2 — batch fetch PostgreSQL attributes
        attr_ids = [e["id"] for e in attr_ents]
        attr_pg = self._batch_fetch(attr_ids, workspace_id)

        # Step 3 — collect ALL menu item IDs from FalkorDB in one graph pass,
        # then batch-fetch all PostgreSQL data in a single query.
        # Previously this loop was capped at [:150], causing attrs beyond that
        # position (e.g. hWVersion_astro at position 236) to silently get no
        # options. Two-pass approach eliminates both the cap and the N+1 pattern.
        neighbor_map: dict[int, list[int]] = {}  # attr_entity_id → [menu_entity_ids]
        all_menu_ids: list[int] = []
        # docs/CPQ_LOAD_PRODUCT_CONFIG_NEIGHBORS_N_PLUS_1_PERFORMANCE_PLAN_
        # 2026_08_10.md -- one FalkorDB round trip for every attr's neighbors
        # instead of one per attr (confirmed live: 498 calls, 6.85s, run
        # fresh from 4 uncached call sites every turn). AttributeError
        # fallback keeps OracleGraphReader and every test double lacking
        # neighbors_batch working unchanged, same pattern as distinct_types
        # above.
        try:
            _neighbors_batch = reader.neighbors_batch([e["id"] for e in attr_ents])
        except AttributeError:
            _neighbors_batch = None
        for ent in attr_ents:
            eid = ent["id"]
            try:
                neighbors = (
                    _neighbors_batch.get(eid, []) if _neighbors_batch is not None
                    else reader.neighbors(eid)
                )
                # reader.neighbors() has no catalog awareness — for attrs whose
                # native id is reused across catalogs (e.g. productSelectionProduct_all,
                # confirmed live to have separate BmMenuItem sets per catalog under
                # the same native id) this returns menu items from EVERY catalog in
                # the workspace, not just the one resolved above. Scope by the same
                # resolved_catalog_prefix already used for attr_types. Skip the
                # filter when resolved_catalog_prefix is "" — per _scope_to_catalog,
                # that means scoping didn't narrow to one catalog, so no filter
                # should be applied (same convention as the attr-type scoping above).
                menu_ids = [
                    n["id"] for n in neighbors
                    if "menuitem" in (n.get("type") or "").lower().replace("_", "")
                    and (
                        not resolved_catalog_prefix
                        or _catalog_prefix(n.get("type") or "") == resolved_catalog_prefix
                    )
                ]
                if menu_ids:
                    neighbor_map[eid] = menu_ids
                    all_menu_ids.extend(menu_ids)
            except Exception:
                logger.debug("cpq: neighbor fetch failed for attr %d", eid, exc_info=True)

        # Step 3b — FK fallback for attrs with a real Postgres bm_config_attr
        # row but NO graph edge to their menu items (confirmed live: SVX's
        # modelSelectionSelectModel_viSoln has 4 real bm_menu_item rows in
        # Postgres, correctly FK'd via bm_config_attr_id, but zero FalkorDB
        # neighbors — a graph-ingestion gap, not a rule-driven/constrained
        # menu). Detected purely structurally (menu_type present + empty
        # neighbor_map entry), never by attr/catalog name, so it self-heals
        # for any future XML with the same ingestion gap.
        orphan_eids = [
            e["id"] for e in attr_ents
            if e["id"] not in neighbor_map
            and str(attr_pg.get(e["id"], {}).get("menu_type") or "") == "1"
        ]
        if orphan_eids:
            # A real BM native id can legitimately own more than one graph
            # entity_id (confirmed live: SL3500e ingested
            # ultimateDestinationCountry twice under distinct entity_ids
            # 188302/212455, both real id 39426962) — a plain 1:1 dict here
            # would silently keep only the last-iterated entity_id and drop
            # the other's options entirely. Map real id -> ALL owning
            # entity_ids so every duplicate gets the same menu options.
            orphan_real_ids: dict[str, list[int]] = {}
            for eid in orphan_eids:
                rid = attr_pg.get(eid, {}).get("id")
                if rid is not None:
                    orphan_real_ids.setdefault(str(rid), []).append(eid)
            if orphan_real_ids:
                menu_types = [
                    t for t in all_type_names
                    if _norm(t).endswith("menuitem")
                    and (not resolved_catalog_prefix
                         or _catalog_prefix(t) == resolved_catalog_prefix)
                ]
                # Paginate past find_entities' per-call cap (ARYX_GRAPH_QUERY_LIMIT,
                # confirmed live at 2000) — SL3500e alone ships >2000 bm_menu_item
                # rows, so a single capped call silently truncated to whichever
                # rows the graph happened to return first, missing e.g.
                # ultimateDestinationCountry's country list entirely.
                fk_menu_ents: list[dict] = []
                page_size = 2000
                for mt in menu_types:
                    offset = 0
                    while True:
                        page = reader.find_entities(
                            ontology_type=mt, limit=page_size, offset=offset)
                        fk_menu_ents.extend(page)
                        if len(page) < page_size:
                            break
                        offset += page_size
                fk_menu_pg = self._batch_fetch(
                    [m["id"] for m in fk_menu_ents], workspace_id)
                for mid, mdata in fk_menu_pg.items():
                    owner_eids = orphan_real_ids.get(str(mdata.get("bm_config_attr_id") or ""))
                    if not owner_eids:
                        continue
                    for owner_eid in owner_eids:
                        neighbor_map.setdefault(owner_eid, []).append(mid)
                    all_menu_ids.append(mid)

        # Step 3c (override redirection) — BigMachines' bm_config_att_override
        # construct lets one catalog replace/extend a SHARED base attribute's
        # own menu list with a catalog-specific one (same native attribute_id,
        # different graph entity, different — and often more complete —
        # bm_menu_item set). Nothing in this pipeline read this construct
        # before (confirmed live: zero references to it anywhere in the
        # codebase) — every attr's options came ONLY from its own base
        # entity's graph neighbors, so an override-only option was silently
        # invisible everywhere (the answer prompt, apply_answer matching,
        # every constraint rule's allowed-value intersection).
        #
        # Live-confirmed bug (2026-07-28): productSelectionProduct_all's base
        # entity (native id 39427019) neighbors a stale bm_menu_item set that
        # repeats "APX NEXT ENHANCED" many times but never carries "APX NEXT
        # XE 4G LTE PLUS 5G" — while a bm_config_att_override entity for the
        # SAME native attribute_id neighbors the complete, catalog-correct
        # list containing both. A real constraint rule (Hardware-Version-
        # keyed) correctly narrowed to both values, but the numbered prompt
        # only ever showed the one the base entity's own menu list happened
        # to carry.
        #
        # Purely additive and structural: detected via ontology_type suffix
        # (no hardcoded catalog/attr names) and merged (never replaces) into
        # the base entity's own neighbor list — `seen_opts`' (item_value,
        # display_name) dedup below already absorbs any item repeated in
        # both sets, so this only ever ADDS options a base-only read would
        # have missed, never removes one a real customer answer already
        # relies on.
        override_types = [
            t for t in all_type_names
            if _norm(t).endswith("configattoverride")
            and (not resolved_catalog_prefix
                 or _catalog_prefix(t) == resolved_catalog_prefix)
        ]
        if override_types:
            override_ents: list[dict] = []
            for ot in override_types:
                offset = 0
                while True:
                    page = reader.find_entities(ontology_type=ot, limit=500, offset=offset)
                    override_ents.extend(page)
                    if len(page) < 500:
                        break
                    offset += 500
            if override_ents:
                override_pg = self._batch_fetch(
                    [e["id"] for e in override_ents], workspace_id)
                # base attr's own native id -> owning entity_id(s), same
                # "native id can own 2+ entity_ids" reality the orphan
                # FK-fallback above already accounts for.
                base_eids_by_native_id: dict[str, list[int]] = {}
                for e in attr_ents:
                    rid = attr_pg.get(e["id"], {}).get("id")
                    if rid is not None:
                        base_eids_by_native_id.setdefault(str(rid), []).append(e["id"])
                for oe in override_ents:
                    oeid = oe["id"]
                    target_native_id = str(override_pg.get(oeid, {}).get("attribute_id") or "")
                    owner_eids = base_eids_by_native_id.get(target_native_id)
                    if not owner_eids:
                        continue
                    try:
                        override_neighbors = reader.neighbors(oeid)
                    except Exception:
                        logger.debug(
                            "cpq: neighbor fetch failed for override attr %d",
                            oeid, exc_info=True)
                        continue
                    override_menu_ids = [
                        n["id"] for n in override_neighbors
                        if "menuitem" in (n.get("type") or "").lower().replace("_", "")
                        and (not resolved_catalog_prefix
                             or _catalog_prefix(n.get("type") or "") == resolved_catalog_prefix)
                    ]
                    if not override_menu_ids:
                        continue
                    for owner_eid in owner_eids:
                        # Prepended, not appended: the override is BM's
                        # authoritative, catalog-specific replacement for
                        # this attr's menu — when the same item_value exists
                        # in both (confirmed live: "APX NEXT ENHANCED" on the
                        # base list displays as "APX NEXT Enhanced", but the
                        # override's own copy of that same item_value
                        # displays as "APX NEXT (4G LTE+5G)"), the override's
                        # display must win, not silently coexist as a
                        # second, differently-labeled entry for an identical
                        # code. Processing override entries first lets the
                        # item_value-keyed dedup below keep only the first
                        # (override) occurrence.
                        neighbor_map[owner_eid] = override_menu_ids + neighbor_map.get(owner_eid, [])
                    all_menu_ids.extend(override_menu_ids)

        # Single batch fetch for all menu items across all attrs
        all_menu_pg = self._batch_fetch(all_menu_ids, workspace_id) if all_menu_ids else {}

        menu_by_attr: dict[int, list[MenuOption]] = {}
        for eid, menu_ids in neighbor_map.items():
            opts: list[MenuOption] = []
            # item_values already added for this attr, keyed by item_value
            # ALONE (2026-07-28: widened from an (item_value, display_name)
            # pair) — company-level/global BM attrs (e.g. _BM_USER_CURRENCY,
            # _BM_USER_LANGUAGE, _BM_USER_NUMBER_FORMAT) share one native id
            # across every ingested catalog from the same BM tenant, and
            # reader.neighbors() has no catalog-prefix scoping of its own, so
            # a workspace holding 2+ catalogs can surface the same option
            # more than once for these specific attrs (confirmed live: "US
            # Dollar" offered twice). See docs/CPQ_MULTI_CATALOG_ASK_FLOW_BUGS_PLAN.md
            # Bug 1 — this is the safe, minimal backstop; product-specific
            # attrs never hit this since their menu items are never
            # re-exported verbatim across catalogs.
            #
            # Widened to item_value-only (2026-07-28, override redirection
            # above): a bm_config_att_override's menu item can share the SAME
            # item_value as one already on the base attr's own menu, with a
            # DIFFERENT display_name — confirmed live: "APX NEXT ENHANCED"
            # displays as "APX NEXT Enhanced" on the base list but as
            # "APX NEXT (4G LTE+5G)" on the override's own copy. The old
            # (item_value, display_name) key let both survive as two
            # differently-labeled entries for what is really one identical
            # code — a customer-facing duplicate. Override entries are
            # placed first in `menu_ids` above specifically so this dedup
            # keeps the override's (authoritative) display when both exist.
            seen_item_values: set[str] = set()
            for mid in menu_ids:
                ma = all_menu_pg.get(mid, {})
                # Always use item_value (API code), item_text for display
                iv = str(ma.get("item_value") or "").strip()
                dt = str(ma.get("item_text") or ma.get("name") or iv).strip()
                order = int(ma.get("order_number") or ma.get("order") or 999)
                if iv:
                    iv_lo = iv.lower()
                    dt_lo = dt.lower()
                    if any(f in iv_lo for f in _NOISE_ITEM_FRAGMENTS):
                        continue
                    if any(f in dt_lo for f in _NOISE_ITEM_FRAGMENTS):
                        continue
                    if iv_lo in seen_item_values:
                        continue
                    seen_item_values.add(iv_lo)
                    opts.append(MenuOption(item_value=iv, display_name=dt, order=order))
            opts.sort(key=lambda x: x.order)
            menu_by_attr[eid] = opts

        # Step 3c — array-set membership (docs/CPQ_ARRAY_SET_PAYLOAD_PLAN.md):
        # bm_config_attr_set/bm_config_attr_set_assoc define BigMachines'
        # composite "array set" construct (a driver/control attr + ordered
        # member columns, e.g. Mounting Type's selector+quantity pair) —
        # confirmed real, previously completely unread by this pipeline.
        # role_by_attr_id/order_by_attr_id/wrapper_key_by_attr_id are keyed
        # by the BM-native attribute id (source_id), the same id every
        # other rule/set join in this method already cross-references by.
        array_sets = get_cpq_rdb().fetch_attr_set_assoc(workspace_id, resolved_catalog_prefix)
        array_set_id_by_attr_id: dict[int, int] = {}
        role_by_attr_id: dict[int, str] = {}
        order_by_attr_id: dict[int, int] = {}
        wrapper_key_by_attr_id: dict[int, str] = {}
        for set_id, sdef in array_sets.items():
            driver_id = sdef["driver_attr_id"]
            array_set_id_by_attr_id[driver_id] = set_id
            role_by_attr_id[driver_id] = "driver"
            wrapper_key_by_attr_id[driver_id] = f"_set{sdef['variable_name']}"
            for member_id, order in sdef["members"]:
                array_set_id_by_attr_id[member_id] = set_id
                role_by_attr_id[member_id] = "member"
                order_by_attr_id[member_id] = order

        # Rule-target ids — computed once here so Step 4's hidden/no-default
        # drop below can exempt attrs that are dynamically populated by a
        # rule action rather than a static default (Amendment 13,
        # docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md). Live-confirmed gap:
        # hiddenHidingRuleMasterStringForCommandCentral_swSoln (hidden=1,
        # empty default_value, but the ACTION-target of a
        # util.getConstraintVals-style recommendation rule) was being
        # dropped before rule evaluation ever ran, so it could never be
        # filled — and every downstream script checking it (e.g. "Hide 'of
        # Video Streaming Devices' if No value available for command and
        # control") always saw it blank, permanently defeating that
        # catalog's own visibility mechanism. Rule references use the
        # BM-native id (pg["id"]/attribute_id/bm_config_rule_id), not the
        # aryx entity_id — both are checked below since either can appear
        # as a rule action's target.
        try:
            _rule_actions_by_rule = self._load_rule_join_data(
                workspace_id, resolved_catalog_prefix)[2]
            rule_target_ids: set[int] = {
                aid for acts in _rule_actions_by_rule.values() for aid, *_rest in acts
            }
        except Exception:
            rule_target_ids = set()

        # Step 4 — build ConfigAttr list
        config_attrs: list[ConfigAttr] = []
        for ent in attr_ents:
            eid = ent["id"]
            pg = attr_pg.get(eid, {})

            var_name = str(
                pg.get("variable_name") or pg.get("name") or ent.get("name") or ""
            ).strip()
            if not var_name:
                continue

            # Patch C: skip noise attrs (TestPager, Error, dummy_* etc.)
            vn_lo = var_name.lower()
            if any(f in vn_lo for f in _NOISE_VAR_FRAGMENTS):
                logger.debug("cpq: skipping noise attr %r", var_name)
                continue

            # docs/CPQ_CONFIG_ATTR_STATUS_FILTERING_ROOT_CAUSE_AND_FIX_
            # PLAN_2026-08-14.md — BmConfigAttr rows carry the same
            # status=1 (active) / status=3 (inactive) convention already
            # relied on for BmConfigRule (see fetch_rules/fetch_value_
            # rules' active_only). Confirmed live: 15 real status=3
            # attribute rows exist (workspace 19) and were loaded
            # unconditionally — a deactivated/deleted attribute could
            # still be shown/asked to the customer. status is present on
            # every real BmConfigAttr row across both real workspaces
            # (verified — no attr lacks the field), so this never
            # accidentally excludes a legitimately-untracked attr.
            if str(pg.get("status", "")).strip() == "3":
                logger.debug("cpq: skipping inactive (status=3) attr %r", var_name)
                continue

            display = str(pg.get("name") or ent.get("name") or var_name).strip()
            required_raw = str(pg.get("required") or "0").strip().lower()
            required = required_raw in ("1", "true", "yes")
            default_val = str(pg.get("default_value") or "").strip()
            order = int(pg.get("order_number") or pg.get("order") or 999)

            hidden_raw = str(pg.get("hidden") or "0").strip().lower()
            is_hidden = hidden_raw in ("1", "true", "yes")
            array_control_raw = str(pg.get("is_array_control_attr") or "0").strip().lower()
            is_array_control = array_control_raw in ("1", "true", "yes")
            # "quantity" name fragment — candidate grid-quantity target attr
            # (e.g. mountingTypeShirtMagneticMountQuantity_viSoln). Kept
            # despite hidden+no-default so resolve_array_grid_links() can
            # name-match it against a visible selector's menu options (§5
            # Change B, docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md).
            is_grid_qty_candidate = "quantity" in vn_lo
            _src_id_raw = pg.get("id") or pg.get("attribute_id") or pg.get("bm_config_rule_id")
            _is_rule_target = eid in rule_target_ids or (
                _src_id_raw is not None
                and str(_src_id_raw).strip().isdigit()
                and int(_src_id_raw) in rule_target_ids
            )
            if (is_hidden and not default_val
                    and not (is_array_control or is_grid_qty_candidate or _is_rule_target)):
                # Hidden with nothing to contribute — never shown/asked, and
                # no static default to feed BML scripts — dropped, UNLESS
                # it's a rule action's target (Amendment 13): those attrs
                # are dynamically populated by a recommendation/constraint
                # rule at apply time, not a static default, and dropping
                # them here means they can never be filled at all.
                continue

            hide_in_trans_raw = str(pg.get("hide_in_trans") or "0").strip().lower()
            is_hide_in_trans = hide_in_trans_raw in ("1", "true", "yes")
            auto_lock_raw = str(pg.get("auto_lock") or "0").strip().lower()
            is_auto_lock = auto_lock_raw in ("1", "true", "yes")

            # Exclude layout/UI-noise nodes by checking attribute content
            if self._is_layout_noise(ent.get("type") or ""):
                continue

            # ID bridge: rules reference attributes by the BM-native id from
            # the source system, not by the aryx entity id. Keep both.
            source_id: int | None = None
            for id_key in ("id", "attribute_id", "bm_config_attr_id"):
                raw_sid = pg.get(id_key)
                if raw_sid is not None:
                    try:
                        source_id = int(str(raw_sid).strip())
                        break
                    except (TypeError, ValueError):
                        continue

            config_attrs.append(ConfigAttr(
                entity_id=eid,
                variable_name=var_name,
                display_label=display,
                required=required,
                default_value=default_val,
                options=menu_by_attr.get(eid, []),
                order=order,
                source_id=source_id,
                select_type=classify_select_type(pg),
                catalog_prefix=_catalog_prefix(ent.get("type") or ""),
                hidden=is_hidden,
                hide_in_trans=is_hide_in_trans,
                set_type=str(pg.get("set_type") or "").strip(),
                is_array_control=is_array_control,
                auto_lock=is_auto_lock,
                array_set_id=(array_set_id_by_attr_id.get(source_id) if source_id else None),
                array_set_role=(role_by_attr_id.get(source_id, "") if source_id else ""),
                array_col_order=(order_by_attr_id.get(source_id, 999) if source_id else 999),
                array_set_wrapper_key=(wrapper_key_by_attr_id.get(source_id, "") if source_id else ""),
            ))

        # Dedup by variable_name (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 8):
        # a catalog accidentally re-ingested wholesale (confirmed live,
        # workspace 19's SL3500e catalog — every entity type doubled,
        # timestamps exactly one day apart) produces 2+ ConfigAttr entries
        # sharing the same variable_name, each independently landing in
        # `pending` when unfilled — surfacing as duplicate questions for the
        # SAME real attribute (confirmed live: modelSelectionCertification_
        # apcr and 5 siblings each asked twice in one turn). Keep only the
        # highest entity_id per variable_name — aryx_entity.id is a
        # monotonic insert-order sequence, so this keeps whichever ingest
        # ran LAST, the same proxy the existing "duplicate entity per real
        # id" handling already relies on elsewhere (menu-option loss fix).
        by_vn: dict[str, ConfigAttr] = {}
        for a in config_attrs:
            existing = by_vn.get(a.variable_name)
            if existing is None or a.entity_id > existing.entity_id:
                by_vn[a.variable_name] = a
        config_attrs = list(by_vn.values())

        config_attrs.sort(key=lambda a: a.order)
        return config_attrs, product_hint

    # ── Rule loaders (dialect-agnostic via cpq.rdb) ──────────────────────────

    def _load_rule_join_data(self, workspace_id: int, catalog_prefix: str = ""):
        """Shared fetch for the rule loaders.

        BmConfigRuleInput/Action rows reference their rule by the BM-native
        rule id (``bm_config_rule_id`` from the source XML), NOT by the aryx
        entity id — the join key is the rule entity's own attrs ``id``.
        Returns (rdb, inputs_by_rule, actions_by_rule, marked_by_rule,
        chain_by_rule).

        catalog_prefix — restricts every join table to one ingested catalog.
        Required whenever a workspace holds more than one product's XML
        export: BM-native rule ids are only unique WITHIN one source, so two
        catalogs sharing a workspace can and do collide on the same native
        id (confirmed live — e.g. id 213876892 exists in both an APX Next
        and an SL3500e export). Without this, inputs_by_rule/actions_by_rule
        etc. silently merge rows from both catalogs under the same key, and
        whichever catalog's row is read last wins — corrupting rule
        evaluation even after fetch_rules() itself is correctly scoped.

        inputs_by_rule holds ALL of a rule's bm_config_rule_input rows, not
        just one — confirmed live 445/688 real rules in one catalog carry
        2+ input rows; keeping only the last (the previous behavior) meant
        63% of declarative rules with any condition were either dead
        (last-kept row's value blank) or silently over-firing (a real
        second condition dropped). See docs/CPQ_APX_NEXT_RULE_CATALOG.md
        "Gap Deep-Dive & Impact Analysis" and bml.evaluate_declarative_conditions
        for the AND/OR-grouping semantics applied to this list.

        docs/CPQ_RULE_JOIN_DATA_CACHING_PERFORMANCE_PLAN_2026_08_10.md —
        module-level, short-TTL cached (see _RULE_JOIN_DATA_CACHE above):
        this is the shared fetch every rule loader (load_hiding_rules,
        _load_value_rules, and everything built on top of them) calls
        independently, with zero caching previously — confirmed live 3+
        redundant full re-fetches of the same join data from one turn's
        single top-level rule-loading block.
        """
        _key = (workspace_id, catalog_prefix)
        _hit = _RULE_JOIN_DATA_CACHE.get(_key)
        if _hit is not None:
            _ts, _result = _hit
            if time.monotonic() - _ts < _RULE_JOIN_DATA_CACHE_TTL_SECONDS:
                return _result

        rdb = get_cpq_rdb()
        # (attr_id, value, operator) — operator is the raw BM-native
        # comparison code ("1"/"2"/.../"8"); see docs/CPQ_DECLARATIVE_
        # CONDITION_OPERATOR_PLAN_2026_08_05.md for what each means and
        # bml.evaluate_declarative_conditions for where it's interpreted.
        inputs_by_rule: dict[int, list[tuple[int, str, str]]] = {}
        for rid, aid, val, op in rdb.fetch_rule_inputs(workspace_id, catalog_prefix):
            inputs_by_rule.setdefault(rid, []).append((aid, val, op))
        actions_by_rule: dict[int, list[tuple[int, int, str, int, int, str]]] = {}
        for rid, aid, at, val, fn, st, comments in rdb.fetch_rule_actions(workspace_id, catalog_prefix):
            actions_by_rule.setdefault(rid, []).append((aid, at, val, fn, st, comments))
        # bm_config_marked_attr: the real target linkage for many declarative
        # hiding rules — verified against real data where BmConfigRuleAction
        # and the rule's own attr_id both carry no target (docs/CPQ_GRAPH_FIX_PLAN.md §6a).
        marked_by_rule: dict[int, list[int]] = {}
        for rid, aid in rdb.fetch_marked_attrs(workspace_id, catalog_prefix):
            marked_by_rule.setdefault(rid, []).append(aid)
        # bm_config_rule_assoc: some rules chain to a child rule rather than
        # declaring their own target; the terminal rule holds the real one.
        chain_by_rule: dict[int, int] = {}
        for rid, cid in rdb.fetch_rule_chain_links(workspace_id, catalog_prefix):
            chain_by_rule[rid] = cid
        _result = (rdb, inputs_by_rule, actions_by_rule, marked_by_rule, chain_by_rule)
        _RULE_JOIN_DATA_CACHE[_key] = (time.monotonic(), _result)
        return _result

    @staticmethod
    def _resolve_targets(
        rule_key: int,
        actions_by_rule: dict[int, list[tuple[int, int, str, int, int, str]]],
        marked_by_rule: dict[int, list[int]],
        chain_by_rule: dict[int, int],
        max_hops: int = 3,
    ) -> list[tuple[int, int]]:
        """Resolve a rule's target attribute(s), following the real linkage.

        Priority: (1) BmConfigRuleAction (still correct for exports that use
        it), (2) BmConfigMarkedAttr — may yield multiple targets, one per
        marked attribute, (3) BmConfigRuleAssoc chaining to a child rule,
        re-resolved through (1)-(2) at the terminal rule (bounded depth).
        Returns [(target_attr_id, action_type)] — action_type defaults to 2
        (hide) for marked-attr-sourced targets since no hide/show signal has
        ever been observed to vary in real data (see §6a).
        """
        acts = actions_by_rule.get(rule_key, [])
        if acts:
            return [(aid, at) for aid, at, _v, _f, _st, _c in acts]
        marked = marked_by_rule.get(rule_key)
        if marked:
            return [(aid, 2) for aid in marked]
        seen: set[int] = {rule_key}
        current = chain_by_rule.get(rule_key)
        hops = 0
        while current is not None and current not in seen and hops < max_hops:
            acts = actions_by_rule.get(current, [])
            if acts:
                return [(aid, at) for aid, at, _v, _f, _st, _c in acts]
            marked = marked_by_rule.get(current)
            if marked:
                return [(aid, 2) for aid in marked]
            seen.add(current)
            current = chain_by_rule.get(current)
            hops += 1
        return []

    @staticmethod
    def _rule_key(entity_id: int, source_id: int | None,
                  inputs: dict, actions: dict) -> int:
        """Pick the id that BmConfigRuleInput/Action rows actually reference."""
        if source_id is not None and (source_id in inputs or source_id in actions):
            return source_id
        return entity_id

    @staticmethod
    def _condition_has_operator_collision(conditions: list[tuple[int, str, str]]) -> bool:
        """True if any single attribute in `conditions` is checked with 2+
        DISTINCT operators — docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_
        PLAN_2026_08_05.md.

        evaluate_declarative_conditions groups same-attribute rows under a
        single shared operator (the first row's); for rows that genuinely
        share one operator (an OR-list of acceptable/excluded values) this
        is correct, but for rows with DIFFERENT operators on the same
        attribute it silently drops every row after the first — confirmed
        live via "Restrict Number Of Seats between 1 and 12" (`< 1` and
        `> 12` on the same attribute; only `< 1` would ever be checked).

        Confirmed catalog-wide (80 real rules across 4 catalogs) that no
        single combining rule fixes this correctly for every shape yet —
        two patterns are confirmed for 76% of cases, but forcing them in
        now would silently mis-evaluate the remaining ~24% (see the plan
        doc). Used as a purely structural, never-guessed exclusion: a rule
        hitting this collision is skipped entirely (same as if it were
        never confirmed) rather than loaded with a guessed combining rule.
        """
        by_attr: dict[int, set[str]] = {}
        for attr_id, _value, operator in conditions:
            by_attr.setdefault(attr_id, set()).add(operator)
        return any(len(ops) > 1 for ops in by_attr.values())

    def _detect_layout_tier(self, workspace_id: int, catalog_prefix: str = "") -> int:
        """docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md §2 — one cheap existence
        check per catalog, cached process-wide (same lifetime/reasoning as
        bml.py's _SHARED_SCRIPT_CACHE / _FLAG_KEYWORD_INDEX_CACHE above):
        1 = rule_type=6 "Configuration Flow" rules exist AND are referenced
            by BmConfigLayoutAttrAssoc (verified on 3 independent catalogs).
        2 = no rule_type=6 flow rule, but layout placement data exists
            anyway — still real UI-truth, just unscoped to one flow.
        3 = no layout data at all — callers must fall back to today's
            existing hidden/required + rule-based behavior unchanged; free,
            no new code needed for this tier.
        """
        key = (workspace_id, catalog_prefix)
        if key in _LAYOUT_TIER_CACHE:
            return _LAYOUT_TIER_CACHE[key]
        rdb = get_cpq_rdb()
        assoc = rdb.fetch_layout_attr_assoc(workspace_id, catalog_prefix)
        if not assoc:
            tier = 3
        else:
            flow_ids = {
                src_id for _eid, src_id, _name, _fn
                in rdb.fetch_rules(workspace_id, "6", catalog_prefix, active_only=True)
                if src_id is not None
            }
            tier = 1 if any(rid in flow_ids for rid, _a, _l in assoc) else 2
        _LAYOUT_TIER_CACHE[key] = tier
        return tier

    def _is_country_anchor_var(self, variable_name: str) -> bool:
        """The D1 country anchor specifically — NOT any "country"-fragment
        match. A plain substring check collides with real, distinct attrs
        confirmed live in this catalog: CRM_BILL_COUNTRY/CRM_SHIP_COUNTRY
        (noise-shaped integration fields) and isUltimateDestinationCountryCA_astro
        (a genuine but DIFFERENT boolean attr, "country" mid-name not at the
        end). Requiring BOTH "ends with country" (excludes the CA-suffixed
        boolean) AND not noise-shaped (excludes the two CRM_* fields)
        isolates exactly ultimateDestinationCountry in this catalog — same
        two-guard pattern auto_fill already uses elsewhere for fragment
        matches that would otherwise over-collide.
        """
        vn_flat = variable_name.lower().replace("_", "")
        return vn_flat.endswith("country") and not self._is_noise_var(variable_name)

    def _find_country_anchor_attr_id(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> int | None:
        """Native id of this catalog's country-anchor ConfigAttr, or None."""
        rdb = get_cpq_rdb()
        for _eid, attrs in rdb.fetch_entities_by_type(workspace_id, "bmconfigattr", catalog_prefix):
            vn = attrs.get("variable_name") or ""
            if self._is_country_anchor_var(vn):
                try:
                    return int(str(attrs.get("id")).strip())
                except (TypeError, ValueError):
                    continue
        return None

    def resolve_ui_layout_scope(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> dict[str, Any] | None:
        """docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md §1-§5 — which attributes
        the real native UI shows on screen, and in what order.

        Returns None for tier 3 (no layout data — caller keeps today's
        existing behavior unchanged, zero new code needed).

        Otherwise returns {"tier": 1|2, "flows": {flow_id: entry, ...}}.
        flow_id is 0 for tier 2 (no flow-rule scoping, one catalog-wide
        entry). Each entry is {"all": {attr_id: order_number},
        "section": {attr_id: order_number} | None} — "all" is every attr
        with layout placement (grouped/ordered, §4); "section" is the
        country-anchor's own parent_id group (§5) when exactly one such
        group exists for that flow, else None.

        Multiple rule_type=6 flows in one catalog (confirmed live: APX
        Next has 3) are a genuine, unresolved ambiguity — every
        disambiguation heuristic tried (biggest total flow, biggest
        immediate group) picked a DIFFERENT, WRONG flow when checked
        against the real ground-truth screenshot. This method deliberately
        does not guess: it returns one entry per flow and leaves picking
        one to the caller (e.g. a future curated per-catalog choice),
        rather than silently resolving to an unverified answer.
        """
        key = (workspace_id, catalog_prefix)
        if key in _LAYOUT_SCOPE_CACHE:
            return _LAYOUT_SCOPE_CACHE[key]
        tier = self._detect_layout_tier(workspace_id, catalog_prefix)
        if tier == 3:
            _LAYOUT_SCOPE_CACHE[key] = None
            return None
        rdb = get_cpq_rdb()
        assoc = rdb.fetch_layout_attr_assoc(workspace_id, catalog_prefix)
        nodes = rdb.fetch_layout_model_nodes(workspace_id, catalog_prefix)
        country_attr_id = self._find_country_anchor_attr_id(workspace_id, catalog_prefix)

        if tier == 1:
            flow_ids = {
                src_id for _eid, src_id, _name, _fn
                in rdb.fetch_rules(workspace_id, "6", catalog_prefix, active_only=True)
                if src_id is not None
            }
            by_flow: dict[int, list[tuple[int, int]]] = {}
            for rid, attr_id, lmid in assoc:
                if rid not in flow_ids:
                    continue
                by_flow.setdefault(rid, []).append((attr_id, lmid))
        else:
            by_flow = {0: [(attr_id, lmid) for _rid, attr_id, lmid in assoc]}

        flows: dict[int, dict[str, Any]] = {}
        for flow_id, attr_lmids in by_flow.items():
            attr_group: dict[int, tuple[int, int]] = {}
            for attr_id, lmid in attr_lmids:
                node = nodes.get(lmid)
                if node is None:
                    continue
                parent_id, _label, order_number = node
                if attr_id not in attr_group:
                    attr_group[attr_id] = (parent_id, order_number)
            all_attrs = {aid: order for aid, (_p, order) in attr_group.items()}
            section: dict[int, int] | None = None
            if country_attr_id is not None and country_attr_id in attr_group:
                target_parent, _own_order = attr_group[country_attr_id]
                section = {
                    aid: order for aid, (parent_id, order) in attr_group.items()
                    if parent_id == target_parent
                }
            flows[flow_id] = {"all": all_attrs, "section": section}

        result = {"tier": tier, "flows": flows}
        _LAYOUT_SCOPE_CACHE[key] = result
        return result

    @staticmethod
    def _walk_layout_components(node: Any) -> list[dict[str, Any]]:
        """Depth-first, document-order list of every leaf component object
        carrying a `resourceAttributeVarName` — the exact flattened order
        the native UI renders in, no `parent_id`/`order_number` tree walk
        needed (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §1: the raw
        relational `order_number` is sibling-scoped, not a flat rank; this
        nested JSON's own array order already is one)."""
        out: list[dict[str, Any]] = []

        def _walk(n: Any) -> None:
            if isinstance(n, dict):
                if "resourceAttributeVarName" in n:
                    out.append(n)
                for v in n.values():
                    _walk(v)
            elif isinstance(n, list):
                for item in n:
                    _walk(item)

        _walk(node)
        return out

    @classmethod
    def _load_layout_components(
        cls, workspace_id: int, catalog_prefix: str,
        layout_source: LayoutFileSource | None,
    ) -> list[dict[str, Any]] | None:
        """Parsed, `status=="Active"`-validated, flattened (document-order)
        component list for a catalog's layout export, or None if no
        currently-Active file exists. Cached process-lifetime — the shared
        parse step both `load_layout_display_order` (§2, visible-only) and
        `_load_layout_full_order` (§2b, ALL entries — rule conditions are
        frequently layout-*hidden*, e.g. a derived attr like Base Model,
        so the ranking those need can't come from the visible-only map)
        build on."""
        key = (workspace_id, catalog_prefix)
        if key in _LAYOUT_COMPONENTS_CACHE:
            return _LAYOUT_COMPONENTS_CACHE[key]
        source = layout_source or _DEFAULT_LAYOUT_FILE_SOURCE
        text = source.get(catalog_prefix)
        if not text:
            _LAYOUT_COMPONENTS_CACHE[key] = None
            return None
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            logger.warning(
                "cpq layout: malformed layout JSON for catalog_prefix=%r",
                catalog_prefix, exc_info=True,
            )
            _LAYOUT_COMPONENTS_CACHE[key] = None
            return None
        if not isinstance(data, dict) or data.get("status") != "Active":
            logger.info(
                "cpq layout: layout file for %r has status=%r, not "
                "'Active' — ignoring (stale/deprecated export guard)",
                catalog_prefix,
                data.get("status") if isinstance(data, dict) else None,
            )
            _LAYOUT_COMPONENTS_CACHE[key] = None
            return None
        components = cls._walk_layout_components(data)
        _LAYOUT_COMPONENTS_CACHE[key] = components
        return components

    def load_layout_display_order(
        self, workspace_id: int, catalog_prefix: str = "",
        layout_source: LayoutFileSource | None = None,
    ) -> dict[str, int] | None:
        """docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2 — {variable_name:
        rank} for exactly the attributes a catalog's decoded native-UI
        layout export marks `hide: false` and non-`HTML`-typed, ranked by
        the file's own document order (§1: the authoritative flat order —
        `bm_layout_model.order_number` is only sibling-scoped).

        Returns None when no matching, currently-Active layout file exists
        for this catalog — callers must treat that as "no layout signal",
        never as "empty visible set" (every §2/§2b/§2c mechanism built on
        this falls back to today's unchanged behavior in that case).

        layout_source — injected for tests / a future non-local backend
        (see LayoutFileSource); defaults to the process-wide local
        directory source (`ARYX_CPQ_LAYOUT_DIR`, else cwd).
        """
        key = (workspace_id, catalog_prefix)
        if key in _LAYOUT_DISPLAY_ORDER_CACHE:
            return _LAYOUT_DISPLAY_ORDER_CACHE[key]
        components = self._load_layout_components(workspace_id, catalog_prefix, layout_source)
        if components is None:
            _LAYOUT_DISPLAY_ORDER_CACHE[key] = None
            return None
        order: dict[str, int] = {}
        for comp in components:
            vn = comp.get("resourceAttributeVarName")
            if (
                vn and comp.get("hide") is False
                and comp.get("resourceAttrType") != "HTML"
                and vn not in order
            ):
                order[vn] = len(order)
        result = order or None
        _LAYOUT_DISPLAY_ORDER_CACHE[key] = result
        return result

    def _load_layout_full_order(
        self, workspace_id: int, catalog_prefix: str = "",
        layout_source: LayoutFileSource | None = None,
    ) -> dict[str, int] | None:
        """docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2b — {variable_name:
        rank} over EVERY component in the layout file's document order,
        regardless of `hide`/`resourceAttrType` — used for rule-conflict
        ranking, where a rule's condition attribute is very often itself
        layout-hidden (a derived/computed attr, e.g. Base Model, is never
        shown to the customer but still gates other rules). Distinct from
        `load_layout_display_order`, which intentionally excludes exactly
        those hidden attrs for the summary/payload visible-set use case.
        """
        key = (workspace_id, catalog_prefix)
        if key in _LAYOUT_FULL_ORDER_CACHE:
            return _LAYOUT_FULL_ORDER_CACHE[key]
        components = self._load_layout_components(workspace_id, catalog_prefix, layout_source)
        if components is None:
            _LAYOUT_FULL_ORDER_CACHE[key] = None
            return None
        order: dict[str, int] = {}
        for comp in components:
            vn = comp.get("resourceAttributeVarName")
            if vn and vn not in order:
                order[vn] = len(order)
        result = order or None
        _LAYOUT_FULL_ORDER_CACHE[key] = result
        return result

    def resolve_always_ask_skips(
        self, workspace_id: int, catalog_prefix: str, attrs: list[ConfigAttr],
    ) -> set[str]:
        """Variable names whose is_decision_attr always-ask override
        (auto_fill's skip_always_ask param, §3c) should be SKIPPED because
        the real native UI never shows them for this catalog's active
        configuration flow.

        Deliberately conservative — only acts when resolve_ui_layout_scope
        resolves to EXACTLY ONE active flow (tier 1, len(flows) == 1).
        Ambiguous catalogs (e.g. APX Next's 2 simultaneously-active flows)
        return an empty set, leaving today's unconditional always-ask
        behavior completely unchanged — see
        docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md §5/§6.
        """
        scope = self.resolve_ui_layout_scope(workspace_id, catalog_prefix)
        if not scope or scope["tier"] != 1 or len(scope["flows"]) != 1:
            return set()
        the_flow = next(iter(scope["flows"].values()))
        in_flow_ids = the_flow["all"]
        skips: set[str] = set()
        for attr in attrs:
            if attr.variable_name != "productSelectionProduct_all":
                continue
            if attr.entity_id not in in_flow_ids:
                skips.add(attr.variable_name)
        return skips

    def resolve_primary_layout_section_vns(
        self, workspace_id: int, catalog_prefix: str, attrs: list["ConfigAttr"],
    ) -> set[str] | None:
        """Variable names genuinely shown on the native UI's own configuration
        screen(s) — the country-anchor's own layout "section" (see
        resolve_ui_layout_scope), scoped to a single, deterministically-
        chosen flow when 2+ active flows exist.

        docs/config_consistency_issues_2026-07-30.md items 1/2: a real
        staging screenshot showed the native UI's Model Configuration panel
        surfacing ~10 fields for one screen, while Aryx's payload/summary
        carried 80-90 attributes total. This catalog's own ingested layout
        data doesn't resolve to per-SCREEN granularity (the finest grouping
        available is a ~35-attr "section" spanning several screens) — this
        is the ceiling of what's derivable without guessing a finer split
        the data doesn't contain.

        Flow disambiguation (APX Next ships 2 simultaneously-active
        rule_type=6 flows — resolve_ui_layout_scope's own docstring already
        flags this as unresolved): prefers the flow whose name does NOT end
        in "_sysConfig" (confirmed live: the two flows here are named
        "Configuration Flow For Astro Devices (Portable)" and
        "...Astro Devices (Portable)_sysConfig" — the suffixed one reads as
        a secondary/system-config variant, not the primary customer-facing
        flow). Falls back to the lowest flow_id for a stable, deterministic
        choice when no name is unsuffixed either way — never a random pick.

        Returns None (no narrowing — caller keeps existing full behavior)
        when: no layout data at all (tier 3), or the chosen flow has no
        resolvable country-anchor section. Never guesses a subset when the
        catalog's own data doesn't support one.
        """
        scope = self.resolve_ui_layout_scope(workspace_id, catalog_prefix)
        if not scope or not scope["flows"]:
            return None
        flow_ids = list(scope["flows"].keys())
        if len(flow_ids) == 1:
            chosen_id = flow_ids[0]
        else:
            rdb = get_cpq_rdb()
            names = {
                src_id: (name or "")
                for _eid, src_id, name, _fn
                in rdb.fetch_rules(workspace_id, "6", catalog_prefix, active_only=True)
                if src_id is not None
            }
            unsuffixed = [
                fid for fid in flow_ids
                if not names.get(fid, "").strip().lower().endswith("_sysconfig")
            ]
            chosen_id = min(unsuffixed) if unsuffixed else min(flow_ids)
        section = scope["flows"][chosen_id].get("section")
        if not section:
            return None
        by_entity_id = {a.entity_id: a.variable_name for a in attrs}
        return {
            by_entity_id[aid] for aid in section if aid in by_entity_id
        }

    @staticmethod
    def model_context_mirror_vns(attrs: list["ConfigAttr"]) -> set[str]:
        """Variable names of model-context MIRROR attrs — pointer-default
        attrs whose referenced attribute is an underscore-prefixed runtime
        context field (the platform's own `_bm_model_*`-style punch-in
        family). Fully structural: an attr qualifies when its
        default_value equals ANOTHER attr's variable name AND that name
        starts with "_" — no attribute names in code (matches
        modelname_all -> _bm_model_variable_name in both ingested
        exports, and nothing else, per the Issue 11 survey).
        """
        vns = {a.variable_name for a in attrs}
        return {
            a.variable_name for a in attrs
            if not a.options
            and a.default_value in vns
            and a.default_value != a.variable_name
            and a.default_value.startswith("_")
        }

    def payload_flow_exclusions(
        self, workspace_id: int, catalog_prefix: str, attrs: list["ConfigAttr"],
    ) -> set[str]:
        """Product/model flow mutual exclusivity for the payload
        (Issue 11 follow-up, docs/CPQ_PRODUCT_SWITCH_ISSUE.md): a quote is
        identified by its product selection OR its model context — never
        both.

        The flow signal is the catalog's own layout data
        (resolve_always_ask_skips): non-empty means the single active
        native-UI flow HIDES the product selector (model flow — e.g. SVX),
        so the product selector is excluded and model mirrors ship.
        Empty means the product selector is genuinely part of this
        catalog's flow, or the flow is ambiguous/unresolvable (e.g. APX
        Next's two active flows) — product flow: the product identifies
        the quote and the model-context mirrors are excluded instead
        (confirmed live: APX shipped modelname_all="aPXNext" alongside
        productSelectionProduct_all, violating the integration's
        one-or-the-other contract).
        """
        skips = self.resolve_always_ask_skips(workspace_id, catalog_prefix, attrs)
        if skips:
            return skips  # model flow — product excluded, mirrors ship
        return self.model_context_mirror_vns(attrs)  # product flow

    @staticmethod
    def array_grid_controls_in_play(attrs: list[ConfigAttr]) -> list[str]:
        """Variable names of is_array_control_attr=1 attrs present in this
        catalog (e.g. an array-control driving a mounting-type quantity
        grid) — flagged, never auto-populated.

        Investigated and deliberately NOT auto-filled
        (docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md §5 Change B
        follow-up): the real link between a customer's grid-row selection
        and its per-row quantity attr lives only in BigMachines' own
        native-UI array-control JavaScript widget — confirmed by a
        full-file scan of the raw XML finding ZERO bm_config_rule_input
        rows referencing the visible row-selector attr at all. Any
        code-side mapping would have to guess from variable-name patterns
        (e.g. "Shirt Magnetic Mount" -> mountingTypeShirtMagneticMount
        Quantity_viSoln), which is catalog-specific and unverifiable —
        exactly the guessing this engine's design principle forbids
        elsewhere (D2 "never guess"). This surfaces the gap instead of
        silently mis-populating or silently dropping it.
        """
        return sorted({a.variable_name for a in attrs if a.is_array_control})

    @staticmethod
    def resolve_array_grid_links(attrs: list[ConfigAttr]) -> dict[str, dict[str, str]]:
        """Best-effort variable-name heuristic linking a visible menu-based
        selector attr's options to hidden ``*Quantity*``-named attrs (kept
        in `attrs` for exactly this purpose — see load_product_config's
        drop-filter exception).

        Explicitly NOT rule-derived — array_grid_controls_in_play()'s own
        docstring and docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md §5
        confirm no such link exists in any ingested rule data. This is a
        deliberate, explicitly requested exception to this engine's
        "never guess" default, scoped as tightly as possible: a match only
        counts when EXACTLY ONE quantity candidate's normalized
        variable_name contains the option's normalized text (>=6 alnum
        chars, to avoid trivial/short-token false positives like "1" or
        "US"). Ambiguous or too-short tokens are skipped silently — never
        guessed. Returns {selector_vn: {item_value_lower: quantity_vn}}.
        """
        def norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]", "", s.lower())

        qty_candidates = [
            a for a in attrs if a.hidden and "quantity" in a.variable_name.lower()
        ]
        if not qty_candidates:
            return {}
        qty_norm = [(a.variable_name, norm(a.variable_name)) for a in qty_candidates]

        links: dict[str, dict[str, str]] = {}
        for attr in attrs:
            if attr.hidden or not attr.options:
                continue
            item_map: dict[str, str] = {}
            for opt in attr.options:
                token = norm(opt.display_name or opt.item_value)
                if len(token) < 6:
                    continue
                matches = [vn for vn, qn in qty_norm if token in qn]
                if len(matches) == 1:
                    item_map[opt.item_value.strip().lower()] = matches[0]
            if item_map:
                links[attr.variable_name] = item_map
        return links

    def resolve_pending_grid_quantities(
        self, attrs: list[ConfigAttr], filled: dict[str, str],
        filled_multi: dict[str, list[str]],
    ) -> list[ConfigAttr]:
        """Extra pending ConfigAttrs for grid-quantity attrs whose selector
        has a selected row without a quantity yet (resolve_array_grid_links).

        Each returned attr is a REAL ConfigAttr from `attrs` — asked via the
        same free-text pending mechanism as any other attribute (these
        quantity attrs have no menu options, so apply_answer's free-text
        numeric path handles the reply). No new UI/ask concept needed.
        """
        links = self.resolve_array_grid_links(attrs)
        if not links:
            return []
        by_vn = {a.variable_name: a for a in attrs}
        extra: list[ConfigAttr] = []
        seen: set[str] = set()
        for selector_vn, item_map in links.items():
            selected = filled_multi.get(selector_vn) or (
                [filled[selector_vn]] if selector_vn in filled and filled[selector_vn] else []
            )
            for item_value in selected:
                qty_vn = item_map.get(item_value.strip().lower())
                if not qty_vn or qty_vn in filled or qty_vn in seen:
                    continue
                qty_attr = by_vn.get(qty_vn)
                if qty_attr is None:
                    continue
                extra.append(qty_attr)
                seen.add(qty_vn)
        return extra

    def unresolved_grid_quantity_options(
        self, attrs: list[ConfigAttr], filled_multi: dict[str, list[str]],
    ) -> list[tuple[str, str]]:
        """Selected grid-selector options with NO resolvable quantity attr
        at all (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 9).

        `resolve_array_grid_links`'s own token-matching deliberately skips
        an option when its token is too short or ambiguous (matches 2+
        quantity-attr candidates) — confirmed live real example: SVX's
        bare "Magnetic Mount" option (distinct from "Jacket Magnetic
        Mount"/"Shirt Magnetic Mount") has no dedicated quantity attr in
        the catalog's own data at all (`qty_attr_id` is unpopulated,
        `-1`, catalog-wide — not authoritative), so its token
        "magneticmount" ambiguously matches BOTH siblings' quantity attrs
        and is correctly never guessed. Left unchecked, that selection's
        quantity is silently, permanently unaskable, yet the conversation
        still declares "Configuration complete" with a real per-row gap.

        Returns (selector_display_label, item_value) pairs for every
        selected option that participates in the grid-quantity mechanism
        (the selector has at least one OTHER option that DOES resolve —
        proving this is a real per-row-quantity construct, not a plain
        multi-select) but has no resolvable link of its own — so the
        caller can surface and block on this instead of completing.
        """
        links = self.resolve_array_grid_links(attrs)
        if not links:
            return []
        by_vn = {a.variable_name: a for a in attrs}
        unresolved: list[tuple[str, str]] = []
        for selector_vn, item_map in links.items():
            selector = by_vn.get(selector_vn)
            if selector is None:
                continue
            for item_value in filled_multi.get(selector_vn) or []:
                if item_value.strip().lower() not in item_map:
                    unresolved.append((selector.display_label, item_value))
        return unresolved

    def load_hiding_rules(self, workspace_id: int, catalog_prefix: str = "") -> list[HidingRule]:
        """Load hiding rules (rule_type=11) from the RDB.

        Declarative rules become HidingRule objects with condition_attr_id/
        condition_value/hide set. Script-backed rules (condition_function_id
        != -1) ALSO become HidingRule objects, with `script` set instead —
        confirmed live that 119 of 191 real hiding rules (62%) in this
        catalog are script-backed (e.g. "Hide HW Version unless region=NA OR
        country=KY OR customerType=FEDERAL"), so skipping them silently, as
        this method previously did, meant most of the source system's real
        show/hide dependencies never took effect here at all. Their target(s)
        are resolved the same way as declarative rules (via
        _resolve_targets); only the CONDITION differs, and is evaluated at
        apply time by BmlEvaluator.should_hide (see apply_hiding_rules).

        catalog_prefix — scopes to one ingested catalog (see
        _load_rule_join_data) when the workspace holds more than one
        product's XML export. "" preserves the original workspace-wide load.
        """
        _t0 = time.monotonic()
        logger.info(
            "cpq_step: load_hiding_rules start workspace_id=%s catalog_prefix=%r",
            workspace_id, catalog_prefix,
        )
        rules: list[HidingRule] = []
        script_missing = 0
        unresolved = 0
        operator_collisions = 0
        try:
            rdb, inputs, actions, marked, chain = self._load_rule_join_data(
                workspace_id, catalog_prefix)
            scripts = rdb.fetch_function_scripts(workspace_id, catalog_prefix)
            # active_only=True (docs/config_consistency_issues_2026-07-30.md,
            # Issue 5 follow-up): live-confirmed real harm from the
            # previously-deliberate byte-for-byte-unaffected choice noted in
            # fetch_rules' own docstring — a DISABLED (status=3) hiding rule,
            # "Hide Frequency Band & Extend Range if Product is selected as
            # APX Enhanced" (script condition reads modelSelectionFrequency
            # BandMsl_astro's OWN just-set value and hides it right back),
            # was still being loaded and evaluated, wiping a customer's
            # Frequency Band answer on the very same turn it was recorded.
            # rule_type="6" flow rules already opted into this exact filter
            # for the identical reason (dead/superseded rules alongside live
            # ones); hiding rules never had — this closes that gap.
            for eid, src_id, rule_name, fn_id in rdb.fetch_rules(
                workspace_id, "11", catalog_prefix, active_only=True,
            ):
                key = self._rule_key(eid, src_id, inputs, actions)
                targets = self._resolve_targets(key, actions, marked, chain)
                if not targets:
                    unresolved += 1
                    logger.info(
                        "cpq: hiding rule %r (id=%s) has no resolvable target "
                        "via action/marked_attr/chain — excluded, not "
                        "silently guessed", rule_name, key)
                    continue
                if fn_id != -1:
                    script = scripts.get(fn_id)
                    if not script:
                        script_missing += 1
                        logger.warning(
                            "cpq: hiding rule %r references function_id=%d "
                            "but no BmFunction script was found", rule_name, fn_id)
                        continue
                    for target_attr_id, _action_type in targets:
                        rules.append(HidingRule(
                            rule_name=rule_name or str(eid),
                            condition_attr_id=0,
                            condition_value="",
                            target_attr_id=target_attr_id,
                            script=script,
                        ))
                    continue
                inp_list = inputs.get(key)
                if not inp_list:
                    unresolved += 1
                    continue
                # docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_PLAN_2026_08_05.md
                # — a declarative condition checking the SAME attribute
                # with 2+ different operators cannot yet be evaluated
                # correctly by evaluate_declarative_conditions (it
                # collapses to the first row's operator+value, silently
                # dropping the rest). No single combining rule is
                # confirmed safe for every such shape yet — skip rather
                # than load with a guessed combining rule, same treatment
                # as the value-less-hide/constraint/recommendation/
                # validation branches in _load_value_rules.
                if self._condition_has_operator_collision(inp_list):
                    operator_collisions += 1
                    continue
                cond_attr_id, cond_value, cond_operator = inp_list[-1]
                for target_attr_id, action_type in targets:
                    rules.append(HidingRule(
                        rule_name=rule_name or str(eid),
                        condition_attr_id=cond_attr_id,
                        condition_value=cond_value,
                        condition_operator=cond_operator,
                        target_attr_id=target_attr_id,
                        hide=(int(action_type or 2) == 2),
                        conditions=list(inp_list),
                    ))
        except Exception:
            logger.debug("cpq: hiding rule load failed", exc_info=True)

        script_backed = sum(1 for r in rules if r.script is not None)
        logger.info(
            "cpq: loaded %d hiding rules (%d declarative, %d script-backed, "
            "%d missing script, %d unresolved, %d skipped: same-attribute "
            "operator collision, docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_"
            "PLAN_2026_08_05.md) elapsed_s=%.3f",
            len(rules), len(rules) - script_backed, script_backed,
            script_missing, unresolved, operator_collisions, time.monotonic() - _t0)

        # docs/CPQ_VALUELESS_HIDE_ACTION_LOADING_GAP_PLAN_2026_08_05.md — a
        # real, separate class of "hide" rule authored OUTSIDE rule_type=11
        # (a declarative action with no literal value1, e.g. "Associated rec
        # rule to Hide Frequency Band for Single Band") that _load_value_
        # rules already classifies correctly but the rest of the codebase
        # only ever asked for hiding rules from THIS method. Merged in here,
        # not by changing load_recommendation_and_constraint_rules' return
        # arity (that method is monkeypatched with a bare (rec, con) 2-tuple
        # across the test suite) — every existing caller of load_hiding_
        # rules() gets the complete set automatically, with zero call-site
        # changes anywhere.
        try:
            _rec, _con, _val, extra_hiding = self._load_value_rules(workspace_id, catalog_prefix)
        except Exception:
            logger.debug("cpq: value-less hiding rule load failed", exc_info=True)
            extra_hiding = []
        if extra_hiding:
            logger.info("cpq: loaded %d additional value-less-action hiding rules",
                        len(extra_hiding))
        logger.info(
            "cpq_step: load_hiding_rules done elapsed_s=%.3f total_rules=%d",
            time.monotonic() - _t0, len(rules) + len(extra_hiding),
        )
        return rules + extra_hiding

    @staticmethod
    def _attr_index(attrs: list[ConfigAttr]) -> dict[int, ConfigAttr]:
        """Index attrs by BOTH ids rules may reference.

        Rule inputs/actions carry BM-native attribute ids from the source
        system (ConfigAttr.source_id); legacy data may reference the aryx
        entity id directly. source_id wins on collision because that is what
        BigMachines rules actually use.
        """
        idx: dict[int, ConfigAttr] = {}
        for a in attrs:
            idx.setdefault(a.entity_id, a)
        for a in attrs:
            if a.source_id is not None:
                idx[a.source_id] = a
        return idx

    @staticmethod
    def _filled_by_rule_id(
        attrs: list[ConfigAttr], filled: dict[str, str],
        filled_multi: dict[str, list[str]] | None = None,
    ) -> dict[int, str]:
        """Map every id a rule may reference → the attr's filled value.

        select_type=="multi" attrs' current selections live in filled_multi
        (a separate structure from the scalar filled dict — see
        evaluate_rules_loop's docstring), not in `filled`. Joined here into
        a single "~"-delimited string so bml._operator_hit's set-
        intersection check (operators "7"/"8" — docs/CPQ_DECLARATIVE_
        CONDITION_OPERATOR_PLAN_2026_08_05.md Phase 2) sees the real
        current selection set instead of always finding the condition
        attribute missing. An explicitly-emptied multi-select (filled_multi
        holding []) still maps to "" here rather than being omitted — that
        is a known, real "nothing selected" state, not an unfilled one.
        """
        multi = filled_multi or {}
        out: dict[int, str] = {}
        for a in attrs:
            if a.variable_name in multi:
                val = "~".join(multi[a.variable_name])
            elif a.variable_name in filled:
                val = filled[a.variable_name]
            else:
                continue
            out[a.entity_id] = val
            if a.source_id is not None:
                out[a.source_id] = val
        return out

    def apply_hiding_rules(
        self,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        rules: list[HidingRule],
        bml_eval: BmlEvaluator | None = None,
        filled_multi: dict[str, list[str]] | None = None,
    ) -> tuple[list[ConfigAttr], list[str], set[str]]:
        """Apply hiding rules against current filled values.

        Script-backed rules (rule.script set) derive their hide/show outcome
        from the BML evaluator using the current filled variables (keyed by
        variable_name — BML scripts compare variable names directly, same
        convention as apply_constraint_rules). An unknown script outcome
        (bml_eval is None, or the evaluator can't determine it yet) leaves
        the target visible rather than risking hiding something the
        customer still needs — the safe default mirrors constraints'
        "unknown applies no constraint" rule, just inverted for hiding
        (unknown → don't hide, not → hide everything).

        filled_multi — select_type=="multi" attrs' current selections (see
        _filled_by_rule_id); only consulted for declarative conditions
        (operators "7"/"8"). Script-backed rules are unaffected — they
        already read `filled` directly via bml_eval, a separate contract.

        Returns:
          filtered_attrs — attrs still visible after rules are applied
          rule_messages  — human-readable list of rules that fired (for reporting)
          hidden_vns     — variable_names explicitly hidden by a fired rule
        """
        if not rules:
            return attrs, [], set()

        by_rule_id = self._attr_index(attrs)
        filled_by_rule_id = self._filled_by_rule_id(attrs, filled, filled_multi)

        hidden_eids: set[int] = set()
        messages: list[str] = []

        for rule in rules:
            target = by_rule_id.get(rule.target_attr_id)
            if not target:
                continue
            if rule.script is not None:
                if bml_eval is None:
                    continue
                hide = bml_eval.hide_for_script(rule.script, filled)
                if hide is True:
                    hidden_eids.add(target.entity_id)
                    messages.append(
                        f"*Rule '{rule.rule_name}' hid **{target.display_label}***"
                    )
                    rule_trace.record_fire(
                        rule_type="hiding", rule_id=rule.rule_name,
                        attr=target.variable_name, outcome="hide", bml_tier="script",
                    )
                elif hide is False:
                    hidden_eids.discard(target.entity_id)
                    rule_trace.record_fire(
                        rule_type="hiding", rule_id=rule.rule_name,
                        attr=target.variable_name, outcome="show", bml_tier="script",
                    )
                continue
            if rule.conditions:
                matched, _blocked = evaluate_declarative_conditions(
                    rule.conditions, filled_by_rule_id)
                if matched is not True:
                    continue  # unresolved or definitively false — doesn't fire
            else:
                current_val = filled_by_rule_id.get(rule.condition_attr_id)
                if current_val is None:
                    continue  # condition attr not filled yet — rule doesn't fire
                if not _condition_value_matches(
                    current_val, rule.condition_value, rule.condition_operator
                ):
                    continue
            if rule.hide:
                hidden_eids.add(target.entity_id)
                messages.append(
                    f"*Rule '{rule.rule_name}' hid **{target.display_label}***"
                )
                rule_trace.record_fire(
                    rule_type="hiding", rule_id=rule.rule_name,
                    attr=target.variable_name, outcome="hide",
                )
            else:
                hidden_eids.discard(target.entity_id)
                rule_trace.record_fire(
                    rule_type="hiding", rule_id=rule.rule_name,
                    attr=target.variable_name, outcome="show",
                )

        hidden_vns = {a.variable_name for a in attrs if a.entity_id in hidden_eids}
        filtered = [a for a in attrs if a.entity_id not in hidden_eids]
        return filtered, messages, hidden_vns

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
        _t0 = time.monotonic()
        logger.info(
            "cpq_step: _load_value_rules (rec/con/validation) start "
            "workspace_id=%s catalog_prefix=%r", workspace_id, catalog_prefix,
        )
        rec_rules: list[RecommendationRule] = []
        con_rules: list[ConstraintRule] = []
        validation_rules: list[ValidationRule] = []
        hiding_rules: list[HidingRule] = []
        script_constraints = 0
        script_recommendations_wired = 0
        cond_script_skipped = 0
        script_condition_gated = 0
        ambiguous_recommendations_skipped = 0
        assign_all_answers_blocked = 0
        unrecognized_answers_requeued = 0
        validation_collisions_skipped = 0
        constraint_collisions_skipped = 0
        recommendation_collisions_skipped = 0
        hiding_collisions_skipped = 0
        # Ambiguous multi-value recommendations are never guessed (D2) — instead
        # routed through the same HITL ingest-question queue used elsewhere for
        # ingest-time ambiguity. Prefetch existing rows once so 14 rules don't
        # cost 14 round-trips, and so an already-answered rule resolves normally
        # instead of being skipped forever.
        try:
            ingest_store = IngestQuestionStore(get_settings().rdb_dsn)
            existing_questions = {
                q["job_id"]: q for q in ingest_store.list(workspace_id, status="")
            }
        except Exception:
            ingest_store = None
            existing_questions = {}
        try:
            rdb, inputs, actions, _marked, _chain = self._load_rule_join_data(
                workspace_id, catalog_prefix)
            scripts = rdb.fetch_function_scripts(workspace_id, catalog_prefix)
            for eid, src_id, rule_name, _rule_type, fn_id in rdb.fetch_value_rules(
                workspace_id, catalog_prefix, active_only=True,
            ):
                key = self._rule_key(eid, src_id, inputs, actions)
                inp_list = inputs.get(key)
                acts = actions.get(key, [])

                # Script-backed actions: gated by set_type same as declarative
                # ones. set_type == -1 → the BML function returns the allowed
                # list at apply time (constraint semantics, handled by the
                # existing BML evaluator path). Any other set_type is a
                # script-backed RECOMMENDATION/default — now wired to
                # RecommendationRule.script + apply_recommendation_rules'
                # BmlEvaluator hookup (previously extracted but never
                # evaluated at all — see docs/CPQ_RULE_TOOL_FLOW_PLAN.md
                # item 2/§7-8's confirmed "APX NEXT ENHANCED product +
                # non-Enhanced hardware" inconsistency this closes).
                for aid, _at, _val, act_fn, act_set_type, _comments in acts:
                    if act_fn != -1:
                        script = scripts.get(act_fn)
                        if not script:
                            logger.warning(
                                "cpq: rule %r references function_id=%d but no "
                                "BmFunction script was found", rule_name, act_fn)
                        elif act_set_type == -1:
                            con_rules.append(ConstraintRule(
                                rule_name=rule_name or str(eid),
                                condition_attr_id=(inp_list[-1][0] if inp_list else 0),
                                condition_value="",
                                target_attr_id=aid,
                                allowed_values=[],
                                script=script,
                            ))
                            script_constraints += 1
                        else:
                            rec_rules.append(RecommendationRule(
                                rule_name=rule_name or str(eid),
                                condition_attr_id=0,
                                condition_value="",
                                target_attr_id=aid,
                                script=script,
                            ))
                            script_recommendations_wired += 1
                            logger.info(
                                "cpq: rule %r is a script-backed recommendation "
                                "(function_id=%d, target=%d) — evaluated via "
                                "BmlEvaluator at apply time",
                                rule_name, act_fn, aid)

                condition_script: str | None = None
                if fn_id != -1:
                    # Condition itself is a script (boolean BML), not the
                    # single condition_attr_id/condition_value pair. As long
                    # as the rule's ACTION is declarative (handled below),
                    # gate it via condition_script instead of dropping it —
                    # apply time runs the same Tier-1/Tier-2 boolean
                    # evaluator apply_hiding_rules already uses (D2 "never
                    # guess" still holds: unknown outcome never fires).
                    condition_script = scripts.get(fn_id)
                    if not condition_script:
                        cond_script_skipped += 1
                        logger.warning(
                            "cpq: rule %r references condition_function_id=%d "
                            "but no BmFunction script was found — not gated",
                            rule_name, fn_id)
                        continue
                    cond_attr_id, cond_value, cond_operator = 0, "", "4"
                else:
                    if not inp_list:
                        continue
                    cond_attr_id, cond_value, cond_operator = inp_list[-1]

                # Amendment 12 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md):
                # a message-only action (function_id=-1, empty value1, but
                # a real human-authored `comments` string) is neither a
                # hide, a set, nor a restrict — its only content is a
                # warning to show when this rule's own condition (script OR
                # declarative) fires. Originally scoped to condition_script
                # only ("a declarative-condition version would need
                # separate confirmation before being added here" — this
                # comment's own prior text); docs/CPQ_CONDITIONAL_REQUIRED_
                # RULE_PLAN_2026_08_05.md provides that confirmation via a
                # 4-catalog audit (138/150 real declarative "set_type=-1,
                # no value1" rows carry a genuine message). By this point
                # either condition_script is set or inp_list was non-empty
                # (the `if not inp_list: continue` above already filtered
                # out rules with neither), so no extra guard is needed here.
                # docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_PLAN_2026_08_05.md
                # — a declarative (non-script) condition where the SAME
                # attribute is checked with 2+ different operators cannot
                # yet be evaluated correctly (evaluate_declarative_
                # conditions collapses to the first row's operator+value,
                # silently dropping the rest). Confirmed catalog-wide that
                # no single combining rule is safe for every such shape
                # yet (80 real rules across 4 catalogs, only 76% resolved
                # with confidence) — applies uniformly to EVERY rule type
                # built from this same inp_list (constraint, recommend,
                # value-less-hide, validation-message below), not just the
                # newest one: a HidingRule/ConstraintRule/RecommendationRule
                # with this exact same-attribute/multi-operator shape would
                # evaluate its condition just as incorrectly (e.g.
                # collapsing "< 1 OR > 12" to only ever check "< 1", or
                # merging a CONTAINS/NOT-CONTAINS pair into a single
                # over-broad OR) as an unguarded declarative ValidationRule
                # would. Skip all four entirely rather than load any of
                # them with a guessed combining rule. Does not apply to
                # script-gated rules (condition_script is not None) —
                # those are unaffected, evaluated by the BML engine, not
                # evaluate_declarative_conditions.
                declarative_condition_collision = (
                    condition_script is None
                    and inp_list is not None
                    and self._condition_has_operator_collision(inp_list)
                )
                for aid, _at, val, act_fn, _set_type, comments in acts:
                    # "System recommendation" is BigMachines' own generic
                    # boilerplate default comment (confirmed: 365
                    # occurrences across this one catalog alone) — not a
                    # real, customer-facing message a rule author actually
                    # wrote. Excluded so a meaningless "⚠️ System
                    # recommendation" is never shown. Re-confirmed as the
                    # only such placeholder across all 138 declarative
                    # candidates too (see the plan doc's boilerplate scan).
                    if (act_fn == -1 and not val and comments
                            and comments.strip().lower() != "system recommendation"):
                        if declarative_condition_collision:
                            validation_collisions_skipped += 1
                            continue
                        validation_rules.append(ValidationRule(
                            rule_name=rule_name or str(eid),
                            target_attr_id=aid,
                            message=comments,
                            condition_script=condition_script,
                            condition_attr_id=cond_attr_id,
                            condition_value=cond_value,
                            condition_operator=cond_operator,
                            conditions=list(inp_list) if condition_script is None else None,
                        ))

                # Declarative actions, bucketed per target by set_type.
                # BigMachines packs multiple allowed values for one action
                # into a single value1 field, tilde-delimited (confirmed live:
                # "DEVICE RENTAL~DEVICE INSTALLATION~DEVICE PROGRAMMING" for
                # one rule_action row) — split before use or the whole glued
                # string gets treated as one (non-existent) option, leaving
                # the target with zero real valid values.
                restrict_by_target: dict[int, list[str]] = {}
                recommend_by_target: dict[int, str] = {}
                # docs/CPQ_VALUELESS_HIDE_ACTION_LOADING_GAP_PLAN_2026_08_05.md
                # — a declarative action with NO literal value1 (function_id
                # =-1) is a genuine "hide" for set_type in (1, 3): confirmed
                # via cross-catalog rule-name sampling (1,096 such actions
                # across 4 ingested catalogs), e.g. "Associated rec rule to
                # Hide Frequency Band for Single Band" — hiding needs no
                # value to assign, unlike a recommendation/constraint. Scoped
                # to (1, 3) specifically: set_type=2's real names are
                # genuinely mixed (some "Show...", some "Set X to blank" —
                # a third, distinct semantic), and set_type=-1's real names
                # are mostly unrelated format/range validation ("Restrict
                # value of Astro System Id to 4 hexadecimal chars") — never
                # guessed without separate confirmation (D2).
                hide_targets: set[int] = set()
                for aid, _at, val, act_fn, set_type, _comments in acts:
                    if act_fn != -1:
                        continue
                    if not val:
                        if set_type in (1, 3):
                            hide_targets.add(aid)
                        continue
                    parts = [p.strip() for p in val.split("~") if p.strip()]
                    if set_type == -1:
                        restrict_by_target.setdefault(aid, []).extend(parts)
                    elif len(parts) == 1:
                        recommend_by_target.setdefault(aid, parts[0])
                    else:
                        # docs/CPQ_BUG2_CONSTRAINT_DISPATCH_MISCLASSIFICATION_
                        # IMPLEMENTATION_PLAN_2026-08-14.md (v2) — a multi-
                        # value, set_type != -1 action is genuinely ambiguous
                        # between two DIFFERENT intents: "assign all N values
                        # as the default selection" vs. "narrow this field's
                        # valid choices to exactly these N values" (a
                        # constraint). Verified live against real ingested
                        # data (apx-cpq-test + workspace 19, 62 real rows)
                        # that NEITHER the target's select_type NOR any BM-
                        # native constraint-shaped field (constrain_all,
                        # constraint_type, filter_attribute, action_type,
                        # value_type) varies AT ALL across this whole rule
                        # set — there is no structural signal in the ingested
                        # schema that resolves this. Never guessed in code
                        # (D2) — a wrong automatic guess here would ship a
                        # customer configuration with features they never
                        # chose, worse than today's silent skip. Routed to a
                        # human via aryx_ingest_question, asking the actual
                        # question (constraint vs. assign-all) instead of the
                        # old "which ONE is the default" framing, which was
                        # incoherent for every one of these rules (their
                        # targets are all multi-select fields, verified live
                        # — "pick exactly one" was never a valid framing). A
                        # distinct job_id/kind from the old ambiguous-
                        # recommendation question avoids misreading any prior
                        # answer under the old (wrong) question semantics —
                        # confirmed live that none of the 62 real rows were
                        # ever answered, so this is a clean cutover.
                        # Raven review of PR #198 — a malformed/case-mismatched
                        # answer (e.g. "Constraint", stray whitespace) must
                        # never permanently strand the rule with only a
                        # manual DB fix as recovery. Normalize before
                        # comparing, and if the LATEST question in this
                        # rule's job_id chain was answered with neither
                        # recognized value, mint the NEXT one in the chain so
                        # a fresh, pending, answerable question appears
                        # automatically — the stale answered row is left
                        # alone (harmless history), never re-used or deleted.
                        base_job_id = f"cpq-rule-{eid}-{aid}-constraint-or-default"
                        job_id = base_job_id
                        chain_n = 2
                        while f"{base_job_id}-r{chain_n}" in existing_questions:
                            job_id = f"{base_job_id}-r{chain_n}"
                            chain_n += 1
                        existing = existing_questions.get(job_id)
                        answered_unrecognized = False
                        if existing and existing.get("status") == "answered":
                            answer = (existing.get("answer") or "").strip().lower()
                            if answer == "constraint":
                                restrict_by_target.setdefault(aid, []).extend(parts)
                                continue
                            if answer == "assign_all":
                                # Not yet applicable — RecommendationRule.
                                # recommended_value (state.py:111) holds a
                                # single value; assigning N simultaneous
                                # values needs a separate model change
                                # (list-valued recommendations wired into
                                # filled_multi). Logged as blocked, never
                                # silently guessed or partially applied.
                                assign_all_answers_blocked += 1
                                logger.info(
                                    "cpq: rule %r answered 'assign_all' for "
                                    "target=%d (%r), but multi-value "
                                    "recommendation assignment isn't "
                                    "supported yet — blocked pending a "
                                    "separate fix", rule_name, aid, parts)
                                continue
                            # Unrecognized answer — mint the next job_id in
                            # the chain so the enqueue below creates a fresh,
                            # pending question instead of leaving this rule
                            # permanently stuck behind an unusable answer.
                            answered_unrecognized = True
                            unrecognized_answers_requeued += 1
                            job_id = f"{base_job_id}-r{chain_n}"
                            existing = None
                        ambiguous_recommendations_skipped += 1
                        logger.info(
                            "cpq: rule %r has a multi-value action "
                            "(set_type=%r) for target=%d (%r) — no "
                            "structural signal distinguishes constraint "
                            "from assign-all, %s", rule_name, set_type, aid,
                            parts,
                            "prior answer was unrecognized (expected "
                            "'constraint' or 'assign_all') — a fresh "
                            "question has been queued" if answered_unrecognized
                            else "awaiting human answer (already queued)" if existing
                            else "queued for human answer")
                        if not existing and ingest_store is not None:
                            try:
                                ingest_store.enqueue(
                                    workspace_id, job_id=job_id,
                                    kind="cpq_multivalue_constraint_or_default",
                                    prompt=(
                                        f"Rule '{rule_name}' offers {parts} "
                                        f"for attribute {aid}. Should this "
                                        "NARROW the field's valid choices to "
                                        "exactly these values (reply "
                                        "'constraint'), or ASSIGN all of "
                                        "them as the default selection "
                                        "(reply 'assign_all')?"),
                                    options=["constraint", "assign_all"],
                                    suggested="")
                                existing_questions[job_id] = {"status": "pending"}
                            except Exception:
                                logger.debug(
                                    "cpq: failed to enqueue constraint-or-"
                                    "default ingest question", exc_info=True)

                if condition_script:
                    if restrict_by_target or recommend_by_target:
                        script_condition_gated += 1
                        logger.info(
                            "cpq: rule %r has a script condition "
                            "(condition_function_id=%d) gating a declarative "
                            "action — evaluated via BmlEvaluator at apply time",
                            rule_name, fn_id)
                    else:
                        # Script condition but no declarative action to gate
                        # (e.g. the action was itself script-backed and
                        # already wired above, or genuinely has no action) —
                        # nothing left for condition_script to attach to.
                        cond_script_skipped += 1
                        logger.info(
                            "cpq: rule %r has a script condition "
                            "(condition_function_id=%d) but no declarative "
                            "action — nothing to gate", rule_name, fn_id)
                for target_attr_id, allowed in restrict_by_target.items():
                    if declarative_condition_collision:
                        constraint_collisions_skipped += 1
                        continue
                    con_rules.append(ConstraintRule(
                        rule_name=rule_name or str(eid),
                        condition_attr_id=cond_attr_id,
                        condition_value=cond_value,
                        condition_operator=cond_operator,
                        target_attr_id=target_attr_id,
                        allowed_values=allowed,
                        conditions=list(inp_list) if condition_script is None else None,
                        condition_script=condition_script,
                    ))
                for target_attr_id, rec_val in recommend_by_target.items():
                    if declarative_condition_collision:
                        recommendation_collisions_skipped += 1
                        continue
                    rec_rules.append(RecommendationRule(
                        rule_name=rule_name or str(eid),
                        condition_attr_id=cond_attr_id,
                        condition_value=cond_value,
                        condition_operator=cond_operator,
                        target_attr_id=target_attr_id,
                        recommended_value=rec_val,
                        conditions=list(inp_list) if condition_script is None else None,
                        condition_script=condition_script,
                    ))
                for target_attr_id in hide_targets:
                    if declarative_condition_collision:
                        hiding_collisions_skipped += 1
                        continue
                    hiding_rules.append(HidingRule(
                        rule_name=rule_name or str(eid),
                        condition_attr_id=cond_attr_id,
                        condition_value=cond_value,
                        condition_operator=cond_operator,
                        target_attr_id=target_attr_id,
                        hide=True,
                        script=condition_script,
                        conditions=list(inp_list) if condition_script is None else None,
                    ))
        except Exception:
            logger.debug("cpq: value-rule load failed", exc_info=True)
        logger.info(
            "cpq: loaded %d recommendation rules, %d constraint rules, "
            "%d value-less hide rules "
            "(%d script-backed constraints, %d script-backed recommendations "
            "wired, %d script-condition rules gating a declarative action, "
            "%d script-condition rules skipped, %d multi-value actions "
            "awaiting a constraint-or-assign-all human answer, %d 'assign_all' "
            "answers blocked (multi-value recommendation not yet supported), "
            "%d unrecognized answers auto-requeued with a fresh question, "
            "%d/%d/%d recommendation/constraint/hide skipped: same-attribute "
            "operator collision, "
            "docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_PLAN_2026_08_05.md)",
            len(rec_rules), len(con_rules), len(hiding_rules), script_constraints,
            script_recommendations_wired, script_condition_gated,
            cond_script_skipped, ambiguous_recommendations_skipped,
            assign_all_answers_blocked, unrecognized_answers_requeued,
            recommendation_collisions_skipped, constraint_collisions_skipped,
            hiding_collisions_skipped)
        logger.info(
            "cpq: loaded %d validation (warning-message) rules "
            "(%d skipped: same-attribute operator collision, "
            "docs/CPQ_SAME_ATTRIBUTE_OPERATOR_COLLISION_PLAN_2026_08_05.md)",
            len(validation_rules), validation_collisions_skipped)
        logger.info(
            "cpq_step: _load_value_rules done elapsed_s=%.3f rec=%d con=%d "
            "validation=%d extra_hiding=%d",
            time.monotonic() - _t0, len(rec_rules), len(con_rules),
            len(validation_rules), len(hiding_rules),
        )
        return rec_rules, con_rules, validation_rules, hiding_rules

    def load_recommendation_and_constraint_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> tuple[list[RecommendationRule], list[ConstraintRule]]:
        """Both rule sets in a single pass — the call callers wanting BOTH
        should use. load_recommendation_rules()/load_constraint_rules() each
        independently call _load_value_rules(), which repeats the same 4
        join-table queries plus a full function-script scan; calling both
        back-to-back (as every CPQ turn does) doubles that DB work for no
        reason. Prefer this method whenever both lists are needed.

        Return arity deliberately unchanged (still a 2-tuple) — widely
        monkeypatched across the test suite with a bare `(rec, con)` stub;
        the value-less-action hiding rule subset (docs/CPQ_VALUELESS_HIDE_
        ACTION_LOADING_GAP_PLAN_2026_08_05.md) is folded into
        load_hiding_rules() instead, so every existing caller/mock of
        EITHER method keeps working unchanged."""
        rec_rules, con_rules, _validation_rules, _extra_hiding_rules = (
            self._load_value_rules(workspace_id, catalog_prefix))
        return rec_rules, con_rules

    def load_validation_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[ValidationRule]:
        """Warning-message rules (Amendment 12) for this catalog — see
        ValidationRule's own docstring and _load_value_rules for how these
        are distinguished from Hiding/Recommendation/Constraint rules.
        Shares _load_value_rules' fetch with load_recommendation_and_
        constraint_rules — call both only when genuinely needed, same
        double-fetch caveat as load_recommendation_rules."""
        _rec_rules, _con_rules, validation_rules, _extra_hiding_rules = (
            self._load_value_rules(workspace_id, catalog_prefix))
        return validation_rules

    def load_recommendation_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[RecommendationRule]:
        """Recommendation rules for this catalog — see _load_value_rules for
        how rule semantics are classified (NOT by rule_type/action_type).
        If you also need constraint rules, call
        load_recommendation_and_constraint_rules() instead to avoid fetching
        the same rule data twice."""
        rec_rules, _con_rules, _validation_rules, _extra_hiding_rules = (
            self._load_value_rules(workspace_id, catalog_prefix))
        return rec_rules

    def apply_recommendation_rules(
        self,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        rules: list[RecommendationRule],
        bml_eval: BmlEvaluator | None = None,
        filled_multi: dict[str, list[str]] | None = None,
        constrained_opts: dict[int, list[str]] | None = None,
    ) -> dict[str, tuple[str, str]]:
        """Apply recommendation rules. Returns {variable_name: (item_value, display)}.

        Only fills attrs that are not already filled. Does not override prior
        user selections or auto-fills from earlier loop iterations.

        Script-backed rules (rule.script set) derive their recommended value
        from the BML evaluator using the current filled variables — same
        Tier-1/Tier-2 machinery apply_constraint_rules already uses via
        BmlEvaluator.allowed_values_for_script. Closes the gap where
        script-backed recommendations were extracted but never evaluated
        (RecommendationRule previously had no script field/hookup at all —
        see docs/CPQ_RULE_TOOL_FLOW_PLAN.md item 2/§7-8's confirmed
        "APX NEXT ENHANCED product + non-Enhanced hardware" inconsistency).
        A script resolving to anything other than EXACTLY one value (None,
        or 2+ candidates) is treated as "not yet determined" and skipped —
        same D2 "never guess" principle as the existing tilde-delimited
        ambiguous-recommendation skip below. bml_eval=None (caller opted
        out) silently skips script-backed rules, same as apply_constraint_rules.

        filled_multi — see apply_hiding_rules; only consulted for
        declarative conditions on a select_type=="multi" attribute
        (operators "7"/"8").

        constrained_opts — this function runs BEFORE apply_constraint_rules
        recomputes it for the CURRENT pass (evaluate_rules_loop's own
        "hide -> auto_fill -> recommend -> constrain" order), so what's
        passed in here is necessarily the PREVIOUS pass's result — still
        the best available signal, and correct at the fixed point once the
        loop converges. Live regression: without this, a recommendation
        whose OWN condition never depends on the attribute a DIFFERENT,
        active constraint just narrowed (e.g. "Default Service Type based
        on Solution Type selected" vs. a Hardware-Version-keyed constraint
        on the same target) kept unconditionally re-asserting its value
        the instant auto_fill's own re-validation correctly dropped it —
        every pass, forever, since this function only checks "is the
        target currently filled at all", never "is this specific value
        still valid". evaluate_rules_loop's fixed-point check compares KEY
        sets, not values, so a target that's drop-then-immediately-refilled
        to the SAME stale value every pass looked stable and converged
        with the wrong answer, silently reporting a complete configuration
        that a separate BOM-gate consistency check only caught one turn
        later. None (caller opted out, e.g. the constraint pass hasn't run
        even once yet) applies no filter, same "unknown -> don't guess a
        restriction that isn't provably there" convention used everywhere
        else a constraint is optional in this module.
        """
        if not rules:
            return {}
        by_rule_id = self._attr_index(attrs)
        filled_by_rule_id = self._filled_by_rule_id(attrs, filled, filled_multi)
        new_fills: dict[str, tuple[str, str]] = {}
        for rule in rules:
            target = by_rule_id.get(rule.target_attr_id)
            # A truthy check, not `in filled` — an empty string is D4's
            # deliberate "user cleared this" marker
            # (docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md), the single-select
            # counterpart of filled_multi's existing "(none)" convention.
            # A genuine rule re-assertion must still override it (same as
            # it would override any other stale value) — only a REAL
            # value already present blocks this rule from firing.
            if not target or filled.get(target.variable_name):
                continue
            if rule.script is not None:
                if bml_eval is None:
                    continue
                allowed = bml_eval.allowed_values_for_script(rule.script, filled)
                if not allowed or len(allowed) != 1:
                    continue  # unknown, or ambiguous — never guess
                recommended_value = allowed[0]
            elif rule.condition_script is not None:
                if bml_eval is None:
                    continue
                fires = bml_eval.condition_holds(rule.condition_script, filled)
                if fires is not True:
                    continue  # False or unknown — never guess, doesn't fire
                recommended_value = rule.recommended_value
            else:
                if rule.conditions:
                    matched, _blocked = evaluate_declarative_conditions(
                        rule.conditions, filled_by_rule_id)
                    if matched is not True:
                        continue
                else:
                    if rule.condition_attr_id not in filled_by_rule_id:
                        continue
                    if not _condition_value_matches(
                        filled_by_rule_id[rule.condition_attr_id], rule.condition_value,
                        rule.condition_operator,
                    ):
                        continue
                recommended_value = rule.recommended_value
            matched_display = next(
                (o.display_name for o in target.options
                 if o.item_value.lower() == recommended_value.lower()),
                recommended_value,
            )
            if not _valid(recommended_value):
                continue
            allowed_for_target = (
                constrained_opts.get(target.entity_id) if constrained_opts else None
            )
            if allowed_for_target is not None and not any(
                recommended_value.lower() == v.lower() for v in allowed_for_target
            ):
                # A DIFFERENT, already-active constraint has ruled this
                # value out — never re-assert it just because this rule's
                # own condition doesn't happen to mention that constraint.
                continue
            new_fills[target.variable_name] = (recommended_value, matched_display)
            rule_trace.record_fire(
                rule_type="recommendation", rule_id=rule.rule_name,
                attr=target.variable_name, outcome=f"set={recommended_value}",
                bml_tier="script" if rule.script is not None else None,
            )
        if new_fills:
            logger.info("cpq: recommendation rules auto-filled %s", list(new_fills.keys()))
        return new_fills

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
        """Re-apply recommendation rules to attrs the ENGINE already filled
        (never a customer's own choice), correcting them when a driving
        attribute's later value now changes what they should be.

        docs/config_consistency_issues_2026-07-30.md issue 6 (FedRAMP) /
        docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §4.1: this codebase
        previously only DETECTED this class of drift
        (`find_rule_inconsistencies` — logged, never corrected), deliberately,
        since "the engine can't be certain what the correct value should
        have been" for a value the CUSTOMER chose. That reasoning does not
        apply to a value the engine itself auto-filled before its own
        driving attribute had a value yet (the documented "first-by-order
        claimed it first" race in `auto_fill`'s own docstring) — re-running
        the SAME deterministic rule with fresher inputs isn't guessing, it's
        finishing a computation that fired too early. Scoped by
        `filled_source`, the exact boundary `find_rule_inconsistencies`
        already uses: "user" is never touched. Also excludes "hint" and
        "cascade" — both still trace back to something the customer said or
        confirmed, not a value this method has any business overwriting.

        Only ever revisits attrs already in `filled` (single-select) — a
        multi-select TARGET's value lives in `filled_multi`, out of scope
        for this pass; `apply_recommendation_rules` (unfilled attrs) is
        unaffected, this only ever touches already-filled ones. filled_multi
        is still accepted here for the separate purpose of reading a rule's
        CONDITION attribute when that attribute (not the target) is
        select_type=="multi" (operators "7"/"8" — see apply_hiding_rules).

        Returns {variable_name: (item_value, display)} for every attr whose
        value actually changed. The caller is expected to apply these
        exactly like any other rule-sourced fill and treat them as a real
        change for cascade-dependent invalidation, same as an explicit
        customer edit would.

        constrained_opts — see apply_recommendation_rules' identical
        parameter; a "correction" back to a value a different, currently-
        active constraint has already excluded is not a correction.
        """
        if not rules:
            return {}
        _NEVER_OVERRIDE = {"user", "hint", "cascade"}
        by_rule_id = self._attr_index(attrs)
        filled_by_rule_id = self._filled_by_rule_id(attrs, filled, filled_multi)
        corrections: dict[str, tuple[str, str]] = {}
        for rule in rules:
            target = by_rule_id.get(rule.target_attr_id)
            if not target:
                continue
            vn = target.variable_name
            current = filled.get(vn)
            if not current:
                continue  # unfilled — apply_recommendation_rules' job, not this one
            if filled_source and filled_source.get(vn) in _NEVER_OVERRIDE:
                continue
            if rule.script is not None:
                if bml_eval is None:
                    continue
                allowed = bml_eval.allowed_values_for_script(rule.script, filled)
                if not allowed or len(allowed) != 1:
                    continue
                recommended_value = allowed[0]
            elif rule.condition_script is not None:
                if bml_eval is None:
                    continue
                fires = bml_eval.condition_holds(rule.condition_script, filled)
                if fires is not True:
                    continue
                recommended_value = rule.recommended_value
            else:
                if rule.conditions:
                    matched, _blocked = evaluate_declarative_conditions(
                        rule.conditions, filled_by_rule_id)
                    if matched is not True:
                        continue
                else:
                    if rule.condition_attr_id not in filled_by_rule_id:
                        continue
                    if not _condition_value_matches(
                        filled_by_rule_id[rule.condition_attr_id], rule.condition_value,
                        rule.condition_operator,
                    ):
                        continue
                recommended_value = rule.recommended_value
            if not _valid(recommended_value) or current.lower() == recommended_value.lower():
                continue
            # Same guard as apply_recommendation_rules: a "correction" back
            # to a value a DIFFERENT, currently-active constraint has
            # already excluded is not a correction — it's silently undoing
            # auto_fill's own correct fallback. Live regression: auto_fill
            # correctly fell back to "ESSENTIAL" once Hardware Version
            # activated a constraint excluding "ADVANCED", but this method
            # ran right after (same pass) and — seeing its own unrelated
            # condition (Solution Type) still held, with no constraint
            # awareness at all — "resynced" it straight back to the
            # excluded value, every single pass.
            allowed_for_target = (
                constrained_opts.get(target.entity_id) if constrained_opts else None
            )
            if allowed_for_target is not None and not any(
                recommended_value.lower() == v.lower() for v in allowed_for_target
            ):
                continue
            matched_display = next(
                (o.display_name for o in target.options
                 if o.item_value.lower() == recommended_value.lower()),
                recommended_value,
            )
            corrections[vn] = (recommended_value, matched_display)
        if corrections:
            logger.info(
                "cpq: resynced stale recommendation-governed attrs %s",
                list(corrections.keys()),
            )
        return corrections

    def apply_validation_rules(
        self,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        rules: list[ValidationRule],
        bml_eval: BmlEvaluator | None = None,
        filled_multi: dict[str, list[str]] | None = None,
    ) -> dict[str, str]:
        """Evaluate every ValidationRule's condition (script OR
        declarative — docs/CPQ_CONDITIONAL_REQUIRED_RULE_PLAN_2026_08_05.md)
        against the current filled state (Amendment 12). Returns
        {variable_name: message} for every rule whose condition currently,
        definitely holds — never on False or unknown (D2 "never guess": an
        unresolvable condition never fires a warning it can't actually
        back).

        Script-backed rules need bml_eval; bml_eval=None skips those only
        (same convention as apply_recommendation_rules/
        apply_constraint_rules) — declarative rules need no BML evaluator
        at all and are unaffected by bml_eval=None, same as
        apply_hiding_rules' own declarative branch.

        filled_multi — see apply_hiding_rules; only consulted for
        declarative conditions on a select_type=="multi" attribute.
        """
        if not rules:
            return {}
        by_id = self._attr_index(attrs)
        filled_by_rule_id = self._filled_by_rule_id(attrs, filled, filled_multi)
        warnings: dict[str, str] = {}
        for rule in rules:
            target = by_id.get(rule.target_attr_id)
            if not target:
                continue
            if rule.condition_script is not None:
                if bml_eval is None:
                    continue
                if bml_eval.condition_holds(rule.condition_script, filled) is True:
                    warnings[target.variable_name] = rule.message
            elif rule.conditions:
                matched, _blocked = evaluate_declarative_conditions(
                    rule.conditions, filled_by_rule_id)
                if matched is True:
                    warnings[target.variable_name] = rule.message
        return warnings

    # ── Constraint rule loader ────────────────────────────────────────────────

    def load_constraint_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[ConstraintRule]:
        """Constraint rules for this catalog — declarative AND script.

        See _load_value_rules for how rule semantics are classified (by
        each action's set_type, NOT by rule_type/action_type — neither
        matches real data in either ingested catalog). Script-form actions
        (function_id != -1) get the raw BML script attached; allowed values
        are derived at apply time by the BML evaluator from the current
        filled variables. If you also need recommendation rules, call
        load_recommendation_and_constraint_rules() instead to avoid
        fetching the same rule data twice.
        """
        _rec_rules, con_rules, _validation_rules, _extra_hiding_rules = (
            self._load_value_rules(workspace_id, catalog_prefix))
        return con_rules

    def build_bml_evaluator(self, workspace_id: int, catalog_prefix: str = "") -> BmlEvaluator:
        """BML evaluator over this workspace's BmFunction scripts.

        catalog_prefix — scopes to one ingested catalog when the workspace
        holds more than one product's XML export (BM-native function ids
        collide across catalogs the same way rule ids do). Also passed to
        the evaluator itself so its process-wide LLM-result cache (see
        bml._SHARED_SCRIPT_CACHE) can't cross-contaminate between catalogs
        or workspaces sharing a colliding function id.

        Tier-2 LLM fallback is gated by settings.bml_use_llm (default
        False) — see that field's docstring for why it's off by default.
        """
        _t0 = time.monotonic()
        logger.info(
            "cpq_step: build_bml_evaluator start workspace_id=%s catalog_prefix=%r",
            workspace_id, catalog_prefix,
        )
        try:
            scripts = get_cpq_rdb().fetch_function_scripts(workspace_id, catalog_prefix)
        except Exception:  # noqa: BLE001
            logger.debug("cpq: function script fetch failed", exc_info=True)
            scripts = {}
        logger.info(
            "cpq_step: build_bml_evaluator done elapsed_s=%.3f scripts=%d",
            time.monotonic() - _t0, len(scripts),
        )
        return BmlEvaluator(
            scripts, use_llm=get_settings().bml_use_llm,
            workspace_id=workspace_id, catalog_prefix=catalog_prefix,
        )

    def apply_constraint_rules(
        self,
        attrs: list[ConfigAttr],
        rules: list[ConstraintRule],
        filled: dict[str, str],
        bml_eval: BmlEvaluator | None = None,
        filled_multi: dict[str, list[str]] | None = None,
    ) -> dict[int, list[str]]:
        """Return {attr_entity_id: [allowed_item_values]} for attrs with active constraints.

        Multiple rules for the same target are intersected (AND semantics) so
        only values permitted by ALL active constraint rules remain valid.

        Script-backed rules (rule.script set) derive their allowed list from
        the BML evaluator using the current filled variables (keyed by
        variable_name — BML scripts compare variable names directly). An
        unknown script outcome (None) applies no constraint rather than
        allowing everything.

        filled_multi — see apply_hiding_rules; only consulted for
        declarative conditions on a select_type=="multi" attribute
        (operators "7"/"8").

        Empty-intersection fallback (docs/CPQ_MULTISELECT_AUTOFILL_
        OVERSELECTION_PLAN_2026_08_05.md's "Known remaining issue",
        explicit product decision 2026-08-05): confirmed live that some
        catalogs carry a genuine authoring gap — a constraint rule never
        given a counterpart for a newer product variant, unconditionally
        colliding with that variant's own (correct) constraint and zeroing
        the intersection. When that happens, rules that fired are grouped
        by their condition attribute set; each candidate group is scored
        by how many rules catalog-wide (the full `rules` list, not just
        those active this turn) reference that same condition attribute —
        confirmed live this cleanly separates a catalog's backbone
        discriminator (productSelectionProduct_all, 478 references in one
        real catalog) from an incidentally-referenced peripheral one
        (additionalSystemEnhancementFeatureType_astro, 3 references).
        Dropping the single group with the strictly lowest score resolves
        the conflict; a tie for lowest, or 2+ groups whose removal would
        each independently resolve it, is genuinely ambiguous and left
        empty rather than guessed. Never applied to script-backed rules
        (their conditions aren't a declarative attr set to group or score).
        """
        if not rules:
            return {}
        by_rule_id = self._attr_index(attrs)
        filled_by_rule_id = self._filled_by_rule_id(attrs, filled, filled_multi)
        constrained: dict[int, list[str]] = {}
        # target.entity_id -> [(condition_key, normalized_allowed_values, rule_name)]
        # for every rule that actually fired -- condition_key groups rules
        # sharing the same declarative condition attribute set; script-backed
        # rules get a per-rule-unique key so they're never grouped/dropped.
        contributions: dict[int, list[tuple[frozenset, list[str], str]]] = {}

        def _normalize(target: ConfigAttr, allowed: list[str]) -> list[str]:
            # docs/config_consistency_issues_2026-07-30.md — a raw catalog
            # rule's own authored allowed-value list can carry different
            # letter-casing than the attribute's real menu item_value
            # (confirmed live: the declarative rule "Constrain for
            # APXNEXTSINGLE & APXNEXTXNSINGLE" lists "700/800 MHz" while
            # every real menu item for this attribute is "700/800 MHZ" —
            # a genuine source-catalog authoring inconsistency, not a bug
            # in this parsing). Left uncorrected, this made a brand-new,
            # completely default APX NEXT Single Band order fail its own
            # BOM-gate stale-constraint check on the very first confirm,
            # every time — the default value was never actually invalid,
            # it just didn't case-exact-match the rule's own typo.
            # Normalize each allowed value back to its real catalog
            # item_value (case-insensitive lookup) before comparing/
            # intersecting, so a same-value-different-case rule entry
            # behaves exactly like the correctly-cased one would.
            by_lower_item_value = {o.item_value.lower(): o.item_value for o in target.options}
            return [by_lower_item_value.get(v.lower(), v) for v in allowed]

        def _intersect(target: ConfigAttr, allowed: list[str], condition_key: frozenset) -> None:
            normalized = _normalize(target, allowed)
            contributions.setdefault(target.entity_id, []).append(
                (condition_key, normalized, rule.rule_name))
            if target.entity_id in constrained:
                existing = set(constrained[target.entity_id])
                constrained[target.entity_id] = [v for v in normalized if v in existing]
            else:
                constrained[target.entity_id] = list(normalized)

        for rule in rules:
            target = by_rule_id.get(rule.target_attr_id)
            if target is None:
                continue
            if rule.script is not None:
                if bml_eval is None:
                    continue
                allowed = bml_eval.allowed_values_for_script(rule.script, filled)
                if allowed:
                    _intersect(target, allowed, frozenset({f"script:{rule.rule_name}"}))
                    rule_trace.record_fire(
                        rule_type="constraint", rule_id=rule.rule_name,
                        attr=target.variable_name, outcome=f"allowed={allowed}",
                        bml_tier="script",
                    )
                continue
            if rule.condition_script is not None:
                if bml_eval is None:
                    continue
                fires = bml_eval.condition_holds(rule.condition_script, filled)
                if fires is True:
                    _intersect(
                        target, rule.allowed_values,
                        frozenset({f"condition_script:{rule.rule_name}"}),
                    )
                    rule_trace.record_fire(
                        rule_type="constraint", rule_id=rule.rule_name,
                        attr=target.variable_name,
                        outcome=f"allowed={rule.allowed_values}", bml_tier="condition_script",
                    )
                continue  # False or unknown — never guess, no constraint applied
            if rule.conditions:
                matched, _blocked = evaluate_declarative_conditions(
                    rule.conditions, filled_by_rule_id)
                if matched is not True:
                    continue
                condition_key = frozenset(attr_id for attr_id, _value, _op in rule.conditions)
            else:
                if rule.condition_attr_id not in filled_by_rule_id:
                    continue
                if not _condition_value_matches(
                    filled_by_rule_id[rule.condition_attr_id], rule.condition_value,
                    rule.condition_operator,
                ):
                    continue
                condition_key = frozenset({rule.condition_attr_id})
            _intersect(target, rule.allowed_values, condition_key)
            rule_trace.record_fire(
                rule_type="constraint", rule_id=rule.rule_name,
                attr=target.variable_name, outcome=f"allowed={rule.allowed_values}",
            )

        # How catalog-wide "central" each condition attribute is to THIS
        # constraint ruleset — counted from the full `rules` list (every
        # declarative condition attr this ConstraintRule set ever
        # references), not just the ones that fired this turn. Purely
        # structural, derived from the real loaded rules, no hardcoded
        # attribute names: confirmed live this reliably separates a
        # catalog's backbone discriminator (e.g. the product-line
        # attribute nearly every "Constrain X for product Y" rule keys
        # off — 478 references in one real catalog) from an incidentally-
        # referenced peripheral one (an unrelated feature-option
        # attribute two old rules happened to key off — 3 references,
        # same catalog). Only actually consulted below when an empty
        # intersection needs resolving; computed unconditionally here
        # (cheap, one pass over `rules`) to avoid conditional-definition
        # scoping hazards.
        attr_ref_count: dict[int, int] = {}
        for r in rules:
            ids = (
                {a for a, _v, _op in r.conditions} if r.conditions
                else ({r.condition_attr_id} if r.condition_script is None and r.script is None else set())
            )
            for attr_id in ids:
                attr_ref_count[attr_id] = attr_ref_count.get(attr_id, 0) + 1

        def _centrality(condition_key: frozenset) -> int:
            return max((attr_ref_count.get(a, 0) for a in condition_key), default=0)

        for entity_id, rows in contributions.items():
            if constrained.get(entity_id) or len(rows) < 2:
                continue
            groups: dict[frozenset, list[tuple[list[str], str]]] = {}
            for condition_key, normalized, rule_name in rows:
                groups.setdefault(condition_key, []).append((normalized, rule_name))
            if len(groups) < 2:
                continue  # everything shares one condition -- genuinely all-or-nothing
            resolved_by_dropping: list[tuple[frozenset, list[str]]] = []
            for dropped_key in groups:
                kept_sets = [
                    set(normalized)
                    for key, entries in groups.items() if key != dropped_key
                    for normalized, _rule_name in entries
                ]
                candidate = set.intersection(*kept_sets) if kept_sets else set()
                if candidate:
                    resolved_by_dropping.append((dropped_key, sorted(candidate)))
            if not resolved_by_dropping:
                continue
            # Prefer dropping whichever candidate group's condition
            # attribute is LEAST central catalog-wide — only when that
            # minimum is unambiguous (a strict minimum, not tied with
            # another candidate group). A tie means two structurally
            # equally-plausible resolutions exist; never guess between them.
            scored = sorted(
                ((_centrality(key), key, candidate) for key, candidate in resolved_by_dropping),
            )
            target_name = by_rule_id[entity_id].variable_name if entity_id in by_rule_id else entity_id
            if len(scored) > 1 and scored[0][0] == scored[1][0]:
                logger.warning(
                    "cpq: constraint intersection for %s is empty and 2+ "
                    "equally-central rule-groups could each resolve it — "
                    "ambiguous, left empty rather than guessing which one wins",
                    target_name,
                )
                continue
            _score, dropped_key, candidate = scored[0]
            dropped_names = sorted({rule_name for _normalized, rule_name in groups[dropped_key]})
            logger.warning(
                "cpq: constraint intersection for %s was empty across all "
                "active rules; dropped least catalog-central conflicting "
                "rule(s) %s (condition attrs %s, %d catalog-wide reference(s)) "
                "to resolve to %s — docs/CPQ_MULTISELECT_AUTOFILL_"
                "OVERSELECTION_PLAN_2026_08_05.md empty-intersection fallback",
                target_name, dropped_names, sorted(dropped_key), _score, candidate,
            )
            constrained[entity_id] = candidate

        if constrained:
            names = [by_rule_id[eid].variable_name for eid in constrained if eid in by_rule_id]
            logger.info("cpq: constraint rules active for %s", names)
        return constrained

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
    ) -> list[dict[str, Any]]:
        """Cross-check `filled` against each rule type's OWN independently
        computed result — NOT a self-referential re-derivation of the same
        data that produced `filled` in the first place (see
        docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §1 for why a check
        against attr_by_vn/options would be tautological and useless).

        Three checks, one per rule type — all reuse the SAME apply_* methods
        already used to build the payload, so BML-script-backed rules
        (rule.script / rule.condition_script) are covered automatically,
        with zero new script-evaluation code (§4's docstring):

          - hiding:         attr is filled AND an active hiding rule matches
                             it right now — it should never have been kept.
          - constraint:     attr's filled value is not in the currently
                             active allowed-values set for it (stale/
                             pre-cascade value that should have been cleared).
          - recommendation: attr not filled via "user" source, whose
                             recommendation rule condition IS satisfied, but
                             the filled value does not match recommended_value
                             (confirmed live this session: the "invalidated —
                             re-evaluating" cascade note that changes nothing).

        Returns a list of {"attr", "value", "rule_type", "issue"} dicts —
        empty when everything is consistent. Never raises; a rule whose
        script outcome is "unknown" is simply skipped for that check (never
        guess a bug that isn't there).
        """
        issues: list[dict[str, Any]] = []
        by_vn = {a.variable_name: a for a in attrs}

        _visible, _msgs, hidden_vns = self.apply_hiding_rules(
            attrs, filled, hiding_rules, bml_eval, filled_multi=filled_multi)
        for vn in hidden_vns:
            if filled.get(vn):
                issues.append({
                    "attr": vn, "value": filled[vn], "rule_type": "hiding",
                    "issue": "filled but an active hiding rule matches",
                })

        constrained_opts = self.apply_constraint_rules(
            attrs, con_rules, filled, bml_eval, filled_multi=filled_multi)
        for vn, value in filled.items():
            attr = by_vn.get(vn)
            allowed = constrained_opts.get(attr.entity_id) if attr else None
            if allowed is not None and value not in allowed:
                issues.append({
                    "attr": vn, "value": value, "rule_type": "constraint",
                    "issue": f"value not in active allowed set {allowed}",
                })

        by_rule_id = self._attr_index(attrs)
        filled_by_rule_id = self._filled_by_rule_id(attrs, filled, filled_multi)
        for rule in rec_rules:
            target = by_rule_id.get(rule.target_attr_id)
            if not target or target.variable_name not in filled:
                continue
            vn = target.variable_name
            if filled_source and filled_source.get(vn) == "user":
                # A customer's deliberate override is not an inconsistency
                # even if it now disagrees with a currently-satisfied
                # recommendation — see docstring's "not filled via 'user'
                # source" contract, which this param actually enforces.
                continue
            condition_met: bool | None
            if rule.script is not None:
                if bml_eval is None:
                    continue
                allowed = bml_eval.allowed_values_for_script(rule.script, filled)
                condition_met = bool(allowed) and len(allowed) == 1
                recommended = allowed[0] if condition_met else None
            elif rule.condition_script is not None:
                if bml_eval is None:
                    continue
                condition_met = bml_eval.condition_holds(rule.condition_script, filled) is True
                recommended = rule.recommended_value
            else:
                if rule.conditions:
                    matched, _blocked = evaluate_declarative_conditions(
                        rule.conditions, filled_by_rule_id)
                    condition_met = matched is True
                else:
                    current_val = filled_by_rule_id.get(rule.condition_attr_id)
                    condition_met = (
                        current_val is not None
                        and _condition_value_matches(
                            current_val, rule.condition_value, rule.condition_operator
                        )
                    )
                recommended = rule.recommended_value
            if condition_met and recommended is not None and filled[vn].lower() != recommended.lower():
                issues.append({
                    "attr": vn, "value": filled[vn], "rule_type": "recommendation",
                    "issue": f"condition met but value != recommended '{recommended}'",
                })

        return issues

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
        """Run hide → recommend → constrain → auto-fill until state is stable.

        workspace_id/catalog_prefix — passed straight through to auto_fill's
        real-Data-Table fallback (see its own docstring); `None` (the
        default) keeps every existing caller's behavior unchanged.

        display_order — docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2d:
        passed straight through to every internal `auto_fill` call so the
        default-value/first-available skip gate applies on EVERY pass, not
        just the caller's own separate, final `auto_fill` call in
        ask_api.py. Without this, an attr could get a "default"-sourced
        value locked in during this loop's own early passes (before the
        caller's final call ever runs) — that value then looks like
        "already filled in a prior turn" to every later pass (including
        the final one), which only re-validates against constraints, never
        re-derives from scratch, so the §2d skip never gets a chance to
        apply. Confirmed live: exactly this happened for 8 real attrs
        before this fix. `None` keeps today's behavior unchanged.
        rule_conflict_order — docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md
        §2b: the catalog's FULL layout document order
        (`_load_layout_full_order`), passed straight through to
        `rank_rules_by_specificity`. `None` keeps today's dependency-
        graph-depth ranking unchanged.

        Each pass:
          1. Auto-fill (hints + defaults + first-option, with active constraints)
          2. Apply hiding rules → update visible attrs
          3. Apply recommendation rules → add new auto-fills
          4. Apply constraint rules → update constrained option sets

        Iterates until neither the filled set nor the visible attr set changes.
        filled_source (variable_name → provenance) and filled_multi
        (variable_name → selected item_values, for select_type=="multi"
        attrs) are updated in place when supplied. Returns (visible_attrs,
        filled, display_filled, constrained_opts).

        skip_always_ask — passed straight through to auto_fill (see its
        docstring); compute via resolve_always_ask_skips() once per turn at
        the caller, where workspace_id/catalog_prefix are available.
        """
        _MAX_LOOPS = 8
        display_filled: dict[str, str] = {}
        constrained_opts: dict[int, list[str]] = {}
        sources = filled_source if filled_source is not None else {}
        multi = filled_multi if filled_multi is not None else {}
        dropped = dropped_multi if dropped_multi is not None else {}

        # docs/CPQ_RULE_SPECIFICITY_EXECUTION_ORDER_PLAN_2026_08_04.md —
        # ranked ONCE here against the full, pre-loop `attrs` (never the
        # loop-local `attrs` below, which apply_hiding_rules reassigns to a
        # shrinking subset every pass) so same-target hiding/recommendation
        # conflicts resolve via provable specificity instead of whatever
        # order fetch_rules()/fetch_value_rules() happened to return.
        hiding_rules, rec_rules, con_rules = self.rank_rules_by_specificity(
            attrs, hiding_rules, rec_rules, con_rules, display_order=rule_conflict_order)

        # Shared across every pass of this loop (and every auto_fill call
        # within it) so the Data Table resolver's per-workspace table scan
        # (data_table_resolver._load_all_tables) runs once per /ask turn
        # instead of once per governed attribute -- see auto_fill's own
        # _dt_cache param and CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_PROOF
        # §11-§12 for the live-measured cost of the uncached version.
        dt_cache: dict[tuple[int, str], tuple] = {}

        # cpq_step start/done — the per-pass "cpq_perf: pass N total ...s"
        # lines below already cover per-pass granularity; this brackets the
        # WHOLE fixed-point loop (all up to _MAX_LOOPS=8 passes) so a hang
        # anywhere inside shows up as "start" with no matching "done" for
        # this run_id, rather than only inferring it from a missing pass log.
        _loop_t0 = time.monotonic()
        logger.info("cpq_step: evaluate_rules_loop start max_passes=%d", _MAX_LOOPS)
        # pass_num pre-seeded defensively -- the "done" log below reads it
        # after the loop, which is only safe today because _MAX_LOOPS is a
        # positive constant guaranteeing at least one iteration (PR #200
        # review flagged this as fragile, not currently broken).
        pass_num = -1
        for pass_num in range(_MAX_LOOPS):
            _pass_t0 = time.monotonic()
            rule_trace.bind_pass(pass_num)
            prev_filled_keys = set(filled.keys())
            prev_visible_ids = {a.entity_id for a in attrs}

            # Amendment 18 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md):
            # warm the shared Tier-2 cache CONCURRENTLY for every hiding
            # rule's script before apply_hiding_rules runs its own
            # sequential loop below — live-measured on the real
            # CommandCentral Aware catalog, 823 distinct hiding-rule
            # scripts needed Tier-2 in a single turn; evaluated one at a
            # time that took 25+ minutes. apply_hiding_rules itself is
            # UNCHANGED — it still calls bml_eval.hide_for_script(...) per
            # rule in order; every one of those calls now just hits the
            # cache this just populated, instead of making a fresh network
            # call. A rule this prefetch missed simply falls through to its
            # normal sequential call, exactly as if this line didn't exist.
            if bml_eval is not None:
                bml_eval.prefetch_tier2(
                    self._bml_prefetch_requests(hiding=hiding_rules, filled=filled))

            # docs/CPQ_HIDDEN_MASTER_STRING_HIDING_RULE_GAP_PLAN_2026_08_10.md
            # -- populate the one shared variable dozens of hiding-rule
            # scripts check membership in, via the real ingested
            # attrSequence Data Table, before apply_hiding_rules runs those
            # scripts below.
            #
            # docs/CPQ_HIDDEN_MASTER_STRING_STALE_AFTER_CASCADE_PLAN_2026_08_
            # 10.md -- recompute whenever the two real inputs this value is
            # derived from (product, base model) have changed since the
            # cached value was computed, not just when the key is merely
            # absent. Confirmed live: a mid-conversation Hardware Version
            # change cascades productSelectionProduct_all to a new value,
            # but the master string cached for the OLD product persisted --
            # every hiding rule keyed on it (e.g. "Hide Carrier Selection if
            # no values available (portables)") then evaluated against the
            # wrong product's data, incorrectly hid carrierSelectionMulti
            # Select_astro, and its real value got cleared along with the
            # hide. Tracking key kept as a plain string (not a tuple) --
            # `filled`/session.filled round-trips through JSON as
            # session_data between turns, and a tuple would silently become
            # a list on deserialization, breaking the equality check on the
            # very next turn.
            _hidden_ms_key = (
                filled.get("productSelectionProduct_all", "") + "\x1f"
                + filled.get("modelSelectionbaseModel_astro", "")
            )
            if (
                "hiddenMasterStringForAstroPortable_astro" not in filled
                or filled.get("_hiddenMasterStringForAstroPortable_astro_computed_for")
                != _hidden_ms_key
            ):
                _hidden_ms = self._compute_hidden_master_string(
                    filled, workspace_id, catalog_prefix, dt_cache, attrs=attrs,
                )
                if _hidden_ms is not None:
                    filled["hiddenMasterStringForAstroPortable_astro"] = _hidden_ms
                    filled["_hiddenMasterStringForAstroPortable_astro_computed_for"] = _hidden_ms_key

            # Apply hiding rules first so auto_fill only fills visible attrs
            attrs, _msgs, hidden_vns = self.apply_hiding_rules(
                attrs, filled, hiding_rules, bml_eval=bml_eval, filled_multi=multi)

            # Strip values ONLY for attrs an explicit hiding rule removed from
            # view. Popping everything not currently visible (the old
            # behaviour) also destroyed confirmed answers whose attr merely
            # wasn't part of this load — dropping user data from the payload.
            for k in hidden_vns:
                filled.pop(k, None)
                display_filled.pop(k, None)
                sources.pop(k, None)
                multi.pop(k, None)

            # Real Oracle CPQ attrSequence Data Table narrowing -- an attr
            # confidently NOT part of the active base model per real
            # ingested data is suppressed the same way an explicit hiding
            # rule removes one from view (docs/CPQ_CARRIER_WIRELESS_
            # FREQBAND_DATA_GAP_PROOF_2026_08_07.md §13-§14). `None`/no
            # workspace_id is a no-op, unchanged from before this existed.
            _t0 = time.monotonic()
            attrs, suppressed_vns = self._suppress_ungoverned_attrs(
                attrs, filled, workspace_id, catalog_prefix, dt_cache,
            )
            logger.info(
                "cpq_perf: _suppress_ungoverned_attrs took %.3fs pass=%d attrs=%d suppressed=%d",
                time.monotonic() - _t0, pass_num, len(attrs), len(suppressed_vns),
            )
            for k in suppressed_vns:
                filled.pop(k, None)
                display_filled.pop(k, None)
                sources.pop(k, None)
                multi.pop(k, None)

            governed_ids = self.governed_target_ids(attrs, hiding_rules, rec_rules, con_rules)
            rule_ids = self.rule_governed_ids(attrs, hiding_rules, rec_rules, con_rules)

            # docs/CPQ_AUTO_FILL_TIER2_PREFETCH_GAP_PLAN_2026_08_10.md --
            # auto_fill's own _satisfied_recommendation helper calls
            # bml_eval.allowed_values_for_script/condition_holds per
            # (unfilled attr, targeting recommendation rule) pair -- the
            # same Tier-1/Tier-2 machinery apply_recommendation_rules uses,
            # but BEFORE the prefetch below (which only warms the cache for
            # apply_recommendation_rules/apply_constraint_rules' own later
            # calls). Confirmed live: on pass 0, when the most attrs are
            # still unfilled, this uncovered gap made auto_fill itself take
            # 20-21s of serial Tier-2 network round-trips. Warming against
            # the PRE-auto_fill filled state here is safe and non-wasteful
            # even though the same rules get prefetched again below against
            # the POST-auto_fill state -- prefetch_tier2 dedupes and caches
            # by (script, variables), so a script whose referenced variables
            # didn't change between the two prefetches is simply a cache
            # hit the second time.
            if bml_eval is not None:
                bml_eval.prefetch_tier2(self._bml_prefetch_requests(
                    attrs=attrs, rec=rec_rules, filled=filled))

            _t0 = time.monotonic()
            filled, display_filled, _ = self.auto_fill(
                attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
                filled_source=sources, governed_ids=governed_ids,
                already_filled_multi=multi, dropped_multi=dropped,
                rule_governed_ids=rule_ids, country=country, rec_rules=rec_rules,
                negated_vns=negated_vns, skip_always_ask=skip_always_ask,
                bml_eval=bml_eval, display_order=display_order,
                workspace_id=workspace_id, catalog_prefix=catalog_prefix,
                _dt_cache=dt_cache, hiding_rules=hiding_rules,
            )
            logger.info(
                "cpq_perf: auto_fill took %.3fs pass=%d", time.monotonic() - _t0, pass_num,
            )

            # Real Data Table pair-consistency check -- two attributes
            # auto_fill resolved INDEPENDENTLY can each be individually
            # legal while their combination is one the real catalog never
            # allows (docs/CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_PROOF_
            # 2026_08_07.md §13-§14). Clearing both lets the next pass
            # re-resolve them together instead of leaving a structurally-
            # invalid combination locked into the payload.
            _t0 = time.monotonic()
            inconsistent_vns = self._invalidate_inconsistent_paired_values(
                filled, sources, workspace_id, catalog_prefix, dt_cache,
            )
            logger.info(
                "cpq_perf: _invalidate_inconsistent_paired_values took %.3fs pass=%d inconsistent=%s",
                time.monotonic() - _t0, pass_num, sorted(inconsistent_vns),
            )
            for k in inconsistent_vns:
                filled.pop(k, None)
                display_filled.pop(k, None)
                sources.pop(k, None)
                multi.pop(k, None)

            # Same prefetch, now for recommendation/constraint rule scripts
            # against the POST-auto_fill state (auto_fill can itself have
            # just resolved values these scripts depend on) — warms the
            # cache for apply_recommendation_rules/apply_constraint_rules
            # below, both still unchanged, still sequential, now cache hits.
            if bml_eval is not None:
                bml_eval.prefetch_tier2(self._bml_prefetch_requests(
                    attrs=attrs, rec=rec_rules, con=con_rules, filled=filled))

            new_fills = self.apply_recommendation_rules(
                attrs, filled, rec_rules, bml_eval=bml_eval, filled_multi=multi,
                constrained_opts=constrained_opts,
            )
            if new_fills:
                # Route multi-select targets to `multi`, not `filled` — same
                # reasoning as auto_fill's final assignment block: this is
                # yet another path that can hand a value to a select_type
                # =="multi" attr, and build_payload only serializes an
                # attr's value as an array when it's stored in filled_multi.
                by_vn_for_type = {a.variable_name: a for a in attrs}
                for k, (iv, d) in new_fills.items():
                    tgt = by_vn_for_type.get(k)
                    if tgt is not None and tgt.select_type == "multi":
                        multi[k] = [iv]
                    else:
                        filled[k] = iv
                    display_filled[k] = d
                    # Force-set, not setdefault: `k` only ever reaches here
                    # via the truthy (not `in filled`) check above, so any
                    # existing tag is either absent or D4's empty-value
                    # "user"-cleared marker being genuinely overridden by a
                    # real rule firing — never a real prior value's tag.
                    sources[k] = "rule"

            # docs/config_consistency_issues_2026-07-30.md issue 6 (FedRAMP)
            # — a recommendation-governed attr the ENGINE already filled
            # (never the customer's own choice) must not be permanently
            # locked in if its driving attribute's value changes on a LATER
            # pass of this same loop (e.g. auto_fill initially claimed it by
            # first-by-order before the real condition could be checked).
            # Scoped to filled_source != user/hint/cascade — see
            # resync_stale_recommendations' own docstring for why that
            # boundary is safe to cross where find_rule_inconsistencies
            # deliberately only logs.
            _resynced = self.resync_stale_recommendations(
                attrs, filled, sources, rec_rules, bml_eval=bml_eval, filled_multi=multi,
                constrained_opts=constrained_opts,
            )
            if _resynced:
                for k, (iv, d) in _resynced.items():
                    filled[k] = iv
                    display_filled[k] = d
                    sources[k] = "rule"

            constrained_opts = self.apply_constraint_rules(
                attrs, con_rules, filled, bml_eval=bml_eval, filled_multi=multi,
            )
            _t0 = time.monotonic()
            self._apply_series_mapping_exclusions(
                attrs, constrained_opts, filled, workspace_id, catalog_prefix, dt_cache,
            )
            logger.info(
                "cpq_perf: _apply_series_mapping_exclusions took %.3fs pass=%d",
                time.monotonic() - _t0, pass_num,
            )

            logger.info(
                "cpq_perf: pass %d total %.3fs resynced=%s inconsistent=%d",
                pass_num, time.monotonic() - _pass_t0, bool(_resynced), len(inconsistent_vns),
            )
            if (not _resynced
                    and not inconsistent_vns
                    and set(filled.keys()) == prev_filled_keys
                    and {a.entity_id for a in attrs} == prev_visible_ids):
                break

        logger.info(
            "cpq_step: evaluate_rules_loop done elapsed_s=%.3f passes=%d",
            time.monotonic() - _loop_t0, pass_num + 1,
        )
        return attrs, filled, display_filled, constrained_opts

    @staticmethod
    def _bml_prefetch_requests(
        filled: dict[str, str],
        attrs: list[ConfigAttr] | None = None,
        hiding: list[HidingRule] | None = None,
        rec: list[RecommendationRule] | None = None,
        con: list[ConstraintRule] | None = None,
    ) -> list[tuple[str, str, dict[str, str], int | None]]:
        """Build BmlEvaluator.prefetch_tier2 requests for every script-backed
        rule in the given rule sets, against the CURRENT `filled` state.

        Amendment 18 (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md): mirrors
        exactly what apply_hiding_rules/apply_recommendation_rules/
        apply_constraint_rules will each independently ask
        hide_for_script/condition_holds/allowed_values_for_script for —
        same rule fields, same `filled` argument, no cache_id (those call
        sites never pass one either, so both sides key on hash(script)).
        Coverage gaps here only cost speed, never correctness: an
        uncovered rule's script just isn't pre-warmed and falls through to
        its normal sequential call, exactly as if this method didn't run.

        `rec` also mirrors apply_recommendation_rules' own "already filled"
        skip (needs `attrs` to resolve target_attr_id -> variable_name) so
        a prefetch doesn't burn concurrent Tier-2 calls on rules that loop
        will never actually consult this pass. `hiding`/`con` have no such
        skip in their own apply_* methods (visibility and allowed-value
        narrowing both apply regardless of current fill state), so none is
        replicated here either.
        """
        reqs: list[tuple[str, str, dict[str, str], int | None]] = []
        for rule in (hiding or []):
            if rule.script is not None:
                reqs.append(("hide", rule.script, filled, None))
        if rec:
            by_rule_id = CpqEngine._attr_index(attrs or [])
            for rule in rec:
                target = by_rule_id.get(rule.target_attr_id)
                if not target or filled.get(target.variable_name):
                    continue
                if rule.script is not None:
                    reqs.append(("values", rule.script, filled, None))
                elif rule.condition_script is not None:
                    reqs.append(("cond", rule.condition_script, filled, None))
        for rule in (con or []):
            if rule.script is not None:
                reqs.append(("values", rule.script, filled, None))
            elif rule.condition_script is not None:
                reqs.append(("cond", rule.condition_script, filled, None))
        return reqs

    # ── Context sentence builder ──────────────────────────────────────────────

    def build_context_sentence(
        self,
        pending_attr: ConfigAttr,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        display_filled: dict[str, str],
        hiding_rules: list[HidingRule],
        rec_rules: list[RecommendationRule],
    ) -> str:
        """Explain WHY this attribute is being asked, based on fired rules.

        Returns a sentence like "Since X was set to Y, we now need Z." or ""
        when no rule relationship is found (attribute is independently required).
        """
        by_rule_id = self._attr_index(attrs)
        pending_ids = {pending_attr.entity_id}
        if pending_attr.source_id is not None:
            pending_ids.add(pending_attr.source_id)

        # A show-type hiding rule revealed this attr
        for rule in hiding_rules:
            if rule.target_attr_id not in pending_ids or rule.hide:
                continue
            cond_attr = by_rule_id.get(rule.condition_attr_id)
            if cond_attr and cond_attr.variable_name in filled:
                disp_val = display_filled.get(
                    cond_attr.variable_name, filled[cond_attr.variable_name]
                )
                return (
                    f"Since we locked in **{disp_val}**, "
                    f"please choose the **{pending_attr.display_label}**."
                )

        # A recommendation rule targeted this attr (but had multiple valid options)
        for rule in rec_rules:
            if rule.target_attr_id not in pending_ids:
                continue
            cond_attr = by_rule_id.get(rule.condition_attr_id)
            if cond_attr and cond_attr.variable_name in filled:
                disp_val = display_filled.get(
                    cond_attr.variable_name, filled[cond_attr.variable_name]
                )
                return (
                    f"Since we locked in **{disp_val}**, "
                    f"please choose the **{pending_attr.display_label}**."
                )

        return ""

    # ── Auto-fill ─────────────────────────────────────────────────────────────

    @staticmethod
    def rule_governed_ids(
        attrs: list[ConfigAttr],
        hiding_rules: list[HidingRule],
        rec_rules: list[RecommendationRule],
        con_rules: list[ConstraintRule],
    ) -> set[int]:
        """Entity ids of attrs targeted by at least one loaded rule.

        D2 (CPQ_CASCADE_CONVERSATION_PLAN.md §2): an attribute only counts as
        a "dependent variable" eligible for default-or-first auto-fill if a
        hiding, recommendation, or constraint rule actually targets it —
        everything else keeps the existing ask-the-user safeguard (Issue 6).
        This is the strict subset `auto_fill` tags `filled_source="rule"`;
        see `governed_target_ids` for the wider Phase N eligibility set.
        """
        by_rule_id = CpqEngine._attr_index(attrs)
        governed: set[int] = set()
        for rule in hiding_rules:
            target = by_rule_id.get(rule.target_attr_id)
            if target:
                governed.add(target.entity_id)
        for rule in rec_rules:
            target = by_rule_id.get(rule.target_attr_id)
            if target:
                governed.add(target.entity_id)
        for rule in con_rules:
            target = by_rule_id.get(rule.target_attr_id)
            if target:
                governed.add(target.entity_id)
        return governed

    @staticmethod
    def product_label_noise_vns(
        attrs: list[ConfigAttr],
        hiding_rules: list[HidingRule],
        rec_rules: list[RecommendationRule],
        con_rules: list[ConstraintRule],
    ) -> set[str]:
        """Variable names of "Product"-labeled attrs that are genuinely
        irrelevant noise once `session.model_leaf_resolved` is True — the
        CommandCentral-style case Amendment 10 was built for, where a
        generic "Product" attr carries no rule of its own and the real
        model identity travels entirely through the resolved bm_catalog
        leaf instead.

        Deliberately NOT every attr labeled "Product" — live-confirmed bug
        (2026-07-28): APX Next's order text ("Order APX Next Radios...")
        also matches one of the workspace's catalog leaf candidates in the
        ambiguous-multi-leaf resolution path, setting model_leaf_resolved
        True for APX Next as well — but unlike CommandCentral, APX Next's
        own "Product" attr (productSelectionProduct_all) IS a genuine,
        rule-governed decision (a real constraint script narrows its
        options by Hardware Version). The blanket "drop every Product-
        labeled attr" rule silently dropped it from `pending` AND the
        payload entirely, with no value ever collected. Scoping to
        `rule_governed_ids` (a purely structural signal — which rules
        already target which attrs, independent of current filled state)
        distinguishes "truly noise, no rule cares about this" from "a real
        rule narrows this, it must still be asked."
        """
        governed = CpqEngine.rule_governed_ids(attrs, hiding_rules, rec_rules, con_rules)
        return {
            a.variable_name for a in attrs
            if a.display_label.strip().lower() == "product"
            and a.entity_id not in governed
        }

    @staticmethod
    def _normalized_label_stem(label: str) -> str:
        """Lowercase, whitespace-collapsed, singular-ized display label —
        used only to detect whether two attrs are labeled as the "same"
        real-world concept (e.g. "Frequency Bands" and "Frequency Band"),
        never to identify a specific attribute by name."""
        s = re.sub(r"\s+", " ", label.strip().lower())
        if s.endswith("s") and not s.endswith("ss"):
            s = s[:-1]
        return s

    # Explicit, disclosed exception to the generic label-stem detector
    # below — see exclusive_sibling_family_exclusions' docstring for why
    # this pair specifically cannot be found by label similarity, and the
    # live evidence establishing it belongs here anyway. Catalog-specific
    # by necessity (this concept has no other derivable signal in the
    # ingested data), NOT a general mechanism — kept to this one pair,
    # added only after direct confirmation, not silently.
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
    ) -> tuple[set[str], list[ConfigAttr]]:
        """Generic (no catalog/attribute names hardcoded) detector for a gap
        this engine can hit on ANY catalog: two attrs sharing the same
        real-world concept (near-identical display label, e.g. "Frequency
        Bands" vs "Frequency Band"), one select_type=="multi" and the other
        not, that BOTH ended up filled in the same turn — meaning no
        catalog hiding rule actually excluded either one for the current
        product (confirmed live on the APX Next catalog, docs/
        config_consistency_issues_2026-07-30.md Issue 5: the active hiding
        rule for this catalog's single-select sibling omits some product
        values entirely, so it stays visible and gets an unconditional
        default_value even when the multi-select sibling is the real
        governing attribute for that product).

        Only acts when the single-select sibling's value came from a
        NON-customer-confirmed provenance — an unconditional XML
        default_value, an engine-derived recommendation, or the
        conservative auto/first-option fallback (filled_source in
        {"default", "rule", "auto"}) — never "user"/"hint"/"cascade", so a
        genuine customer-confirmed or customer-triggered value is never
        second-guessed. Widened beyond a bare "default" check (confirmed
        live: this catalog's single-select sibling is actually populated by
        a shared-input RECOMMENDATION rule — tagged source "rule" — not a
        bare XML default_value, so a "default"-only check never caught it).

        `all_attrs` (docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_
        2026_08_05.md follow-up) — the label-stem grouping below only
        trusts a pair when EXACTLY 2 attrs share that stem, specifically
        so a genuinely ambiguous 3+-way label collision is never guessed.
        That size check is meaningless if it only sees `attrs` (the
        DYNAMICALLY hiding-filtered, currently-visible set): confirmed
        live, a real catalog reuses the identical display label "Service
        Type" across 4 semantically UNRELATED attributes (general service
        type, related-services type, DMS coverage plan, RSM warranty
        type); when a hiding rule happens to leave only 2 of the 4
        visible this turn, the size-2 check wrongly treated them as a
        genuine near-duplicate pair — the same false-positive class this
        check exists to prevent, just reached via visibility instead of
        catalog authoring. Groups by stem over `all_attrs` (the full,
        pre-hiding catalog list) when given; defaults to `attrs` (old
        behavior, unchanged) when omitted, so every existing caller/test
        is unaffected.

        Returns (vns_to_strip_from_filled, attrs_to_add_to_pending) — the
        multi-select sibling is asked instead of silently guessing which
        half applies. Empty on any catalog without this exact shape.
        """
        _WEAK_SOURCES = {"default", "rule", "auto"}
        by_vn = {a.variable_name: a for a in attrs}
        stem_universe = all_attrs if all_attrs is not None else attrs
        by_stem: dict[str, list[ConfigAttr]] = {}
        for a in stem_universe:
            by_stem.setdefault(self._normalized_label_stem(a.display_label), []).append(a)
        groups: list[list[ConfigAttr]] = list(by_stem.values())

        # Explicit, disclosed exception — NOT a generic mechanism. The
        # label-stem detector above provably cannot pair these two: live-
        # confirmed the display labels are "Wireless Carrier" vs "Carrier
        # Selection" (zero shared tokens), yet they exhibit the EXACT same
        # wrong-sibling bug as the generic-detected Frequency Band pair —
        # confirmed live: wirelessCarrier_astro ends up with a value
        # (e.g. "ATT/FIRSTNET", itself a real, valid option on BOTH
        # attributes' overlapping menus, so bom_gate's provenance check
        # never flags it) while carrierSelectionMultiSelect_astro — the
        # real governing multi-select for this concept — stays empty.
        # Named explicitly here (per direct approval) rather than silently
        # extending the generic label heuristic to something it can't
        # actually detect.
        for vn_a, vn_b in self._KNOWN_SIBLING_PAIRS:
            attr_a, attr_b = by_vn.get(vn_a), by_vn.get(vn_b)
            if attr_a is not None and attr_b is not None:
                groups.append([attr_a, attr_b])

        to_strip: set[str] = set()
        to_ask: list[ConfigAttr] = []
        for group in groups:
            if len(group) != 2:
                continue
            multi = [a for a in group if a.select_type == "multi"]
            single = [a for a in group if a.select_type != "multi"]
            if len(multi) != 1 or len(single) != 1:
                continue
            multi_attr, single_attr = multi[0], single[0]
            if multi_attr.variable_name not in by_vn:
                # The multi-select sibling only exists in `all_attrs` (the
                # full, pre-hiding catalog list) — a real hiding rule has
                # decided it does NOT apply this turn (confirmed live: "Hide
                # Frequency Band Model Selection Attribute for APX NEXT All
                # Band model" correctly hides modelSelectionFrequencyBandMsl_
                # astro for that product). There is no more-specific answer
                # to defer to, so the single-select's value — weak-sourced
                # or not — is left alone rather than stripped for nothing;
                # stripping it here previously resurrected a question the
                # engine's own hiding-rule evaluation had already, correctly,
                # decided to never ask.
                continue
            single_has_value = single_attr.variable_name in filled
            multi_has_value = bool(filled_multi.get(multi_attr.variable_name))
            if (
                single_has_value and not multi_has_value
                and filled_source.get(single_attr.variable_name) in _WEAK_SOURCES
            ):
                to_strip.add(single_attr.variable_name)
                to_ask.append(multi_attr)
        return to_strip, to_ask

    def enforce_exclusive_sibling_families(
        self,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]],
        filled_source: dict[str, str],
        display_filled: dict[str, str],
        pending: list[ConfigAttr],
        all_attrs: list[ConfigAttr] | None = None,
    ) -> list[ConfigAttr]:
        """Apply `exclusive_sibling_family_exclusions`: strip the weakly-
        sourced single-select sibling from `filled` (mutated in place) and
        add its multi-select sibling to `pending` if nothing has already
        filled or asked it. Returns the updated pending list.

        `all_attrs` — see exclusive_sibling_family_exclusions' docstring;
        pass the full, pre-hiding catalog attr list so the label-stem
        pairing check isn't fooled by a multi-way label collision that
        happens to look like a 2-attr pair only because hiding rules left
        just 2 of the real N visible this turn."""
        to_strip, to_ask = self.exclusive_sibling_family_exclusions(
            attrs, filled, filled_multi, filled_source, all_attrs=all_attrs,
        )
        if not to_strip:
            return pending
        for vn in to_strip:
            filled.pop(vn, None)
            display_filled.pop(vn, None)
            filled_source.pop(vn, None)
        pending = [a for a in pending if a.variable_name not in to_strip]
        pending_vns = {a.variable_name for a in pending}
        for attr in to_ask:
            # `to_ask` is already guaranteed visible-this-turn by
            # exclusive_sibling_family_exclusions (it only pairs a multi-
            # select sibling that's present in `attrs`, the visible list —
            # see that function's docstring for the hidden-sibling
            # regression this closes). Truthiness check (not mere key
            # presence) is deliberate here —
            # see test_enforce_still_asks_when_multi_sibling_has_an_empty_
            # placeholder: a governing multi-select sibling this mechanism
            # just decided IS the real answer for this concept must still
            # be asked even if auto_fill left an empty-list placeholder for
            # it, because THIS mechanism's whole point is that nobody has
            # actually confirmed the real concept yet. (A false-positive
            # pairing that wrongly reached this point at all — e.g. two
            # unrelated attrs coincidentally sharing a display label — is
            # fixed at the pairing stage in exclusive_sibling_family_
            # exclusions, not by weakening this check.)
            if (
                not filled.get(attr.variable_name)
                and not filled_multi.get(attr.variable_name)
                and attr.variable_name not in pending_vns
            ):
                pending.append(attr)
                pending_vns.add(attr.variable_name)
        return pending

    @staticmethod
    def governed_target_ids(
        attrs: list[ConfigAttr],
        hiding_rules: list[HidingRule],
        rec_rules: list[RecommendationRule],
        con_rules: list[ConstraintRule],
    ) -> set[int]:
        """Entity ids eligible for default-or-first auto-fill.

        Widened per CPQ_APX_NEXT_ISSUES_PLAN.md Phase N: rule coverage alone
        left ~29 attrs pending on a richer catalog (APX Next) where most
        attrs simply carry no rule at all in the source data — far short of
        the client's <=2-3-prompt requirement. Attrs marked `required=False`
        in the source are also eligible (a source-asserted "safe to default"
        signal), excluding decision-required attrs (country/region), which
        always ask regardless of governance. See `rule_governed_ids` for the
        strict rule-only subset (used to tag `filled_source`).
        """
        governed = set(
            CpqEngine.rule_governed_ids(attrs, hiding_rules, rec_rules, con_rules)
        )
        for attr in attrs:
            if attr.required:
                continue
            vn_flat = attr.variable_name.lower().replace("_", "")
            if any(dk in vn_flat for dk in _DECISION_REQUIRED_KEYS):
                continue
            governed.add(attr.entity_id)
        return governed

    @staticmethod
    def is_recognized_country(value: str) -> str | None:
        """The canonical common name (e.g. "United States") when `value`
        is a real, recognized country -- by common name, official name,
        ISO alpha-2/alpha-3 code, or a punctuation/abbreviation variant
        of any of those ("US.A", "U.K", "U.A.E") -- else None.

        ISSUE-007 (docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_2026_08_
        17.md): previously checked membership in `_COUNTRY_TO_REGION` --
        a small, hand-typed dict of exact strings covering a narrow
        subset of countries, with none of their punctuation/abbreviation
        variants ("us.a" was never a key). Now normalizes the candidate
        (`_normalize_country_candidate`) and checks it against
        `_country_alias_group` -- the comprehensive, symmetric, 249-real-
        country alias table already built for exactly this purpose
        (`engine.py:404+`) -- so any real alias/punctuation/abbreviation
        form of any of the 249 countries resolves here, not just the
        handful the old dict happened to spell out.

        Returns `str | None` rather than the old bare `bool` because this
        is the single shared validation gate for THREE call sites (Path
        B's bare-anchor-reply hint validation, Path C's change-command
        gate, and Path C's downstream LLM-result validation) that all
        need the RESOLVED canonical value, not just a yes/no -- a caller
        that only ever needed the boolean keeps working unmodified, since
        a non-empty string is truthy and `None` is falsy, identical to
        the old bool contract.

        Guards `session.country`'s own assignment (ask_api.py) against a
        real, confirmed live bug: `extract_hints`' generic
        preposition-based country extractor's 2-letter-code alternative
        has no trailing word-boundary check, so "for APX Next" matched
        "for " + "AP" (the first two letters of "APX") and produced
        `hints["country"] = "Ap"`. session.country is a "first hint wins,
        never re-derived" field (ask_api.py) — once set, it's reused
        verbatim on every later turn regardless of whether a real answer
        ever fills the actual country attribute, so a single bad match
        this early permanently blocks `derive_region` for the rest of the
        session with no way to self-correct. Since `session.country`'s
        only consumer is `derive_region`, and `derive_region` itself
        already returns None for anything it can't resolve a region for,
        rejecting an unrecognized candidate BEFORE it's stored costs
        nothing today and stops it from calcifying into a wrong value
        that can never be replaced by a later, correct hint.

        PR #205 review fix: an earlier version of this exclusion rejected
        ANY candidate matching one of this system's own region codes
        ("NA"/"EMEA"/"ME"/"APAC"/"LA") -- but "ME" is genuinely Montenegro's
        real ISO alpha-2 code and "LA" is genuinely Laos's, so that blanket
        rule silently reintroduced the exact same collision bug for two
        more real countries. The blanket exclusion was never actually
        needed for "EMEA"/"ME"/"APAC"/"LA" in the first place: none of
        those four strings appear in any real country's alias group
        (`_COUNTRY_ALIAS_GROUPS`) as anything OTHER than Montenegro's/
        Laos's own codes, so the alias-group lookup below already returns
        None for "EMEA"/"APAC" on its own -- only "NA" is a genuine,
        confirmed double meaning (this system's own "North America" token
        AND Namibia's real alpha-2 code, confirmed live and locked in by
        test_garbage_and_product_fragments_not_recognized, which predates
        this fix and only exercises "NA"/"APAC", never "ME"/"LA"). Scoped
        to the literal, documented single collision instead of a blanket
        rule across this system's whole region-code namespace.
        """
        _normalized = _normalize_country_candidate(value)
        if _normalized.upper() == "NA":
            return None
        group = _country_alias_group(_normalized)
        if group is None:
            return None
        return _country_canonical_name(group)

    @staticmethod
    def derive_region(country: str, attr: ConfigAttr) -> tuple[str, str] | None:
        """Resolve a region attr's value from a known country, without
        inventing a code the catalog doesn't actually offer.

        Looks up `country` in `_COUNTRY_TO_REGION` for a standard region
        abbreviation, then matches that abbreviation against `attr`'s real
        menu options (exact item_value first, then display_name) — a
        country with no mapping, or a catalog whose Region attr doesn't
        offer the derived code, returns None so the caller falls back to
        asking rather than guessing.

        ISSUE-007 (docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_2026_08_
        17.md): `country` may legitimately arrive as any real alias of a
        country (official name, alpha-2/alpha-3 code, a punctuation
        variant like "us.a" normalized upstream to "United States", ...)
        rather than one of the handful of literal strings
        `_COUNTRY_TO_REGION` happens to spell out as keys. The direct
        lookup below is tried first (fast path, unchanged behavior for
        the exact forms that already worked); only when that misses does
        this resolve `country` to its full alias group and retry the
        lookup against every member of that group -- generic for all 249
        real countries, never a per-country special case -- since
        `_COUNTRY_TO_REGION`'s own keys are already just a few of a
        country's many real aliases (e.g. "us"/"usa"/"united states" are
        all present for the US entry today).
        """
        if not country:
            return None
        region_code = _COUNTRY_TO_REGION.get(country.strip().lower())
        if not region_code:
            group = _country_alias_group(_normalize_country_candidate(country))
            if group:
                for alias in group:
                    region_code = _COUNTRY_TO_REGION.get(alias)
                    if region_code:
                        break
        if not region_code:
            return None
        for opt in attr.options:
            if opt.item_value.upper() == region_code:
                return opt.item_value, opt.display_name
        for opt in attr.options:
            if region_code in opt.display_name.upper():
                return opt.item_value, opt.display_name
        return None

    @staticmethod
    def _apply_series_mapping_exclusions(
        attrs: list[ConfigAttr], constrained_opts: dict[int, list[str]],
        filled: dict[str, str], workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> None:
        """Real Oracle CPQ Seriesmodelsmapping Data Table narrowing for
        productSelectionProduct_all -- mutates `constrained_opts` IN PLACE.

        Confirmed live (2026-08-08): with country=US, "APX NEXT
        International (Federal)" still appeared in the Product menu even
        though it isn't a real, orderable model for the US market (see
        data_table_resolver.resolve_invalid_product_variant's own
        docstring for the full evidence chain). `None`/no workspace_id
        (default) is a complete no-op, identical to before this existed.
        Only ever REMOVES options a real ingested row explicitly says
        aren't valid here -- never adds a constraint where none of this
        data applies (never guess).
        """
        if workspace_id is None:
            return
        target = next(
            (a for a in attrs if a.variable_name == "productSelectionProduct_all"), None,
        )
        if target is None:
            return
        existing = constrained_opts.get(target.entity_id)
        candidates = (
            [o for o in target.options if o.item_value in existing]
            if existing is not None else target.options
        )
        excluded: set[str] = set()
        for opt in candidates:
            override = dt_resolve_invalid_product_variant(
                opt.display_name, opt.item_value, filled, workspace_id, catalog_prefix, cache,
            )
            if override is not None:
                excluded.add(opt.item_value)
        if not excluded:
            return
        if existing is not None:
            constrained_opts[target.entity_id] = [v for v in existing if v not in excluded]
        else:
            constrained_opts[target.entity_id] = [
                o.item_value for o in target.options if o.item_value not in excluded
            ]

    @staticmethod
    def _suppress_ungoverned_attrs(
        attrs: list[ConfigAttr], filled: dict[str, str],
        workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> tuple[list[ConfigAttr], set[str]]:
        """Drop attrs the real ingested attrSequence Data Table confidently
        says do NOT belong to the active base model -- returns (visible,
        suppressed_variable_names).

        `data_table_resolver.attribute_applies()` already answers this
        generically for any attribute name; the gap was never the data, it
        was that nothing called it. Confirmed live (2026-08-08): with a
        base model whose real attrSequence rows list wirelessCarrier_astro
        as required and carry ZERO rows for carrierSelectionMultiSelect_
        astro, auto_fill still filled BOTH (they're independently governed
        by unrelated rules) -- a structurally-invalid payload (two mutually
        exclusive carrier mechanisms both populated) that no rule in the
        static export catches, because the exclusivity lives in this Data
        Table, not in any rule script.

        Only ever REMOVES an attr when at least one CPQModel candidate has
        attrSequence coverage for this exact base model (some OTHER attr
        showed up) AND none of them say this one applies AND at least one
        candidate's attrSequence table mentions this attr name for SOME
        base model (i.e. the catalog actively tracks its applicability,
        just not here) -- a confident "not part of this base model", never
        a guess from missing data.

        An attr that is absent from the base-model-scoped governed set
        purely because NO attrSequence row anywhere (any base model, any
        candidate) ever mentions it at all (confirmed live 2026-08-09:
        carrierSelectionMultiSelect_astro has real sequence coverage for
        exactly one (CPQModel, BaseModel) pair in the whole catalog) is
        left visible instead -- there is no real "excluded" signal, only
        silence, and silently dropping a real, catalog-defined question is
        worse than asking it (same reasoning as bom_gate.
        find_missing_required_fields and the always-ask decision-key
        carve-outs elsewhere in this method).

        `None` (no attrSequence coverage at all for any candidate) leaves
        the attr untouched, identical to before this method existed.
        `None`/no `workspace_id` is a complete no-op.
        """
        if workspace_id is None:
            return attrs, set()
        base_model = filled.get("modelSelectionbaseModel_astro", "")
        if not base_model:
            return attrs, set()
        product = filled.get("productSelectionProduct_all", "")
        cands = _cpq_model_candidates(
            product, workspace_id, catalog_prefix, cache, base_model=base_model,
        )
        if not cands:
            return attrs, set()

        # Precomputed ONCE per candidate CPQModel here, not once per attr
        # -- see governed_attr_names_for_base_model's own docstring for
        # the live-measured O(attrs x candidates x rows) cost of the
        # naive per-attr version this replaced.
        scoped_name_sets = [
            dt_governed_attr_names_for_base_model(
                cm, base_model, workspace_id, catalog_prefix, cache,
            )
            for cm in cands
        ]
        if not any(s is not None for s in scoped_name_sets):
            return attrs, set()
        governed_names: set[str] = set()
        for s in scoped_name_sets:
            if s:
                governed_names |= s

        visible: list[ConfigAttr] = []
        suppressed: set[str] = set()
        for attr in attrs:
            vn = attr.variable_name
            vn_flat = vn.lower().replace("_", "")
            if any(frag in vn_flat for frag in _NEVER_SUPPRESS_FRAGMENTS):
                visible.append(attr)
            elif vn in governed_names:
                visible.append(attr)
            elif not any(
                dt_attr_ever_governed_for_cpq_model(cm, vn, workspace_id, catalog_prefix, cache)
                for cm in cands
            ):
                # No attrSequence row anywhere (any base model, any
                # candidate CPQModel) ever mentions this attr -- silence,
                # not a confident exclusion. Leave it visible/askable.
                visible.append(attr)
            else:
                suppressed.add(vn)
        return visible, suppressed

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
        """Real, generic replacement for a real BM script this catalog can't
        execute ("Set Hidden Master String For Astro Portable" and its
        siblings): the delimited list of attribute names the ingested
        attrSequence Data Table says apply to the current product's
        CPQModel/BaseModel pair -- exactly what dozens of "hide if no
        values available" hiding-rule scripts check membership in via
        SPLIT()/findinarray() (docs/CPQ_HIDDEN_MASTER_STRING_HIDING_RULE_
        GAP_PLAN_2026_08_10.md). Reuses the SAME governed-name computation
        `_suppress_ungoverned_attrs` already runs -- the gap here was
        never the data, it was that nothing exposed this specific
        variable to the hiding-rule evaluator.

        `var_name` is accepted (not hardcoded into the body) so a sibling
        master-string variable following the identical attrSequence-
        lookup shape could reuse this same method later -- but the
        result is only ever written into `filled` under this parameter's
        actual value by the caller, never assumed here.

        Returns `None` (leave the caller's `filled` untouched) when:
          - `workspace_id` is `None`, or Product/Base Model aren't filled
            yet -- the real script needs both too, same guard as
            `_suppress_ungoverned_attrs`.
          - no CPQModel candidate has ANY attrSequence coverage at all for
            this base model -- an unresolvable "unknown", never
            fabricated as an empty string. An empty string would make
            every downstream script's `findinarray(...) == -1` branch
            fire and hide everything, which is worse than leaving the
            script "unknown" (matches `apply_hiding_rules`' own
            "unknown -> don't hide" default for every OTHER unresolvable
            script).

        The join separator is read from `filled` first (in case a real
        turn already resolved it the same way BigMachines' own runtime
        would), else from the separator attribute's own real, ingested
        `default_value` when `attrs` is supplied -- never a bare
        hardcoded literal, so this stays correct for any catalog whose
        export uses a different separator string.
        """
        if workspace_id is None:
            return None
        product = filled.get("productSelectionProduct_all", "")
        base_model = filled.get("modelSelectionbaseModel_astro", "")
        if not product or not base_model:
            return None
        cands = _cpq_model_candidates(
            product, workspace_id, catalog_prefix, cache, base_model=base_model,
        )
        if not cands:
            return None
        scoped_name_sets = [
            dt_governed_attr_names_for_base_model(
                cm, base_model, workspace_id, catalog_prefix, cache,
            )
            for cm in cands
        ]
        if not any(s is not None for s in scoped_name_sets):
            return None
        governed_names: set[str] = set()
        for s in scoped_name_sets:
            if s:
                governed_names |= s

        sep = filled.get(separator_var_name, "")
        if not sep and attrs:
            sep_attr = next(
                (a for a in attrs if a.variable_name == separator_var_name), None,
            )
            if sep_attr and sep_attr.default_value:
                sep = sep_attr.default_value
        if not sep:
            sep = "@@@"

        if not governed_names:
            return ""
        return "".join(f"{name}{sep}" for name in sorted(governed_names))

    @staticmethod
    def _invalidate_inconsistent_paired_values(
        filled: dict[str, str], sources: dict[str, str],
        workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> set[str]:
        """Variable names to clear because their currently-filled value
        contradicts a linked attribute's currently-filled value, per real
        ingested Data Table rows (data_table_resolver.
        find_inconsistent_filled_pairs -- see its own docstring for the
        live-confirmed Bands/BandPlus example). Clearing both lets the
        next evaluate_rules_loop pass re-resolve them together instead of
        leaving a structurally-invalid combination locked in.

        Never clears a variable whose value traces back to something the
        customer said or confirmed -- filled_source in
        `CpqEngine._CONFIRMED_SOURCES` ("user", "hint", "cascade"), the same
        boundary `apply_recommendation_rules`' `_NEVER_OVERRIDE` and
        `build_standalone_payload`'s own none-sentinel handling already use
        -- this check second-guesses two independent auto-fill guesses,
        never a real answer. Live-confirmed bug (2026-08-10): this
        previously only excluded "user", so a "hint"-sourced value (e.g.
        `ultimateDestinationCountry` mined from turn 1's free-text order)
        got silently cleared and re-asked mid-conversation the moment a
        LATER, unrelated cascade (Hardware Version) changed `base_model`/
        `productSelectionProduct_all` enough for this pass's Data-Table-
        scoped pairing to flag it -- even though the customer had already
        given it.
        `None`/no workspace_id is a complete no-op.
        """
        if workspace_id is None:
            return set()
        base_model = filled.get("modelSelectionbaseModel_astro", "")
        if not base_model:
            return set()
        product = filled.get("productSelectionProduct_all", "")
        cands = _cpq_model_candidates(
            product, workspace_id, catalog_prefix, cache, base_model=base_model,
        )
        invalid: set[str] = set()
        for cpq_model in cands:
            invalid |= dt_find_inconsistent_filled_pairs(
                cpq_model, base_model, filled, workspace_id, catalog_prefix, cache,
            )
        return {vn for vn in invalid if sources.get(vn) not in CpqEngine._CONFIRMED_SOURCES}

    @staticmethod
    def find_confirmed_data_table_conflicts(
        filled: dict[str, str], sources: dict[str, str],
        workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> set[tuple[str, str]]:
        """The specific edge case `_invalidate_inconsistent_paired_values`
        deliberately leaves untouched: a real, data-proven-invalid pair
        where BOTH sides are customer-confirmed (`CpqEngine.
        _CONFIRMED_SOURCES` -- "user", "hint", "cascade"). Neither side can
        be silently self-corrected (both are real facts the customer gave),
        so this is surfaced for an explicit re-ask instead -- same
        discipline `_reask_stale_constraint_violations` already applies to
        constraint-rule violations
        (docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §4.1), extended to
        Data-Table-proven conflicts
        (docs/CPQ_BOTH_CONFIRMED_DATA_TABLE_CONFLICT_REASK_PLAN_2026_08_10.md).

        `None`/no workspace_id, or no base model resolved yet, is a
        complete no-op -- same convention as
        `_invalidate_inconsistent_paired_values`.
        """
        if workspace_id is None:
            return set()
        base_model = filled.get("modelSelectionbaseModel_astro", "")
        if not base_model:
            return set()
        product = filled.get("productSelectionProduct_all", "")
        cands = _cpq_model_candidates(
            product, workspace_id, catalog_prefix, cache, base_model=base_model,
        )
        confirmed_conflicts: set[tuple[str, str]] = set()
        for cpq_model in cands:
            for attr_a, attr_b in dt_find_inconsistent_filled_pairs_detailed(
                cpq_model, base_model, filled, workspace_id, catalog_prefix, cache,
            ):
                if (sources.get(attr_a) in CpqEngine._CONFIRMED_SOURCES
                        and sources.get(attr_b) in CpqEngine._CONFIRMED_SOURCES):
                    confirmed_conflicts.add((attr_a, attr_b))
        return confirmed_conflicts

    @staticmethod
    def _resolve_via_data_tables(
        vn: str, filled: dict[str, str], valid_opts: list[MenuOption],
        workspace_id: int | None, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> MenuOption | None:
        """Real ingested Oracle CPQ Data Table lookup
        (docs/CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_PROOF_2026_08_07.md
        §11-§12), tried only when script-based governance already failed to
        resolve `vn`. Returns a menu option ONLY when the table resolves to
        exactly one legal value that is also a real option on this attr --
        2+ legal values, 0 legal values, no table data at all, or no
        `workspace_id` (caller didn't opt in) all return None (never guess),
        matching every other never-guess branch in this method.
        """
        if workspace_id is None:
            return None
        base_model = filled.get("modelSelectionbaseModel_astro", "")
        if not base_model:
            return None
        product = filled.get("productSelectionProduct_all", "")
        for cpq_model in _cpq_model_candidates(
            product, workspace_id, catalog_prefix, cache, base_model=base_model,
        ):
            values = dt_resolve_whitelist_values(
                cpq_model, base_model, vn, filled, workspace_id, catalog_prefix, cache,
            )
            if values is None:
                continue
            if len(values) != 1:
                # This candidate is ambiguous -- try the REST of the
                # candidate tuple before giving up. `_cpq_model_candidates`
                # appends base-model-specific candidates after the
                # product-derived primary one(s) (confirmed live:
                # H45TGU9PW8AN's real whitelist rows are keyed to
                # APXNEXTXNSINGLE, only reachable via that appended tail,
                # even though the product resolves primary to
                # APXNEXTSINGLE/APXNEXTSINGLE_BOM). Returning None here
                # would end the search the moment the FIRST candidate
                # happens to be ambiguous, even when a later candidate
                # would have resolved to exactly one confirmed value --
                # the same "continue past ambiguous, don't abort" contract
                # `_resolve_narrowed_legal_values` already uses below.
                continue
            return next((o for o in valid_opts if o.item_value == values[0]), None)
        return None

    @staticmethod
    def _resolve_narrowed_legal_values(
        vn: str, filled: dict[str, str], workspace_id: int, catalog_prefix: str = "",
        cache: dict[tuple[int, str], tuple] | None = None,
    ) -> list[str] | None:
        """Real ingested Data Table whitelist for `vn`, however many values
        it narrows to -- unlike `_resolve_via_data_tables` (which only ever
        returns when exactly one value is confidently correct), this
        returns the full narrowed set so a blind-pick fallback can choose
        from real, data-proven-legal options instead of the unfiltered raw
        catalog menu (docs/CPQ_MULTISELECT_BLIND_PICK_RESPECTS_WHITELIST_
        PLAN_2026_08_10.md). `None` -- no ingested table has any row for
        this attr in this context (genuinely unknown, not zero); `[]` --
        real rows exist but none match the current filled state (a
        confirmed, real "nothing is legal right now" answer); `[v1, v2,
        ...]` -- the real, catalog-sourced legal set, however many members.
        """
        base_model = filled.get("modelSelectionbaseModel_astro", "")
        if not base_model:
            return None
        product = filled.get("productSelectionProduct_all", "")
        for cpq_model in _cpq_model_candidates(
            product, workspace_id, catalog_prefix, cache, base_model=base_model,
        ):
            values = dt_resolve_whitelist_values(
                cpq_model, base_model, vn, filled, workspace_id, catalog_prefix, cache,
            )
            if values is not None:
                return values
        return None

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
    ) -> tuple[dict[str, str], dict[str, str], list[ConfigAttr]]:
        """Auto-fill attributes. Never assigns None/null/empty values.

        hiding_rules — docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_BLIND_PICK_
        PLAN_2026_08_10.md: optional; when supplied, a pending-bound attr
        whose ONLY hiding rule structurally depends on a confirmed-absent
        data table (`_KNOWN_MISSING_DATA_TABLES`) is warned-and-skipped
        instead of asked forever. `None` (the default) is a complete no-op,
        identical to every caller that doesn't pass it.

        workspace_id — optional; when supplied, an attribute whose only
        governing rule is script-based and failed to resolve
        (`_NEVER_GUESS_SCRIPT_GOVERNED`) gets one more real-data attempt via
        `data_table_resolver.py` before falling through to pending
        (docs/CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_PROOF_2026_08_07.md
        §11-§12) — real ingested Oracle CPQ Data Table rows, not a guess.
        `None` (the default) skips this tier entirely, identical to
        pre-existing behavior for every caller that doesn't pass it.
        catalog_prefix — forwarded to the same lookup for workspaces
        holding more than one ingested catalog (see `_catalog_prefix`).

        display_order — optional {variable_name: rank} from
        `load_layout_display_order` (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_
        PLAN.md §2c). When supplied: (a) the returned `pending` list is
        sorted by rank instead of catalog/discovery order, so questions
        get asked in the same sequence the real native UI shows them; (b)
        only `is_decision_attr` anchors (Country/Region/Hardware
        Version/Product) and grid-linked selectors reach `pending` at all
        — every other attr the final ask-branch would otherwise have
        asked about is instead SKIPPED (left entirely unfilled, not
        defaulted-empty) when nothing upstream (hint/recommendation/
        default) resolved it. Sibling-forced re-asks
        (`enforce_exclusive_sibling_families`) are a separate code path
        and are unaffected either way. `None` (the default) keeps today's
        "ask everything with options" behavior completely unchanged.

        Priority order (first match wins):
          1. Already filled in a prior turn.
          2. User-stated value matched from NL hints.
          3. A `rec_rules` recommendation targeting this exact attr whose
             condition is ALREADY satisfied by the current `filled` state
             (via `_satisfied_recommendation`) — checked BEFORE the generic
             XML default_value below, because a targeted, condition-matched
             recommendation is more specific than a catalog-wide default and
             must win over it. Without this, an attr with a non-empty
             default_value got locked in by step 4 unconditionally, before
             `apply_recommendation_rules()` (which runs later in
             `evaluate_rules_loop` and never revisits an attr already in
             `filled`) ever got a chance to apply (confirmed live:
             solutionTypeDevices_astro's own default_value silently beat
             the "Set CLOUD RC as default value" rule this way).
          4. Valid default_value from XML (not None/null/0).
          5. Rule-governed default-or-first (D2/§3) — only for attrs in
             `governed_ids`; everything else falls through to (6). Before
             falling to "first by order", re-checks `_satisfied_recommendation`
             (same helper as step 3, needed here for attrs with NO
             default_value at all, which skip step 3's `attr.options` guard
             only when they still lack a value) — if so, uses that value
             instead. Without this check, a rule-governed attr whose real
             recommendation condition happens to already be true this same
             pass still got the blind first-option pick here (this method
             runs before `apply_recommendation_rules()` in
             `evaluate_rules_loop`), permanently locking in the wrong value
             since neither mechanism revisits an attr already in `filled`
             (confirmed live: hWVersion_astro's region=NA recommendation
             never fired because first-by-order claimed it first).
          6. First eligible item_value by order_number, but ONLY when exactly
             one option remains after constraint filtering (NO EAGER
             EVALUATION — Issue 6's "Stop and Wait" safeguard for anything
             not rule-governed).

        constrained_opts — {entity_id: [allowed_item_values]} from active
          ConstraintRules. When set, first-option fallback only picks from the
          allowed set; hint/default paths ignore constraints (they were validated
          by the rule that produced the recommendation).
        governed_ids — entity_ids eligible for step 4 (see governed_target_ids).
        rule_governed_ids — the strict rule-only subset of governed_ids (see
          rule_governed_ids()); used only to tag filled_source as "rule" vs
          "optional" (Phase N/K) for step-4 fills. Defaults to governed_ids
          itself when omitted, i.e. every step-4 fill is tagged "rule" —
          the pre-Phase-N behavior for callers not yet passing it.
        country — confirmed country text (session.country), used ONLY to
          derive region-pattern decision-key attrs via `derive_region()`
          before they fall to the normal "always ask" path. "country"
          itself is unaffected — it's still asked as before (D1). No match
          (unmapped country, or catalog offers no matching code) falls
          through to asking, same as if `country` were omitted.
        negated_vns — variable_names from extract_catalog_hints() whose
          concept was explicitly negated in the question (see that method's
          docstring). Step 4's blind first-by-order fallback is skipped for
          these — ask instead of risking the literal opposite of what was
          requested.

        select_type handling within step 4:
          - single/boolean: default_value if present, else first option by
            order (boolean's "first option" is well-defined — only two states).
          - multi, non-required: an active constraint narrowing to EXACTLY
            ONE remaining option is auto-filled (written to filled_multi),
            same certainty threshold as single-select's "exactly one
            choice" case (confirmed live, docs/CPQ_MULTISELECT_AUTOFILL_
            OVERSELECTION_PLAN_2026_08_05.md: a near-universally-true
            constraint narrowing a menu to 9 of 11 options is not a
            recommendation to select all 9 — auto-selecting all 9 there
            was the original bug). Narrowing to SEVERAL remaining options
            (still ambiguous) prefers the XML default_value when it's
            still one of the currently-valid options; with no matching
            default, defaults to empty rather than asking — an explicit
            product decision (same plan doc's "explicit product decision"
            addendum) to favor fewer conversational questions over asking
            about every unresolved optional multi-select, accepting the
            known, documented risk that a sibling rule keyed on "does NOT
            contain value X" may treat that default-empty as a genuine
            confirmed answer.

        Returns:
          filled         — {variable_name: item_value} for API payload
          display_filled — {variable_name: display_name} shown to sales rep
          pending        — attrs that still need a human answer

        filled_multi is updated in place (via the `filled_source` pattern) if
        `already_filled_multi` is supplied; otherwise multi-select governed
        auto-fills are silently skipped (caller opted out of multi-select).
        An existing multi-selection is re-validated against a NEW active
        constraint each call — members no longer allowed are dropped and
        named in `dropped_multi` (in place) rather than silently vanishing
        (§5 — same bug class as the Region=NA payload-drop fix).

        skip_always_ask — variable_names whose normal always-ask override
        (e.g. productSelectionProduct_all, §3c) should NOT force a question
        this call, because the caller already confirmed via
        resolve_ui_layout_scope() that the real native UI never shows this
        field for the active configuration flow (exactly one active
        rule_type=6 flow resolved, and this attr isn't in it — see
        docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md §5). Empty/None
        changes nothing — every catalog where the flow is ambiguous (e.g.
        APX Next, 2 active flows) keeps today's unchanged always-ask
        behavior.
        """
        dt_cache: dict[tuple[int, str], tuple] = _dt_cache if _dt_cache is not None else {}
        filled: dict[str, str] = dict(already_filled or {})
        filled_multi = already_filled_multi if already_filled_multi is not None else {}
        display_filled: dict[str, str] = {}
        pending: list[ConfigAttr] = []
        sources = filled_source if filled_source is not None else {}
        governed = governed_ids or set()
        rule_governed = rule_governed_ids if rule_governed_ids is not None else governed
        dropped = dropped_multi if dropped_multi is not None else {}
        # Cascade-invalidated attrs whose CLEARED value was a real user
        # decision (filled_source == "user"), not an auto-fill — these must
        # be re-asked (added to `pending`) rather than silently re-guessed
        # by the blind-fallback branch below (docs/CPQ_SESSION_2_OPEN_ISSUES.md
        # item 4). Mirrors the same "never silently guess a real decision"
        # principle already applied to product-identifier attrs.
        user_answered_dropped_ids: set[int] = set()

        # Pointer-defaults (Issue 11, docs/CPQ_PRODUCT_SWITCH_ISSUE.md): a
        # default_value that exactly equals ANOTHER attribute's variable
        # name is a REFERENCE the source platform resolves at runtime, not
        # a literal (confirmed live: modelname_all's XML default is the
        # string "_bm_model_variable_name" — BM's own "Set Model Name..."
        # rule copies that runtime model-context attr into it; the export
        # carries only the pointer token). Shipping the token as data put
        # '"modelname_all": "_bm_model_variable_name"' in real payloads.
        # Structural check, no attribute names in code — an exhaustive
        # survey of every ingested catalog found exactly this ONE pattern
        # (modelname_all -> _bm_model_variable_name in both exports) and
        # zero coincidental literal defaults matching an attr name.
        _all_vns = {a.variable_name for a in attrs}

        def _is_pointer_default(a: "ConfigAttr") -> bool:
            return (not a.options
                    and a.default_value in _all_vns
                    and a.default_value != a.variable_name)

        # target attr id -> recommendation rules targeting it, so step 4 can
        # check for an already-satisfied recommendation before blindly
        # picking first-by-order (see docstring — the ordering bug this closes).
        rec_by_target: dict[int, list[RecommendationRule]] = {}
        if rec_rules:
            for _r in rec_rules:
                rec_by_target.setdefault(_r.target_attr_id, []).append(_r)
        attr_by_rule_id = self._attr_index(attrs) if rec_by_target else {}

        def _satisfied_recommendation(
            attr: "ConfigAttr", candidate_opts: list["MenuOption"],
        ) -> tuple[str, str, str] | None:
            """A targeted recommendation whose condition is ALREADY true
            in the current `filled` state — more specific than a generic
            XML default_value and must win over it (confirmed live:
            solutionTypeDevices_astro's own default_value silently beat
            the "Set CLOUD RC as default value" rule because the old step
            3 ran unconditionally before any rule got a chance to apply,
            since apply_recommendation_rules() never revisits an attr
            already in `filled` — docs/CPQ_SESSION_2_OPEN_ISSUES.md).

            Also handles script/condition_script-backed rules (via
            bml_eval), not just the plain condition_attr_id/condition_value
            pair — same Tier-1/Tier-2 machinery apply_recommendation_rules
            uses. Purely additive: a script that resolves is always a
            correct answer, never a wrong guess, and never asks a
            question that wasn't already going to be asked (it can only
            resolve an attr that would otherwise stay unfilled/pending).
            bml_eval=None (caller opted out) falls back to skipping script
            rules entirely, same as apply_recommendation_rules.

            Returns (item_value, display_name, rule_name) — the rule_name
            (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2e) is the
            specific rule that fired, for the rule-trace attribution call
            sites use it for instead of the old generic "auto_fill:rule"
            tag. Every return path below already has `rrule` in scope, so
            this is free — no separate lookup.
            """
            for aid_key in (attr.entity_id, attr.source_id):
                if aid_key is None:
                    continue
                for rrule in rec_by_target.get(aid_key, []):
                    if rrule.script is not None:
                        if bml_eval is None:
                            continue
                        allowed = bml_eval.allowed_values_for_script(rrule.script, filled)
                        if not allowed or len(allowed) != 1:
                            continue  # unknown, or ambiguous — never guess
                        recommended_value = allowed[0]
                    elif rrule.condition_script is not None:
                        if bml_eval is None:
                            continue
                        fires = bml_eval.condition_holds(rrule.condition_script, filled)
                        if fires is not True:
                            continue  # False or unknown — never guess, doesn't fire
                        recommended_value = rrule.recommended_value
                    else:
                        cond_attr = attr_by_rule_id.get(rrule.condition_attr_id)
                        if not cond_attr:
                            continue
                        cond_val = filled.get(cond_attr.variable_name)
                        if cond_val is None or not _condition_value_matches(
                            cond_val, rrule.condition_value, rrule.condition_operator
                        ):
                            continue
                        recommended_value = rrule.recommended_value
                    match = next(
                        (o for o in candidate_opts
                         if o.item_value.lower() == recommended_value.lower()),
                        None,
                    )
                    if match:
                        return match.item_value, match.display_name, rrule.rule_name
            return None

        # Selectors resolve_array_grid_links() confirmed drive a real
        # quantity attr (e.g. mountingTypeArray_viSoln -> the 6 mounting-
        # type quantities) are NOT cosmetic optional checkboxes even though
        # required="0" — silently defaulting them to empty would silently
        # skip a real BOM decision (docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_
        # GRID_PLAN.md §5). Excluded from the optional-multi-select
        # auto-empty branch below so they're asked like any other real
        # question instead; every other optional multi-select is unaffected.
        grid_selector_vns = set(self.resolve_array_grid_links(attrs).keys())

        # Attrs a real ingested attrSequence Data Table confirms govern the
        # CURRENT base model (docs/CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_
        # PROOF_2026_08_07.md §1-§3, §9): must be treated as askable by §2c's
        # display-order gate below the same way `grid_selector_vns` already
        # is. Without this, an attr that legitimately survives
        # `_suppress_ungoverned_attrs` (confirmed governed, or never
        # governed anywhere so left visible) could still be silently
        # dropped by §2c's blanket "not a decision attr → skip" rule,
        # exactly reproducing the original bug (a real question the
        # customer should see just never appears) one layer further down.
        # Also mirrors `_suppress_ungoverned_attrs`'s OTHER carve-out here:
        # an attr no attrSequence row anywhere (any base model, any
        # candidate CPQModel) ever mentions is silence, not a confident
        # exclusion, so it survives suppression -- but §2c's gate below
        # would otherwise still silently drop it as "not a decision attr".
        # `_dt_never_governed_anywhere` memoizes that per-vn check (real
        # rows can be up to tens of thousands; only compute once per attr
        # actually reaching this branch, not for every attr up front).
        # Base models are sometimes shared across unrelated regional/federal
        # CPQModel siblings (confirmed live 2026-08-09: H55TGT9RW8AN has ZERO
        # real coverage under APXNEXTSINGLE -- the primary, product-derived
        # candidate for "APX NEXT Single Band" -- but 120 attrs' worth of
        # coverage under APXNEXTINTL/APXNEXTINTLFED, discovered only via the
        # base_model= widening below). Using the full widened candidate set
        # to decide "must always ask, never blind-guess" inherited that
        # unrelated sibling's entire governance scope onto a domestic order,
        # forcing 120 real questions (Configuration Type, System Key,
        # Wireless Carrier, ...) that the actual Single Band data would
        # never require. `_dt_primary_candidates` (product-derived only, no
        # base_model widening) is what should gate always-ask; the full,
        # base-model-widened `_dt_candidates` is kept for VALUE RESOLUTION
        # only (_resolve_via_data_tables, _dt_never_governed_anywhere) --
        # that's the mechanism the keypad-type XN-variant fix depends on and
        # must stay unchanged.
        # Base Model region-allow resolution (confirmed live, 2026-08-10):
        # NewCountryRegMapping-shaped ("region_rule") Data Table rows carry
        # a real per-(CPQModel, region[, country]) ALLOW default for
        # modelSelectionbaseModel_astro -- the same answer Oracle CPQ's own
        # "Set Base Model" recommendation rules compute at runtime against
        # `Oracle_BomItemMap` (a live table never present in any export
        # seen so far). Computed here, BEFORE base model is filled, using
        # only the PRIMARY (product-derived) CPQModel candidates -- unlike
        # `_dt_candidates` below (which also widens by base_model once one
        # is chosen), there is no base model yet to widen from. Only ever
        # used when it resolves to exactly one value (see
        # `resolve_region_allow_value`'s tie-safe contract); otherwise
        # falls through to the unconditional always-ask anchor unchanged.
        _bm_region_allow_value: str | None = None
        if workspace_id is not None and not filled.get("modelSelectionbaseModel_astro"):
            _bm_product = filled.get("productSelectionProduct_all", "")
            if _bm_product:
                _bm_country = filled.get("ultimateDestinationCountry") or country or ""
                _bm_region = filled.get("modelSelectionRegion_astro") or (
                    _COUNTRY_TO_REGION.get(_bm_country.strip().lower(), "") if _bm_country else ""
                )
                if _bm_region:
                    _bm_primary_candidates = _cpq_model_candidates(
                        _bm_product, workspace_id, catalog_prefix, _dt_cache,
                    )
                    for _bm_cm in _bm_primary_candidates:
                        _bm_v = dt_resolve_region_allow_value(
                            "modelSelectionbaseModel_astro", _bm_cm, _bm_region,
                            workspace_id, catalog_prefix, _dt_cache, country=_bm_country,
                        )
                        if _bm_v:
                            _bm_region_allow_value = _bm_v
                            break

        _dt_governed_vns: set[str] = set()
        _dt_candidates: tuple[str, ...] = ()
        if workspace_id is not None:
            _dt_base_model = filled.get("modelSelectionbaseModel_astro", "")
            if _dt_base_model:
                _dt_product = filled.get("productSelectionProduct_all", "")
                _dt_primary_candidates = _cpq_model_candidates(
                    _dt_product, workspace_id, catalog_prefix, _dt_cache,
                )
                _dt_candidates = _cpq_model_candidates(
                    _dt_product, workspace_id, catalog_prefix, _dt_cache, base_model=_dt_base_model,
                )
                for _dt_cm in _dt_primary_candidates:
                    _dt_scoped = dt_governed_attr_names_for_base_model(
                        _dt_cm, _dt_base_model, workspace_id, catalog_prefix, _dt_cache,
                    )
                    if _dt_scoped:
                        _dt_governed_vns |= _dt_scoped

        def _dt_never_governed_anywhere(vn: str) -> bool:
            if not _dt_candidates:
                return False
            return not any(
                dt_attr_ever_governed_for_cpq_model(
                    cm, vn, workspace_id, catalog_prefix, _dt_cache,
                )
                for cm in _dt_candidates
            )

        # docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_BLIND_PICK_PLAN_2026_08_
        # 10.md -- attrs whose ONLY hiding rule structurally depends on a
        # confirmed-absent data table (_KNOWN_MISSING_DATA_TABLES) can never
        # have that rule resolve. Precomputed once, same pattern as
        # _dt_governed_vns above. hiding_rules=None (no caller passes it)
        # keeps this empty -- a complete no-op, identical to today's
        # behavior for every existing call site.
        _missing_data_target_ids: set[int] = {
            rule.target_attr_id for rule in (hiding_rules or [])
            if _hiding_rule_needs_missing_data_table(rule)
        }

        # Two "optional"-tier attrs (no rule, no default — eligible only via
        # the widened Phase N fallback) that share a real option value are
        # very likely the same underlying hardware/accessory concept exported
        # as separate BM attributes (confirmed live: spSurveillancePackagesType_astro
        # and spSurveillancePackagesTypes_astro both offer "Impress 3-Wire
        # Surveillance Kit - Black" — picking first-by-order for each
        # independently produced Beige AND Black in the same quote). Rule-governed
        # attrs (a real rule already backs the value) are excluded — this is
        # purely a same-slot-detector for otherwise-independent fields.
        _option_value_owners: dict[str, set[int]] = {}
        for a in attrs:
            if (a.hidden or a.entity_id not in governed or a.entity_id in rule_governed
                    or a.select_type == "multi"):
                continue
            for opt in a.options:
                iv_norm = opt.item_value.strip().upper()
                # Generic yes/no-shaped values are shared by dozens of
                # unrelated boolean-ish attrs (quickStartGuide, dualBand,
                # etc.) — real signal only comes from specific values a
                # coincidence wouldn't produce (e.g. a shared SKU/kit name).
                if _valid(opt.item_value) and iv_norm.lower() not in self._BOOLEAN_DISPLAY_VALUES:
                    _option_value_owners.setdefault(iv_norm, set()).add(a.entity_id)
        conflicted_optional_ids: set[int] = set()
        for owners in _option_value_owners.values():
            if len(owners) > 1:
                conflicted_optional_ids.update(owners)

        for attr in attrs:
            vn = attr.variable_name
            # §2e (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md): set by
            # _satisfied_recommendation's call sites below when it returns
            # a match, so the trace call downstream can attribute the fill
            # to the specific rule that fired instead of a generic tag.
            fired_rule_name: str | None = None

            if vn in filled:
                # Deliberately cleared by the user (D4,
                # docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md) — an empty
                # value tagged filled_source="user" is a standing "leave
                # this blank" decision, the single-select counterpart of
                # filled_multi's existing empty-plus-"user" "(none)"
                # convention below. Never re-guessed by the blind
                # first-by-order fallback on a later pass; only a genuine
                # rule re-assertion (apply_recommendation_rules' truthy
                # check, not `in filled`) overrides it, exactly like it
                # would override any other stale value.
                if filled[vn] == "" and sources.get(vn) == "user":
                    display_filled[vn] = "(none)"
                    continue
                # Already answered in a prior turn — but a cascade may have
                # narrowed this attr's allowed set since then (single-select
                # counterpart of the multi-select re-validation below, §5/
                # Phase J). If the locked value is no longer allowed, clear
                # it and fall through to re-resolution instead of keeping a
                # stale, now-invalid answer.
                allowed_single = (
                    constrained_opts.get(attr.entity_id) if constrained_opts else None
                )
                if allowed_single is not None and filled[vn] not in allowed_single:
                    stale_display = display_filled.get(vn, filled[vn])
                    dropped[vn] = [stale_display]
                    if sources.get(vn) == "user":
                        user_answered_dropped_ids.add(attr.entity_id)
                    filled.pop(vn, None)
                    display_filled.pop(vn, None)
                    sources.pop(vn, None)
                elif sources.get(vn) == "default_first_available":
                    # Live bug (2026-08-09): this value was picked with
                    # NOTHING to justify it (§2f's blind first-by-order
                    # fallback, when neither a satisfied recommendation nor
                    # the real Data Table constraint resolved a value on
                    # THAT pass) -- but evaluate_rules_loop's `filled` state
                    # keeps growing richer pass over pass, and the Data
                    # Table lookup that failed to narrow to one value on an
                    # EARLY pass (not enough context yet) can very much
                    # succeed on a LATER one. Confirmed live:
                    # extendRangeTo762764MHz_astro got blind-picked "YES"
                    # on an early pass; the real ingested constraint data,
                    # given the FULL final filled state, unambiguously says
                    # "NO" -- but nothing ever re-checked it once filled,
                    # same "single-select re-validation" gap the
                    # multi-select branch below already closes for its own
                    # "default_first_available" tag. Re-open it every pass
                    # instead of locking in a guess forever -- worst case
                    # (still no real resolution) it just gets re-guessed
                    # identically; best case, a real answer now overrides
                    # the earlier guess before the customer ever sees the
                    # wrong one.
                    filled.pop(vn, None)
                    display_filled.pop(vn, None)
                    sources.pop(vn, None)
                else:
                    matched_display = next(
                        (o.display_name for o in attr.options
                         if o.item_value == filled[vn]),
                        filled[vn],
                    )
                    display_filled[vn] = matched_display
                    continue
            if vn in filled_multi:
                allowed_now = constrained_opts.get(attr.entity_id) if constrained_opts else None
                if allowed_now is not None:
                    if sources.get(vn) == "default_first_available":
                        # This value was picked with NOTHING to justify it
                        # (no active constraint, no default_value) on some
                        # earlier pass — a real constraint now exists for
                        # this attr that didn't (or wasn't yet computed)
                        # when the guess was made. Re-open unconditionally
                        # rather than merely checking the guess is still
                        # technically a member of the new allowed set —
                        # "still happens to be valid" is not the same as
                        # "is the answer Fix 3/4's own logic would now
                        # produce", and re-deriving is idempotent (falls
                        # through to the same branch below, which converges
                        # to the same answer if run again with unchanged
                        # inputs).
                        filled_multi.pop(vn, None)
                        sources.pop(vn, None)
                    else:
                        allowed_set = set(allowed_now)
                        kept = [v for v in filled_multi[vn] if v in allowed_set]
                        lost = [v for v in filled_multi[vn] if v not in allowed_set]
                        if lost:
                            dropped[vn] = lost
                            filled_multi[vn] = kept
                if not filled_multi.get(vn):
                    if sources.get(vn) == "user":
                        # An EMPTY selection the user explicitly confirmed
                        # ("no mounts needed" declining an optional grid) is
                        # a settled answer, not an unresolved attr — keep it
                        # so the question is never re-asked and the payload
                        # simply carries no rows. Only constraint-drops
                        # (non-user sources) fall through to re-resolution.
                        display_filled[vn] = "(none)"
                        continue
                    filled_multi.pop(vn, None)
                    sources.pop(vn, None)
                    # Falls through to normal resolution below — the drop may
                    # have emptied the selection entirely.
                else:
                    display_filled[vn] = ", ".join(
                        next((o.display_name for o in attr.options if o.item_value == v), v)
                        for v in filled_multi[vn]
                    )
                    continue

            if attr.hidden:
                # Never asked, never NL-hint-matched, never blind-first-picked
                # — a hidden attr only ever gets its own XML default_value
                # (BML scripts elsewhere may reference it), or is left out of
                # `filled` entirely if it has none. Never enters `pending`.
                # Pointer-defaults are NOT literals — resolved (or left
                # unfilled) by the post-pass below, never written verbatim.
                if _valid(attr.default_value) and not _is_pointer_default(attr):
                    filled[vn] = attr.default_value
                    display_filled[vn] = next(
                        (o.display_name for o in attr.options
                         if o.item_value == attr.default_value),
                        attr.default_value,
                    )
                    sources.setdefault(vn, "default")
                continue

            value: str | None = None
            display: str | None = None
            source: str = "auto"

            # 1. User hint matching — strip underscores/case, check fragment containment
            vn_flat = vn.lower().replace("_", "")
            for hint_key, hint_val in hints.items():
                hk_flat = hint_key.lower().replace("_", "")
                if hk_flat in vn_flat or vn_flat in hk_flat:
                    hv_lower = hint_val.lower()
                    # Priority 1: exact item_value match (e.g. hint="US" → item_value="US")
                    for opt in attr.options:
                        if opt.item_value.lower() == hv_lower:
                            value = opt.item_value
                            display = opt.display_name
                            break
                    # Priority 2: exact display_name match (prevents "United States"
                    # matching "United States Minor Outlying Islands" via word-boundary)
                    if not value:
                        for opt in attr.options:
                            if opt.display_name.lower() == hv_lower:
                                value = opt.item_value
                                display = opt.display_name
                                break
                    # Priority 3: word-boundary display match (catches partial names,
                    # prevents "us" matching "Austria")
                    if not value:
                        for opt in attr.options:
                            if re.search(r"\b" + re.escape(hv_lower) + r"\b",
                                         opt.display_name.lower()):
                                value = opt.item_value
                                display = opt.display_name
                                break
                    # Priority 4: country alias group (bidirectional) —
                    # a hint value that's ANY known alias for a country
                    # (full name, official name, alpha-2, alpha-3, or
                    # common colloquial name) matches an option whose own
                    # item_value/display_name is any OTHER alias in the
                    # same group. Fixed 2026-08-14: the old lookup was
                    # keyed one-directionally (full name -> abbreviation
                    # only), so a hint value that was ITSELF an
                    # abbreviation (e.g. "usa") could never look anything
                    # up — `_COUNTRY_HINT_SHORTHAND.get("usa", ())` always
                    # returned empty since "usa" was never a dict key.
                    # _country_alias_group is symmetric, closing that gap
                    # for real, for all 249 real ISO countries, not just
                    # the 2 the old dict hand-covered.
                    if not value and hint_key == "country":
                        alias_group = _country_alias_group(hv_lower)
                        if alias_group:
                            for opt in attr.options:
                                if (opt.item_value.lower() in alias_group
                                        or opt.display_name.lower() in alias_group):
                                    value = opt.item_value
                                    display = opt.display_name
                                    break
                    # Never assign an arbitrary hint string to a boolean-typed
                    # attr just because its name fragment-matched a hint key
                    # (e.g. "country" is a substring of
                    # "isUltimateDestinationCountryCA_astro") — confirmed
                    # live against the real CPQ API: this attr is a genuine
                    # boolean (data_type=4, real default "false"), and the
                    # fragment match wrongly assigned the literal country
                    # name "United States" to it, which the API rejected
                    # ("has to be either true or false"). A boolean attr's
                    # only valid values are true/false, never a hint's
                    # free-text content.
                    if (not value and not attr.options and _valid(hint_val)
                            and attr.select_type != "boolean"):
                        value = hint_val
                        display = hint_val
                    if value:
                        source = "hint"
                    break

            # 2. Recommendation rule already satisfied by the current filled
            # state — takes priority over the catalog's generic default_value
            # (see _satisfied_recommendation's docstring for the bug this closes).
            #
            # Constraint-filtered candidates, not the raw `attr.options` menu
            # (live regression, docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_
            # PLAN_2026_08_05.md follow-up): a script-backed recommendation
            # rule with a condition unrelated to the attribute a DIFFERENT,
            # ALREADY-ACTIVE constraint rule just narrowed can confidently
            # reassert a value the constraint has already ruled out —
            # confirmed live: "Default Service Type based on Solution Type
            # selected" unconditionally returns "ADVANCED" (its own
            # condition never depends on Hardware Version at all), while a
            # separate constraint rule keyed on Hardware Version had
            # already narrowed this same attr to 3 completely different
            # options. Passing the full, unfiltered menu here let the
            # recommendation win anyway — every turn, forever — because
            # _satisfied_recommendation's own membership check
            # (`candidate_opts`) only protects against a value that was
            # NEVER a real menu option, not one merely excluded by an
            # active constraint. This silently produced an internally
            # inconsistent "Configuration complete" (the recommendation
            # resolved the attribute so nothing was pending) that a
            # separate BOM-gate consistency check caught one full turn
            # later, only once the customer said "confirm".
            if not value and rec_by_target and attr.options:
                _allowed_for_rec = (
                    set(constrained_opts.get(attr.entity_id, []))
                    if constrained_opts else None
                )
                _rec_candidate_opts = [
                    o for o in attr.options
                    if _valid(o.item_value)
                    and (_allowed_for_rec is None or o.item_value in _allowed_for_rec)
                ]
                rec_match = _satisfied_recommendation(attr, _rec_candidate_opts)
                if rec_match:
                    value, display, fired_rule_name = rec_match
                    source = "rule"

            # 3. Default value (pointer-defaults excluded — see
            # _is_pointer_default above; the post-pass resolves them).
            # Also skipped when an active constraint has already narrowed
            # this attr's allowed set and the raw default isn't in it
            # (docs/config_consistency_issues_2026-07-30.md Issue 7
            # follow-up: the catalog's own generic default_value is not
            # guaranteed to satisfy a PRODUCT-SPECIFIC constraint rule —
            # confirmed live, Carry Type's catalog default "2.0 INCH /
            # 5.08 CM (STANDARD)" is genuinely invalid for APX NEXT Single
            # Band's own constraint rule, yet this step locked it in
            # unconditionally before the constraint-aware fallback a few
            # lines below (which already correctly picks a real, valid
            # option) ever got a chance to run — forcing a BOM-gate
            # correction round-trip on every single default order for
            # this product). Falling through here instead of locking in a
            # known-bad value lets that existing fallback do its job.
            _default_excluded_by_constraint = (
                constrained_opts is not None
                and attr.entity_id in constrained_opts
                and attr.default_value not in constrained_opts[attr.entity_id]
            )
            if (
                not value and _valid(attr.default_value)
                and not _is_pointer_default(attr)
                and not _default_excluded_by_constraint
                # §2d (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md): once a
                # layout map is loaded, a bare catalog default_value no
                # longer fills the attribute on its own — falls through to
                # the final ask-branch, which §2c then skips (not asks)
                # since this isn't a decision-anchor or grid selector.
                and display_order is None
            ):
                value = attr.default_value
                source = "default"
                display = next(
                    (o.display_name for o in attr.options
                     if o.item_value == attr.default_value),
                    attr.default_value,
                )
                # Issue 5 root cause 3 (docs/config_consistency_issues_
                # 2026-07-30.md): some menu attrs carry a legacy boolean-era
                # option pair (item_value "YES"/"NO") alongside a
                # differently-spelled current/canonical option that shares
                # the SAME display_name (confirmed live: baselineReleaseSW_
                # astro has both "YES"->"Baseline Release" and "BASELINE
                # RELEASE"->"Baseline Release"). If the catalog's
                # default_value happens to be the bare legacy "YES"/"NO"
                # spelling, prefer a same-display-name sibling option whose
                # item_value ISN'T a bare boolean literal — it's the same
                # real-world choice, just the non-deprecated spelling.
                # Generic (no attribute names hardcoded): only fires when
                # such a sibling genuinely exists, never invents a value.
                if value.strip().upper() in ("YES", "NO"):
                    _canonical_sibling = next(
                        (o for o in attr.options
                         if o.display_name == display
                         and o.item_value.strip().upper() not in ("YES", "NO")),
                        None,
                    )
                    if _canonical_sibling is not None:
                        value = _canonical_sibling.item_value
                        display = _canonical_sibling.display_name
            elif (not value and attr.select_type == "boolean"
                    and attr.default_value.strip().lower() in ("true", "false")
                    # §2d (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md): a
                    # second, separate default_value branch I missed on the
                    # first pass — same bare-catalog-default shape as the
                    # sibling branch above, gated the same way. Found live:
                    # a boolean attr's "true"/"false" default_value slipped
                    # through with a "default"-tagged value even after §2d
                    # shipped, because this branch has its own independent
                    # default_value check instead of sharing the one above.
                    and display_order is None):
                # _valid() treats the literal string "false" as a none-sentinel
                # (_NONE_VALUES) — correct for single-select dropdowns where
                # "FALSE" can mean "no selection", but wrong for a genuinely
                # boolean-typed attr, where "false" IS the real, meaningful
                # value. Without this, a boolean's own valid default gets
                # silently discarded here, falls through ungoverned, and
                # (confirmed live) can reach the decision-required cascade
                # below and get contaminated with an unrelated sibling's raw
                # string value (e.g. isUltimateDestinationCountryCA_astro
                # picking up "United States" from CRM_BILL_COUNTRY).
                value = attr.default_value.strip().lower()
                source = "default"
                display = "Yes" if value == "true" else "No"

            # 3/4. Rule-governed default-or-first (D2/§3), else the
            # conservative single-remaining-option fallback (NO EAGER
            # EVALUATION — Issue 6's "Stop and Wait" safeguard for anything
            # not rule-governed). Decision-required attrs (country/region —
            # hwVersion removed per D1, it's a normal dependent now) always
            # ask regardless of governance.
            is_decision_attr = (
                any(dk in vn_flat for dk in _DECISION_REQUIRED_KEYS)
                # Hardware Version is MANDATORY on hardware-based catalogs
                # (APX/aSTRO25) — never blind first-by-order; must be asked
                # (or matched from NL) before Product is even eligible.
                or self._is_hardware_version_attr(attr)
                # productSelectionProduct_all is a shared, catalog-wide
                # option list (e.g. 325 product-line codes across every
                # product family) with no rule reliably narrowing it to the
                # resolved product — blind first-by-order picked "APX6500"
                # for an APX NEXT quote (confirmed live). Exact variable-name
                # match, not a substring, so this never widens to unrelated
                # "product*" attrs. See
                # docs/CPQ_MULTI_CATALOG_ASK_FLOW_BUGS_PLAN.md Bug 3/3c.
                # skip_always_ask overrides this ONLY when the caller
                # already confirmed the real native UI never shows it (see
                # docstring) — every other catalog keeps this unconditional.
                # ALSO deferred from pending until hardware is filled — see
                # _order_pending_hardware_before_product at end of auto_fill.
                or (
                    vn == "productSelectionProduct_all"
                    and vn not in (skip_always_ask or ())
                )
                # "selectmodel"-named attrs can list real variants of ONE
                # product mixed with an unrelated accessory at a low menu
                # order (confirmed live: SVX's modelSelectionSelectModel_
                # viSoln has "V200 Body Worn Camera" at order=1 ahead of its
                # 3 real "SVX Video Remote Speaker Mic" variants) — blind
                # first-by-order silently picked the camera with zero
                # customer input. No rule or default_value backs this attr
                # in the ingested data (confirmed via direct Postgres query),
                # so hint-matching (checked above, unaffected by this flag)
                # is the only correct signal; without one, ask rather than
                # guess. Deliberately narrower than the full
                # _PRODUCT_IDENTIFIER_KEYS fragment set used to (see history
                # of commit 445595b) — "basemodel" and the others stay off
                # this override because they're rule-governed catalog master
                # lists, not a mix of unrelated products (APX's Base Model:
                # picking the rule-governed first option is safe there).
                # Same skip_always_ask carve-out as the productSelectionProduct_all
                # branch above -- resolve_always_ask_skips only ever populates
                # productSelectionProduct_all today, so this is currently
                # dormant, but without it any future extension of that method
                # to a "selectmodel"-named attr would have this generic
                # fragment match force it to always-ask anyway, reintroducing
                # the exact "asks a question the native UI never shows" bug
                # this carve-out pattern exists to prevent (Raven review).
                or ("selectmodel" in vn_flat and vn not in (skip_always_ask or ()))
                # Confirmed live (2026-08-08): modelSelectionbaseModel_astro
                # has 16 real menu options and an empty default_value, and
                # `governed_target_ids` DOES include it (some hiding rule
                # references it as a CONDITION variable -- an earlier direct
                # per-rule-type check missed this, using the wrong attribute
                # name on HidingRule and reporting a false "0 hiding rules"),
                # but being referenced as a condition is not the same as a
                # rule ever RESOLVING it -- confirmed live it stays empty
                # regardless of governed status (§2f's own comment already
                # notes "'governed' ... really only ever meant 'some rule
                # cares about this attr,' not 'a rule decided its value'").
                # Once §2c's display_order-gated skip became active, that
                # left a genuine, structurally load-bearing customer
                # decision (16 real, meaningfully different physical base
                # models) silently unfilled -- everything downstream
                # (carrier, frequency-band pairing, provisioning) that
                # conditions on base model never gets a chance to resolve.
                #
                # A broader "any ungoverned attr with 2+ options and no
                # default" rule was tried and reverted -- it can't be
                # distinguished from a genuinely fine-to-skip optional
                # attr (confirmed by test_auto_fill_skips_unresolvable_
                # non_anchor_attr_when_layout_loaded's own "someOptional
                # Choice_astro" fixture, identically shaped, deliberately
                # expected to skip) using anything generic available here.
                # Narrowed instead to the same fragment-match convention
                # _DECISION_REQUIRED_KEYS already uses for country/region
                # -- "basemodel" is a structural naming convention (a
                # physical hardware base model selector), not a literal
                # per-catalog name, so this still generalizes across any
                # catalog using it. Unconditional on governed status, same
                # as every other decision-key fragment/anchor in this
                # expression -- none of them gate on it either.
                or "basemodel" in vn_flat
            )
            is_governed = attr.entity_id in governed
            governed_source = "rule" if attr.entity_id in rule_governed else "optional"
            filled_multi_now = False

            # Region-from-country derivation: region is a decision-required
            # key (always ask, D2/§Phase M-adjacent) UNLESS the confirmed
            # country resolves to one of this attr's real options — country
            # itself is untouched, still always asked (D1).
            if not value and "region" in vn_flat and country and attr.options:
                derived = self.derive_region(country, attr)
                if derived:
                    value, display = derived
                    source = "country_derived"

            # Base Model region-allow default (see the precompute above) --
            # a real, confirmed per-region ALLOW value from an ingested
            # region-rule-shaped Data Table, not a blind guess. Checked
            # BEFORE the unconditional "basemodel" always-ask anchor above
            # gets to force this to `pending` -- only ever applies when
            # exactly one such value resolved.
            if not value and "basemodel" in vn_flat and _bm_region_allow_value and attr.options:
                match = next(
                    (o for o in attr.options if o.item_value == _bm_region_allow_value),
                    None,
                )
                if match:
                    value = match.item_value
                    display = match.display_name
                    source = "region_allow_default"

            if not value and attr.options:
                allowed_for_attr = (
                    set(constrained_opts.get(attr.entity_id, []))
                    if constrained_opts else None
                )
                valid_opts = [
                    o for o in attr.options
                    if _valid(o.item_value)
                    and (allowed_for_attr is None or o.item_value in allowed_for_attr)
                ]
                if len(valid_opts) == 1 and attr.entity_id not in user_answered_dropped_ids:
                    # Exactly one choice — auto-fill, no user decision needed.
                    #
                    # EXCLUDED when this attr's only-one-option state exists
                    # because a constraint just rejected the CUSTOMER'S OWN
                    # explicit answer this same turn (live-verified bug,
                    # 2026-07-23: changing Billing Option to "Annual" got
                    # silently replaced with "Immediate" — the drop was
                    # correctly detected and noted, but this branch — a
                    # DIFFERENT, earlier branch than the blind first-by-order
                    # fallback the existing user_answered_dropped_ids guard
                    # protects a few lines below — filled the one remaining
                    # option unconditionally, with no awareness that "only
                    # one option remains" was true BECAUSE it just excluded
                    # what the customer picked). Falls through to `pending`
                    # instead, same "a real decision deserves to be re-asked,
                    # not silently re-guessed" principle as the sibling fix
                    # (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 4) — the
                    # resume prompt shown for `pending` already tells the
                    # customer the one remaining valid option.
                    value = valid_opts[0].item_value
                    display = valid_opts[0].display_name
                elif (
                    is_governed and not is_decision_attr and valid_opts
                    # skip_always_ask only means "the native UI never shows
                    # a question for this" — it must NOT also unlock the
                    # blind first-by-order fallback below for
                    # productSelectionProduct_all specifically. That list is
                    # shared/catalog-wide (hundreds of unrelated product
                    # codes across every family), so first-by-order silently
                    # picks a foreign product's code (confirmed live: SVX
                    # session filled "APX6500" this way). Without this guard,
                    # suppressing the ask (is_decision_attr -> False) directly
                    # re-opens the exact failure this attr's is_decision_attr
                    # branch above exists to prevent.
                    and not (vn == "productSelectionProduct_all"
                             and vn in (skip_always_ask or ()))
                    # A real customer decision that a cascade just cleared
                    # deserves to be re-asked, not silently re-guessed — same
                    # "never blind-fill a real decision" principle as
                    # productSelectionProduct_all above, generalized to any
                    # attr whose cascade-dropped value was filled_source
                    # "user" (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 4).
                    and attr.entity_id not in user_answered_dropped_ids
                ):
                    if attr.select_type == "multi":
                        # docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_
                        # 2026_08_05.md — an active constraint narrowing to
                        # exactly ONE remaining option is exactly as
                        # unambiguous here as it already is for single-
                        # select (the `len(valid_opts) == 1` branch above);
                        # narrowing to SEVERAL remaining options is not the
                        # same signal and must not be auto-selected in
                        # full. Confirmed live: "Constrain Additional
                        # feature Type" (condition: any product selected —
                        # true for virtually every order) narrows
                        # additionalSystemEnhancementFeatureType_astro to 9
                        # of 11 options; that 9-item list is the catalog's
                        # MENU of available choices, not a recommendation
                        # to select all 9 — auto-selecting all 9
                        # (including "ICE KIT") silently triggered an
                        # unrelated constraint that collapsed a real
                        # question (Package Type) to zero valid options.
                        # allowed_for_attr is None → no active constraint
                        # narrowed this attr → leave unselected, ask the
                        # user (unchanged).
                        if allowed_for_attr is not None and len(valid_opts) == 1:
                            filled_multi[vn] = [o.item_value for o in valid_opts]
                            display_filled[vn] = ", ".join(o.display_name for o in valid_opts)
                            sources.setdefault(vn, governed_source)
                            filled_multi_now = True
                            if governed_source == "rule":
                                rule_trace.record_fire(
                                    rule_type="auto_fill", rule_id="auto_fill:rule_governed_multi",
                                    attr=vn, outcome=f"set={filled_multi[vn]}",
                                )
                        elif allowed_for_attr is None:
                            # No active rule-based constraint narrowed this
                            # multi-select attr — the script governing it
                            # either doesn't exist or failed to resolve.
                            # Same real-Data-Table attempt as the
                            # single-select _NEVER_GUESS_SCRIPT_GOVERNED
                            # branch below, applied here too since
                            # carrierSelectionMultiSelect_astro-shaped attrs
                            # are multi-select (docs proof §11-§12). Only
                            # ever fills confidently when exactly one real
                            # value resolves.
                            dt_match = self._resolve_via_data_tables(
                                vn, filled, valid_opts, workspace_id, catalog_prefix, dt_cache,
                            )
                            if dt_match:
                                filled_multi[vn] = [dt_match.item_value]
                                display_filled[vn] = dt_match.display_name
                                sources.setdefault(vn, "data_table")
                                filled_multi_now = True
                            # No confident single match (2+ legal values,
                            # or none): NOT handled here -- falls through
                            # (filled_multi_now stays False) to the second
                            # multi-select branch below, whose own
                            # `is_unconstrained and candidate_opts` case
                            # already correctly blind-picks the first real
                            # option (tagged "default_first_available") for
                            # this exact genuinely-unconstrained shape. An
                            # earlier version of this fix duplicated that
                            # logic here with a different tag, which broke
                            # the existing re-validation contract keyed on
                            # "default_first_available" (docs/CPQ_
                            # MULTISELECT_GOVERNED_NO_MATCH_ASK_PLAN_2026_08_
                            # 10.md) -- see that plan's real gap instead:
                            # `elif display_order is not None: pass` further
                            # below intercepts this case BEFORE it ever
                            # reaches the working is_unconstrained logic.
                    elif governed_source == "optional" and attr.entity_id in conflicted_optional_ids:
                        # This attr shares a real option value with another
                        # "optional"-tier attr — first-by-order would silently
                        # pick a competing value for what's very likely the
                        # same hardware/accessory slot (§ surveillance-package
                        # double-fill). Ask instead of guessing which one wins.
                        pass
                    elif vn in (negated_vns or ()):
                        # The customer explicitly negated this attr's concept
                        # (e.g. "exclude any multikey capability") but no
                        # option text let extract_catalog_hints resolve which
                        # specific option that means — first-by-order has no
                        # way to know either, and confirmed live it picked
                        # the literal opposite ("MULTIKEY"). Ask instead.
                        pass
                    else:
                        # Check for an already-satisfied recommendation before
                        # the blind first-by-order pick below claims this attr
                        # (see docstring — apply_recommendation_rules() runs
                        # AFTER this method in evaluate_rules_loop and never
                        # revisits an attr already in `filled`).
                        rec_match = (
                            _satisfied_recommendation(attr, valid_opts)
                            if rec_by_target else None
                        )
                        if rec_match:
                            value, display, fired_rule_name = rec_match
                            source = "rule"
                        elif (
                            dt_match := self._resolve_via_data_tables(
                                vn, filled, valid_opts, workspace_id, catalog_prefix, dt_cache,
                            )
                        ):
                            # This attr is governed (some rule targets it)
                            # but no active constraint narrowed it here —
                            # the governing rule is either script-based and
                            # just failed to resolve, or never fired at all.
                            # Before falling to "no recommendation applies"
                            # (_NEVER_GUESS_SCRIPT_GOVERNED) or a blind
                            # first-by-order guess, try the real ingested
                            # Data Table source (§11-§12 of the proof doc) —
                            # a different, catalog-wide data source than the
                            # script/rule evaluation that just failed, not a
                            # second guess at the same one. Only ever fills
                            # when exactly one real value resolves (see
                            # _resolve_via_data_tables); a no-op (None) when
                            # the caller didn't pass workspace_id.
                            value = dt_match.item_value
                            display = dt_match.display_name
                            source = "data_table"
                        elif vn in _NEVER_GUESS_SCRIPT_GOVERNED:
                            # This attr's only governing rule is script-based
                            # and just failed to resolve to a value above —
                            # confirmed live to legitimately mean "no
                            # recommendation applies" for this specific attr,
                            # not "unknown, guess anyway". Falls through to
                            # pending/ungoverned handling instead of guessing.
                            pass
                        elif (
                            display_order is not None
                            and allowed_for_attr is not None
                            and _valid(attr.default_value)
                        ):
                            # §2g (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md):
                            # narrow carve-out to §2f's skip below — an active
                            # constraint (allowed_for_attr is not None) means
                            # this attr's default_value has been CONFIRMED
                            # valid for this exact product/configuration right
                            # now, not just present in the catalog in the
                            # abstract (the bare-default case §2d/§2f still
                            # skip). Live-verified: APX NEXT Single Band's
                            # Frequency Bands (UHF/VHF/700/800 MHz, catalog
                            # default "700/800 MHZ") and Antenna Type
                            # (Whip/No Antenna, catalog default "WHIP APX
                            # NEXT") both survive their own active constraint.
                            # Case-insensitive match: the constraint rule's own
                            # `allowed_values` list and the menu's real
                            # item_value casing aren't guaranteed to agree
                            # character-for-character (confirmed live — same
                            # "700/800 MHz" concept, different case) even
                            # though every other exact-string comparison in
                            # this file assumes they do; only this new
                            # cross-source comparison needs the normalization.
                            _default_norm = attr.default_value.strip().upper()
                            match = next(
                                (o for o in valid_opts
                                 if o.item_value.strip().upper() == _default_norm),
                                None,
                            )
                            if match:
                                value = match.item_value
                                display = match.display_name
                                source = "default"
                        elif display_order is not None and vn in display_order:
                            # §2f, superseded by explicit instruction
                            # (2026-08-09): governed (some rule targets this
                            # attr) but nothing -- no active constraint, no
                            # satisfied recommendation, no Data Table match,
                            # no confirmed default_value -- resolved a value.
                            # Previously skipped entirely (never asked,
                            # never defaulted); now picks the first real,
                            # catalog-defined eligible option instead of
                            # falling through to `pending`, matching the
                            # identical first-by-order fallback the sibling
                            # `else` branch below already uses when no
                            # layout map is loaded. Tagged with a distinct
                            # source (not "default") so a later audit or
                            # revalidation pass can tell "guessed, nothing
                            # to justify it" apart from a genuine catalog
                            # default_value match -- same convention the
                            # multi-select "is_unconstrained" branch already
                            # uses (`source="default_first_available"`).
                            #
                            # docs/CPQ_DATA_TABLE_GOVERNED_LAYOUT_VISIBILITY_
                            # GAP_PLAN_2026_08_10.md: `and vn in display_order`
                            # added -- this was the DOMINANT source of the
                            # layout-visibility-baseline gap (26 real
                            # attributes confirmed live), bigger than the
                            # sibling _dt_governed_vns fix in this same file.
                            # `display_order is not None` alone only proves a
                            # layout map exists, not that THIS attr is in its
                            # visible set -- a layout-hidden but rule-governed
                            # attr with no other resolution signal was still
                            # blind-picked unconditionally. See the `elif`
                            # immediately below for the new layout-hidden case.
                            value = valid_opts[0].item_value
                            display = valid_opts[0].display_name
                            source = "default_first_available"
                        elif display_order is not None:
                            # Layout map loaded, but this attr isn't in its
                            # visible set -- the layout explicitly says never
                            # show it. Falls through with no value set, same
                            # as any other layout-hidden, unresolved attr
                            # (the final ask/skip decision below correctly
                            # skips it, since it's neither a decision attr
                            # nor a grid selector).
                            pass
                        else:
                            # single/boolean, 2+ options, no default: first by
                            # menu order — well-defined for boolean (only two
                            # states) and safe here because a rule REQUIRES this
                            # attr to be resolved for the cascade to proceed.
                            value = valid_opts[0].item_value
                            display = valid_opts[0].display_name
                            source = governed_source
                # else: 0 or 2+ options, ungoverned → pending (user must choose)
            elif (
                not value and is_governed and not is_decision_attr
                and attr.select_type == "boolean" and display_order is None
            ):
                # Governed boolean with no menu options at all: default to
                # "false" (unchecked) rather than leaving it perpetually
                # pending — a boolean's absent-default state is well-defined.
                # §2f: gated the same way as the sibling branch above — once
                # a layout map is loaded, this blind default is skipped too.
                value = "false"
                display = "No"
                source = governed_source

            if filled_multi_now:
                continue
            if value:
                # A value can reach here from several upstream paths (hint
                # match, default_value, region-derivation, single-remaining-
                # option, rule recommendation, boolean-default) — none of
                # which check select_type before this point. Route multi-
                # select attrs to filled_multi here too, not just in the
                # dedicated multi branch above, or a value assigned via any
                # of those other paths would land in `filled` as a scalar
                # and silently defeat build_payload's array serialization
                # for it (confirmed live: this is exactly what happened to
                # two attrs that got their value via hint-matching rather
                # than the dedicated multi/constrained-options branch).
                if attr.select_type == "multi":
                    filled_multi[vn] = [value]
                else:
                    filled[vn] = value
                display_filled[vn] = display or value
                sources.setdefault(vn, source)
                # Trace step 3 ("already-satisfied recommendation", source
                # == "rule") and step 5 ("rule-governed default-or-first",
                # source == governed_source == "rule") -- the two auto_fill
                # paths this method's own docstring documents as having
                # previously shipped real fill-ordering bugs
                # (solutionTypeDevices_astro, hWVersion_astro). Raven review
                # on PR #156: these were the only evaluate_rules_loop stage
                # ("hide -> recommend -> constrain -> auto-fill") left
                # untraced by the original rule_trace wiring.
                if source == "rule" or (is_governed and source == governed_source == "rule"):
                    # §2e (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md):
                    # attribute to the specific rule _satisfied_recommendation
                    # matched when we have one — lands in the same
                    # rule_type="recommendation" bucket apply_recommendation_
                    # rules' own trace entries use, so one query answers
                    # "which rule fired this attribute" either way. Falls
                    # back to the old generic tag only for step 5's
                    # governed_source path, which isn't _satisfied_
                    # recommendation-backed and has no single rule to name.
                    if fired_rule_name:
                        rule_trace.record_fire(
                            rule_type="recommendation", rule_id=fired_rule_name,
                            attr=vn, outcome=f"set={value}",
                        )
                    else:
                        rule_trace.record_fire(
                            rule_type="auto_fill", rule_id=f"auto_fill:{source}",
                            attr=vn, outcome=f"set={value}",
                        )
            elif (
                attr.select_type == "multi" and not attr.required
                and vn not in grid_selector_vns
            ):
                # A multi-select that reached here (no single-remaining-
                # option, not required=1 in the raw XML) has nothing
                # unambiguous to justify picking a subset on its own —
                # `valid_opts` from the branch above is NOT reliably in
                # scope here (only assigned inside the sibling `if not
                # value and attr.options:` block, which this attr never
                # entered if attr.options was empty — confirmed live:
                # UnboundLocalError on "APX NEXT All Band"). Recomputed
                # independently against the same constraint. Grid-linked
                # selectors (vn in grid_selector_vns) are excluded from
                # this branch — see grid_selector_vns comment above.
                #
                # Two distinct cases (explicit product decisions,
                # docs/CPQ_MULTISELECT_AUTOFILL_OVERSELECTION_PLAN_2026_08_
                # 05.md):
                #
                # 1. Genuinely UNCONSTRAINED (no active constraint rule
                #    ever targeted this attr this turn — real Oracle CPQ
                #    UI behavior for e.g. Service Type/Carrier Selection):
                #    prefer default_value; else first real menu option by
                #    order — never leave it silently empty. Confirmed
                #    live: relatedServicesType_astro ("Service Type") has
                #    zero active constraints and no default_value; the
                #    catalog's own first-listed real option is picked
                #    instead of guessing nothing.
                #
                # 2. CONSTRAINED but ambiguous (a real rule narrowed this
                #    attr to 2+ remaining options, just not exactly one):
                #    prefer default_value if still valid under that
                #    constraint; otherwise default to EMPTY, not first-
                #    available — picking an arbitrary one of several
                #    rule-narrowed options is exactly the guessing risk
                #    Fix 1 exists to prevent (confirmed live:
                #    additionalSystemEnhancementFeatureType_astro narrowed
                #    to 9 of 11 by a real constraint — picking option #1
                #    there would be exactly as arbitrary as picking all
                #    9 was). KNOWN, ACCEPTED RISK: _filled_by_rule_id
                #    treats that [] as a real, known-empty value, so a
                #    sibling rule keyed on "does NOT contain value X"
                #    (operator "8", disjoint-from) can fire on it as if
                #    the customer had confirmed nothing — the same
                #    mechanism that collapsed Package Type live via a
                #    separate, pre-existing catalog rule contradiction
                #    (see plan doc's "Known remaining issue").
                is_unconstrained = attr.entity_id not in (constrained_opts or {})
                current_allowed = (
                    set(constrained_opts.get(attr.entity_id, []))
                    if constrained_opts else None
                )
                candidate_opts = [
                    o for o in attr.options
                    if _valid(o.item_value)
                    and (current_allowed is None or o.item_value in current_allowed)
                ]
                # Priority, highest first: (1) a targeted RecommendationRule
                # already satisfied by the current filled state -- more
                # specific than a generic default_value, same "rule beats
                # default" priority _satisfied_recommendation's own
                # docstring establishes for single-select; (2) the XML
                # default_value; (3) first available (unconstrained case
                # only, see above). Multi-select attrs never reach
                # _satisfied_recommendation via the sibling "else" branch
                # above (mutually exclusive if/elif with this one), so it
                # must be checked here directly.
                rec_match = (
                    _satisfied_recommendation(attr, candidate_opts)
                    if rec_by_target else None
                )
                default_opt = next(
                    (o for o in candidate_opts if o.item_value == attr.default_value),
                    None,
                ) if attr.default_value else None
                if rec_match:
                    rec_value, rec_display, fired_rule_name = rec_match
                    filled_multi[vn] = [rec_value]
                    display_filled[vn] = rec_display
                    sources.setdefault(vn, "rule")
                    # §2e: this multi-select path never traced its fill at
                    # all before — a real, separate gap from the
                    # single-select trace call above, closed the same way.
                    rule_trace.record_fire(
                        rule_type="recommendation", rule_id=fired_rule_name,
                        attr=vn, outcome=f"set={rec_value}",
                    )
                elif display_order is not None and not (
                    is_unconstrained and candidate_opts
                    and (attr.entity_id in rule_governed or vn in _dt_governed_vns)
                ):
                    # §2d (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md):
                    # once a layout map is loaded, nothing satisfying a
                    # recommendation rule means skip entirely — never fall
                    # to default_value, never guess first-available, never
                    # even the explicit-empty placeholder below. Leaves
                    # filled_multi/display_filled/sources untouched for vn.
                    # `test_multiselect_first_available_skipped_when_layout_
                    # loaded` locks this in for a genuinely UNGOVERNED
                    # multi-select -- still correctly skipped, unchanged.
                    #
                    # Narrowed (docs/CPQ_MULTISELECT_GOVERNED_NO_MATCH_ASK_
                    # PLAN_2026_08_10.md): excludes the `is_unconstrained
                    # and candidate_opts` shape ONLY when the attr is also
                    # genuinely governed (rule_governed or _dt_governed_vns,
                    # the exact same distinction Group 1/Group 2 already
                    # established today for the single-select final chain)
                    # so THAT case falls through to its own, already-
                    # correct, already-tested handler a few lines below
                    # instead of being silently dropped here first.
                    # Confirmed live: carrierSelectionMultiSelect_astro
                    # (governed via real attrSequence Data Table coverage,
                    # no active constraint at all, 6 real options, nothing
                    # else resolves it) was reaching this `pass` and
                    # vanishing -- neither filled nor asked -- purely
                    # because a layout map happened to be loaded, which
                    # this branch was never meant to block for an attr the
                    # catalog's own data proves is governed. The
                    # CONSTRAINED-but-ambiguous case (is_unconstrained=
                    # False) still lands here and correctly stays
                    # untouched -- unchanged, matching the explicit HITL
                    # "default-or-empty, never guess among rule-narrowed
                    # options" decision this file's own multiselect
                    # over-selection tests already lock in.
                    pass
                elif default_opt:
                    filled_multi[vn] = [default_opt.item_value]
                    display_filled[vn] = default_opt.display_name
                    sources.setdefault(vn, "default")
                elif is_unconstrained and candidate_opts:
                    # Tagged with a DISTINCT source (not "default") so the
                    # re-validation step above (`if vn in filled_multi:`)
                    # can tell "guessed with nothing to justify it" apart
                    # from a genuine default_value match. Necessary because
                    # evaluate_rules_loop's fixed-point iteration can call
                    # auto_fill on an EARLY pass where this attr is
                    # genuinely unconstrained (e.g. before
                    # productSelectionProduct_all itself is filled), lock
                    # this guess into filled_multi, and then a LATER pass
                    # activates a real constraint on the same attr — the
                    # re-validation step would otherwise just confirm the
                    # guessed value is still technically a member of the
                    # new allowed set and keep it unquestioned, never
                    # re-deriving the correct Fix-3 default-or-empty
                    # answer for the now-real constraint (confirmed live:
                    # additionalSystemEnhancementFeatureType_astro got
                    # guessed "DISABLE CLOUD SERVICES" before Product was
                    # resolved, then kept it across every later pass even
                    # after its real 9-of-11 constraint activated).
                    # docs/CPQ_MULTISELECT_BLIND_PICK_RESPECTS_WHITELIST_
                    # PLAN_2026_08_10.md -- confirmed live (carrierSelection
                    # MultiSelect_astro): the raw catalog menu order can
                    # include real, data-proven-ILLEGAL options for the
                    # current context (e.g. a carrier only legal for a
                    # different destination country). When the real
                    # ingested Data Table has ANY coverage for this attr
                    # here -- even narrowed to 2+ values, not just the
                    # single-confident-match case _resolve_via_data_tables
                    # already handles above -- pick from that real,
                    # narrowed set instead of the unfiltered raw menu.
                    # `None` (no table coverage at all) falls back to
                    # today's original raw-order pick, unchanged.
                    _dt_legal = (
                        self._resolve_narrowed_legal_values(
                            vn, filled, workspace_id, catalog_prefix, dt_cache,
                        )
                        if workspace_id is not None else None
                    )
                    _narrowed_opts = (
                        [o for o in candidate_opts if o.item_value in _dt_legal]
                        if _dt_legal is not None else candidate_opts
                    )
                    if _narrowed_opts:
                        first_opt = _narrowed_opts[0]
                        filled_multi[vn] = [first_opt.item_value]
                        display_filled[vn] = first_opt.display_name
                        sources.setdefault(vn, "default_first_available")
                    else:
                        # Real Data Table confirms ZERO legal values for
                        # this exact context (`_dt_legal == []`) -- a
                        # genuine, data-proven answer, not something to
                        # guess past. Same empty outcome as the sibling
                        # `else` below, reached here instead since
                        # `is_unconstrained and candidate_opts` already
                        # matched on the raw (pre-whitelist) option list.
                        filled_multi[vn] = []
                        display_filled[vn] = "(none)"
                        sources.setdefault(vn, "default")
                else:
                    filled_multi[vn] = []
                    display_filled[vn] = "(none)"
                    sources.setdefault(vn, "default")
            elif self._is_noise_var(vn) and attr.options:
                # Company-level/system attrs (_BM_USER_CURRENCY, _BM_USER_
                # LANGUAGE, _BM_USER_NUMBER_FORMAT, ...) are already excluded
                # from the final payload by _is_noise_var (build_payload) —
                # asking about them in conversation is inconsistent with that
                # (confirmed live: these got asked, with duplicate options,
                # right before a bug that never affects the submitted BOM).
                # Auto-default instead of asking: prefer the XML default_value
                # if it's a real option, else first by order — same rule
                # already used for governed single/boolean attrs above.
                valid_opts = [o for o in attr.options if _valid(o.item_value)]
                fallback = next(
                    (o for o in valid_opts if o.item_value == attr.default_value),
                    valid_opts[0] if valid_opts else None,
                )
                if fallback:
                    filled[vn] = fallback.item_value
                    display_filled[vn] = fallback.display_name
                    sources.setdefault(vn, "default")
            elif (
                (attr.options or is_decision_attr
                 or self.should_ask_free_text_attr(attr, validation_rules, bml_eval))
                and not self._is_noise_var(vn)
                # skip_always_ask means the native UI never shows a question
                # for this attr in this catalog — it must be excluded from
                # `pending` too, not just from is_decision_attr's always-ask
                # override above. `attr.options` alone would otherwise put it
                # right back into pending (confirmed live: SVX asked
                # productSelectionProduct_all again once the first-by-order
                # auto-fill leak above was fixed, because this branch never
                # consulted skip_always_ask on its own).
                # Same carve-out extended to "selectmodel"-named attrs,
                # matching is_decision_attr's own dormant-but-structural
                # skip_always_ask exception above -- an ungoverned
                # "selectmodel" attr (is_governed False, so the governed
                # blind-fallback elif never fires) falls straight through to
                # this branch on `attr.options` alone regardless of
                # is_decision_attr, so it needs this same exclusion too.
                and not (
                    vn in (skip_always_ask or ())
                    and (vn == "productSelectionProduct_all" or "selectmodel" in vn_flat)
                )
            ):
                # Attrs with a meaningful choice set OR decision-required free-text
                # attrs (region/country) go to pending for user input.
                # Free-text CRM/system fields with no options and no decision
                # requirement are skipped — they are filled by integration.
                # `not _is_noise_var`: integration fields must NEVER be asked
                # even when a decision-key fragment matches their name —
                # confirmed live (Issue 9, docs/CPQ_PRODUCT_SWITCH_ISSUE.md):
                # CRM_BILL_COUNTRY ("Bill Country") got decision-promoted via
                # its "country" fragment and asked first after a product
                # switch, while build_payload drops it unconditionally — the
                # answer was collected then silently discarded. Same predicate
                # the payload exclusion trusts; zero rule impact (no BML
                # script in either catalog reads CRM_BILL_*/CRM_SHIP_*).
                #
                # §2c (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md): when a
                # layout map is loaded, only the anchors (is_decision_attr —
                # Country/Region/Hardware Version/Product) and grid-linked
                # selectors (never auto-fillable, explicit product decision)
                # actually get asked. Everything else that reaches this
                # branch has nothing resolving it via hint/recommendation/
                # default — skip it (leave unfilled, not defaulted-empty)
                # rather than asking, per your explicit call. Sibling-forced
                # re-asks (enforce_exclusive_sibling_families) are a
                # separate code path, unaffected either way. No layout map
                # loaded → today's unchanged "ask everything with options".
                #
                # EXPLICIT INSTRUCTION (2026-08-10, HITL-confirmed): for an
                # attr confirmed real-Data-Table-governed for THIS base
                # model (vn in _dt_governed_vns) but with no rule/Data
                # Table VALUE resolving it and no narrowing signal anywhere
                # (confirmed exhaustively for several such attrs this
                # session -- Additional Frequency Bands, Extend Range,
                # spare-radio pair, System Key, Configuration Type, battery
                # type, keypad type), blind-pick the first real catalog
                # option instead of asking -- same first-by-order fallback
                # §2f already uses for ungoverned attrs, extended here to
                # this confirmed-governed case by explicit user choice.
                # User accepted the tradeoff in full: this maximizes for
                # turn count (≤3 turns), not per-attribute correctness --
                # unlike default_first_available's re-validation (auto_fill
                # re-opens it once real narrowing data appears), there is
                # NO narrowing data to re-check against here, so this can
                # never self-correct on a later pass. `_dt_never_governed_
                # anywhere` is untouched -- that's a different, unrelated
                # safety net (never silently drop an attr no table ever
                # mentions) and still forces `pending` as before.
                #
                # docs/CPQ_DATA_TABLE_GOVERNED_LAYOUT_VISIBILITY_GAP_PLAN_
                # 2026_08_10.md: `and (display_order is None or vn in
                # display_order)` added below -- confirmed live an
                # attrSequence-governed attr the LAYOUT explicitly hides
                # (hide:true) was still reaching this branch and landing in
                # `pending` when it had no blind-pickable option, bypassing
                # the layout-visibility baseline the sibling `elif` right
                # below already enforces. No behavior change when no layout
                # map is loaded, or for any attr the layout actually allows
                # -- only a layout-hidden attr's outcome changes, falling
                # through to the sibling `elif` instead (which correctly
                # skips it, matching every other layout-hidden attr).
                if is_decision_attr or vn in grid_selector_vns:
                    # Forced-ask anchors (Country/Region/Hardware Version/
                    # Product) and grid-linked selectors are never auto-
                    # fillable -- always ask regardless of rule governance
                    # or data gaps below. Unchanged from before this fix.
                    # Checked FIRST, ahead of _dt_governed_vns below, same
                    # priority order the pre-existing final `elif` used to
                    # enforce before this restructuring.
                    pending.append(attr)
                elif (
                    attr.entity_id in _missing_data_target_ids
                    or attr.source_id in _missing_data_target_ids
                ):
                    # docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_BLIND_PICK_
                    # PLAN_2026_08_10.md Group 1 -- checked BEFORE
                    # _dt_governed_vns below: confirmed live the real Group
                    # 1 attrs (cBPQRCode_astro/fedQRCode_astro/
                    # dHSAssetTagLabel_astro) ARE ALSO attrSequence-Data-
                    # Table-governed, so without this ordering they'd hit
                    # that branch's own blind-pick/pending decision first
                    # and never reach this check at all. `attr.source_id`
                    # checked too, not just `attr.entity_id` -- confirmed
                    # live the real hiding rule's `target_attr_id` (e.g.
                    # 18302531462 for cBPQRCode_astro) is the BM-native
                    # source id, not the FalkorDB graph entity_id (292414);
                    # same entity_id-vs-source_id duplicate-id convention
                    # `_satisfied_recommendation` already accounts for
                    # elsewhere in this file. This attr's only real
                    # governance is a hiding rule that can never resolve
                    # (depends on a data table confirmed absent from every
                    # ingested catalog, see _KNOWN_MISSING_DATA_TABLES).
                    # Asking about it forever would never converge -- warn
                    # (traceable, auditable) and skip: no fill, no pending,
                    # leave it genuinely unresolved until the real data gap
                    # (CPQ_USER_GROUP_MAPPING_HIDING_RULE_PLAN_2026_08_10.md)
                    # is actually closed.
                    logger.warning(
                        "cpq: %r skipped -- its only hiding rule depends on "
                        "a data table confirmed absent from this catalog "
                        "(%s); will never resolve until that data is "
                        "ingested", vn, ", ".join(_KNOWN_MISSING_DATA_TABLES),
                    )
                elif vn in _dt_governed_vns and (
                    display_order is None or vn in display_order
                ):
                    # Deliberately checks key PRESENCE, not the whole dict's
                    # truthiness (docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_
                    # BLIND_PICK_PLAN_2026_08_10.md) -- confirmed live this
                    # attr-absent-from-constrained_opts case is the DOMINANT
                    # real shape: apply_constraint_rules only adds an entry
                    # for attrs an active constraint actually fired against;
                    # an attr with no active constraint firing has no entry
                    # at all, meaning every real catalog option remains
                    # legal, not zero. The original `.get(id, [])` pattern
                    # treated "not a key" identically to "constrained to
                    # nothing", silently sending real, blind-pickable attrs
                    # (wirelessCarrier_astro, subscriptionBillingAddDMS
                    # Coverage_astro, ...) straight to `pending` below with
                    # an artificially-empty `_blind_opts` instead of ever
                    # offering them a real option to pick from.
                    _blind_allowed = (
                        set(constrained_opts[attr.entity_id])
                        if constrained_opts and attr.entity_id in constrained_opts
                        else None
                    )
                    _blind_opts = [
                        o for o in attr.options
                        if _valid(o.item_value)
                        and (_blind_allowed is None or o.item_value in _blind_allowed)
                    ]
                    if _blind_opts:
                        _blind_first = _blind_opts[0]
                        filled[vn] = _blind_first.item_value
                        display_filled[vn] = _blind_first.display_name
                        sources.setdefault(vn, "blind_pick_governed")
                    else:
                        pending.append(attr)
                elif (
                    attr.entity_id in rule_governed
                    and attr.select_type != "multi"
                    and vn not in _NEVER_GUESS_SCRIPT_GOVERNED
                    and attr.entity_id not in user_answered_dropped_ids
                    and not _valid(attr.default_value)
                ):
                    # docs/CPQ_DATA_GAP_SKIP_AND_RULE_GOVERNED_BLIND_PICK_
                    # PLAN_2026_08_10.md Group 2 -- real recommendation/
                    # constraint/hiding rules target this attr, but none
                    # fired for this exact product/region/bundle and the
                    # catalog has NO default_value at all (an attr WITH a
                    # default_value that simply didn't survive an active
                    # constraint is a structurally different, already-
                    # correct case -- stays unfilled, not force-picked --
                    # see test_default_value_not_used_when_it_does_not_
                    # survive_the_constraint). HITL-confirmed generic
                    # policy: blind-pick the first rule-valid option rather
                    # than ask forever -- same tradeoff already accepted
                    # for Data-Table-sequence-governed attrs a few lines
                    # above, extended here to the ordinary-rule-governed
                    # case. Three existing safety nets still apply
                    # unconditionally: `_NEVER_GUESS_SCRIPT_GOVERNED` (a
                    # curated allowlist of attrs already confirmed broken by
                    # blind-picking, see that constant's own docstring/
                    # history), `user_answered_dropped_ids` (a cascade just
                    # invalidated the customer's own prior answer this pass
                    # -- must be RE-ASKED, never silently reguessed, same
                    # guard the exactly-one-remaining-option shortcut above
                    # already uses), and falling through to the unchanged
                    # safety net below if there's nothing valid to pick from
                    # at all (never silently drop the attr). select_type !=
                    # "multi" excluded here -- this branch only ever writes
                    # a scalar into `filled`; a multi-select target needs
                    # `filled_multi`'s list form instead (confirmed live
                    # elsewhere in this file: writing a scalar for a
                    # multi-select attr silently defeats build_payload's
                    # array serialization for it). Multi-select rule-
                    # governed attrs in this exact shape still fall through
                    # to the unchanged safety net below (ask), not covered
                    # by this pass.
                    #
                    # Deliberately checks key PRESENCE, not the whole dict's
                    # truthiness (unlike the `allowed_for_attr` computed
                    # earlier in this same function, ~line 6583) --
                    # apply_constraint_rules' own docstring confirms
                    # constrained_opts only holds entries for attrs with an
                    # ACTIVE firing constraint; an attr absent from it has no
                    # active constraint at all, so every real catalog option
                    # is genuinely legal to pick from -- not zero. Using
                    # `.get(id, [])` here (empty-list default whenever this
                    # attr merely isn't a key, e.g. some OTHER unrelated
                    # attr's constraint fired this turn) would make this
                    # branch pick from nothing for the exact real-world shape
                    # (Wireless Carrier, Include Accidental Damage, ...) this
                    # fix exists for.
                    _rg_allowed = (
                        set(constrained_opts[attr.entity_id])
                        if constrained_opts and attr.entity_id in constrained_opts
                        else None
                    )
                    _rg_opts = [
                        o for o in attr.options
                        if _valid(o.item_value)
                        and (_rg_allowed is None or o.item_value in _rg_allowed)
                    ]
                    if _rg_opts:
                        _rg_first = _rg_opts[0]
                        filled[vn] = _rg_first.item_value
                        display_filled[vn] = _rg_first.display_name
                        sources.setdefault(vn, "blind_pick_rule_governed")
                    else:
                        pending.append(attr)
                elif (
                    display_order is None
                    # docs/CPQ_DATA_TABLE_GOVERNED_LAYOUT_VISIBILITY_GAP_
                    # PLAN_2026_08_10.md: `vn in display_order and` added --
                    # this was the THIRD, dominant instance of the same gap
                    # (confirmed live: backupPTT_astro/rFIDRFIDEquipped_
                    # astro/cableDataCable_astro have zero real attrSequence
                    # coverage for ANY base model, so _dt_never_governed_
                    # anywhere is True for them regardless of layout). That
                    # safety net exists to never silently drop an attr the
                    # catalog tracks nowhere AND the layout gives no
                    # guidance on either -- but when the layout EXPLICITLY
                    # hides an attr, that is not silence, it is a real
                    # instruction, and it must win over an "unknown, ask to
                    # be safe" fallback the same way it wins everywhere
                    # else. No behavior change when no layout map is loaded
                    # or the attr is layout-visible. This branch is now only
                    # reached by attrs with ZERO rule governance at all
                    # (Group 2's blind-pick above already claims every
                    # rule-governed case with a real option to pick).
                    or (vn in display_order and _dt_never_governed_anywhere(vn))
                ):
                    pending.append(attr)

        # Pointer-default resolution post-pass (Issue 11): an unfilled
        # pointer attr inherits its REFERENCED attribute's value once that
        # value exists — reproducing what the source platform's own runtime
        # rule does (BM's "Set Model Name to All Product Family attribute
        # modelname" copies _bm_model_variable_name into modelname_all).
        # If the referenced attr never fills (e.g. APX Next, where the
        # model context is ambiguous), the pointer attr stays unfilled —
        # the token itself is never shipped as data.
        for attr in attrs:
            vn = attr.variable_name
            if vn in filled or not _is_pointer_default(attr):
                continue
            ref_value = filled.get(attr.default_value)
            if ref_value:
                filled[vn] = ref_value
                display_filled[vn] = display_filled.get(attr.default_value, ref_value)
                sources.setdefault(vn, "cascade")

        # Cascade fill: for any pending free-text attr that shares a decision
        # key fragment with an already-filled attr (e.g. packageRegion ← region
        # from modelSelectionRegion_astro), fill it directly from the filled
        # sibling. This handles attrs whose item_value is a None sentinel (e.g.
        # "NA" = North America but also "na" in _NONE_VALUES) by trusting the
        # value that was validated via options on the sibling attr.
        still_pending: list[ConfigAttr] = []
        for attr in pending:
            vn_flat_p = attr.variable_name.lower().replace("_", "")
            if attr.options:
                still_pending.append(attr)
                continue
            if attr.select_type == "boolean":
                # A boolean's absent-default state is well-defined (default
                # to "false" — see the governed-boolean fallback above) —
                # never let it fall into the free-text cascade below, which
                # blindly copies ANY same-fragment sibling's raw value with
                # no type check. Confirmed live: a boolean attr named
                # "isUltimateDestinationCountryCA_astro" matched the
                # "country" decision-key fragment and got contaminated with
                # "United States" (a raw string from CRM_BILL_COUNTRY) this
                # way — nonsensical for a true/false field and exactly the
                # payload-shape mismatch the real CPQ API previously rejected.
                filled[attr.variable_name] = "false"
                display_filled[attr.variable_name] = "No"
                sources.setdefault(attr.variable_name, "default")
                continue
            matched_dk = next(
                (dk for dk in _DECISION_REQUIRED_KEYS if dk in vn_flat_p), None
            )
            if not matched_dk:
                still_pending.append(attr)
                continue
            # Find a filled sibling that shares this key fragment
            cascaded = next(
                (v for k, v in filled.items()
                 if matched_dk in k.lower().replace("_", "") and v),
                None,
            )
            if cascaded:
                filled[attr.variable_name] = cascaded
                display_filled[attr.variable_name] = cascaded
                sources.setdefault(attr.variable_name, "cascade")
            else:
                still_pending.append(attr)
        pending = still_pending

        # Hardware-based catalogs: country/region → Hardware (mandatory) →
        # other attrs → Product last; Product deferred until Hardware filled.
        pending = self._order_pending_hardware_before_product(
            pending, filled, attrs, display_order=display_order,
        )

        return filled, display_filled, pending

    @staticmethod
    def _is_hardware_version_attr(attr: "ConfigAttr") -> bool:
        """True for Hardware Version attrs (hWVersion_*, Hardware Version label).

        Hardware is mandatory on hardware-based product catalogs — used both
        to force always-ask and to order pending ahead of Product.
        """
        vn_flat = (attr.variable_name or "").lower().replace("_", "")
        label = (attr.display_label or "").lower()
        if "hwversion" in vn_flat or "hardwareversion" in vn_flat:
            return True
        if "hardware" in label and "version" in label:
            return True
        return False

    @staticmethod
    def _is_product_line_selector(attr: "ConfigAttr") -> bool:
        """True for the shared multi-family Product dropdown (~325 options)."""
        vn = attr.variable_name or ""
        if vn in _PRODUCT_LINE_SELECTOR_EXACT:
            return True
        vn_flat = vn.lower().replace("_", "")
        if "productselectionproduct" in vn_flat:
            return True
        label = (attr.display_label or "").strip().lower()
        if label == "product" and len(attr.options) > _MAX_ENUMERATED_OPTIONS:
            return True
        return False

    def _order_pending_hardware_before_product(
        self,
        pending: list["ConfigAttr"],
        filled: dict[str, str],
        attrs: list["ConfigAttr"],
        display_order: dict[str, int] | None = None,
    ) -> list["ConfigAttr"]:
        """Defer Product until Hardware is filled; sort pending by dependency.

        Live-confirmed (2026-07-28): after country was set, next prompt was
        Product with 325 options because productSelectionProduct_all is
        always-ask and catalog order listed it before Hardware. On
        hardware-based catalogs Hardware is mandatory and constrains Product
        — never ask the unconstrained product portfolio first.

        display_order — docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2b:
        when supplied, the real native UI's own sequence wins over the
        catalog-agnostic heuristic below (confirmed live to already agree
        with it on APX Next: Country → Hardware Version → Product). The
        Hardware-before-Product deferral itself is a correctness
        constraint (Product's options are genuinely unconstrained without
        it), not just an ordering preference, so it still applies first;
        display_order only changes the final sort key.
        """
        if not pending:
            return pending
        if display_order is not None:
            # Deferral still applies (see docstring); ranking is layout
            # position, with anything absent from the map (shouldn't
            # happen once display_order-gated §2c is active, since
            # pending would only ever hold decision attrs/grid selectors —
            # both real layout members) sorted after everything ranked.
            catalog_has_hw = any(self._is_hardware_version_attr(a) for a in attrs)
            if catalog_has_hw:
                hw_vns = {
                    a.variable_name for a in attrs if self._is_hardware_version_attr(a)
                }
                hw_filled = any(vn in filled and filled.get(vn) for vn in hw_vns)
                if not hw_filled:
                    pending = [a for a in pending if not self._is_product_line_selector(a)]
            return sorted(
                pending,
                key=lambda a: display_order.get(a.variable_name, 10**9),
            )

        catalog_has_hw = any(self._is_hardware_version_attr(a) for a in attrs)
        if not catalog_has_hw:
            # Non-hardware catalog (e.g. pure software): keep country first,
            # then original relative order.
            countryish = [
                a for a in pending
                if any(
                    dk in a.variable_name.lower().replace("_", "")
                    for dk in _DECISION_REQUIRED_KEYS
                )
            ]
            rest = [a for a in pending if a not in countryish]
            return countryish + rest

        hw_vns = {
            a.variable_name for a in attrs if self._is_hardware_version_attr(a)
        }
        hw_filled = any(vn in filled and filled.get(vn) for vn in hw_vns)

        # Drop product-line selectors from pending until hardware is known.
        if not hw_filled:
            pending = [
                a for a in pending if not self._is_product_line_selector(a)
            ]

        def _rank(a: "ConfigAttr") -> tuple[int, int]:
            vn_flat = a.variable_name.lower().replace("_", "")
            if any(dk in vn_flat for dk in _DECISION_REQUIRED_KEYS):
                return (0, a.order)
            if self._is_hardware_version_attr(a):
                return (1, a.order)
            if self._is_product_line_selector(a):
                return (3, a.order)
            return (2, a.order)

        return sorted(pending, key=_rank)

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

    def detect_response_mode_request(self, question: str) -> str | None:
        """Return "json" | "batch" | None for an explicit presentation request.

        CPQ_CASCADE_CONVERSATION_PLAN.md §6: the client gets the rich default
        (verbose narrative, one question at a time) unless they explicitly
        ask for the JSON payload or the full batch of pending questions.
        """
        if self._JSON_REQUEST_RE.search(question):
            return "json"
        if self._BATCH_REQUEST_RE.search(question):
            return "batch"
        return None

    # Approval keywords — user is confirming the configuration (Step 8 trigger)
    _APPROVAL_RE = re.compile(
        r"^(?:i\s+(?:hereby\s+|just\s+|really\s+)?)?"
        r"(yes|confirm(?:ed)?|approve(?:d)?|submit|finali[sz]e|"
        r"looks?\s+good|that'?s?\s+(correct|right|good|it)|go\s+ahead|"
        r"proceed|ok(?:ay)?|all\s+good|send\s+it|let'?s?\s+go)\b|"
        r"^(?:great|perfect)\b[\s,!.]*(?:let'?s?\s+go|that'?s?\s+(?:works|good|right))?$",
        re.IGNORECASE,
    )

    # Q&A intent signals — user is asking a question, not answering a config prompt
    _QA_INTENT_RE = re.compile(
        r"^(what|why|how|explain|tell\s+me|describe|what'?s?\s*(is|are)?|"
        r"difference\s+between|compare|which\s+is\s+(better|best)|"
        r"can\s+you\s+explain|why\s+can'?t|how\s+does|how\s+do)\b",
        re.IGNORECASE,
    )

    # Change-request verbs — user wants to modify a filled attr (Step 6 cascade).
    # Conjugated forms ("-ing", "-e") are included so "i am changing" / "switching"
    # / "replacing" all fire has_change_verb=True and activate the attr-name guard.
    _CHANGE_VERB_RE = re.compile(
        r"\b(choos(?:e|ing)|select(?:ing)?|pick(?:ing)?|"
        r"swapp?(?:ing)?|chang(?:e|ing)|switch(?:ing)?|replac(?:e|ing)|"
        r"updat(?:e|ing)|modif(?:y|ying)|actually|instead|"
        r"make\s+it|i\s+want|use\s+.+\s+instead)\b",
        re.IGNORECASE,
    )
    # An arrow ("→" or "->") is unambiguous "set this to that" notation on
    # its own — confirmed live: "chnage mounting type Jacket Magnetic Mount
    # Quantity → 89" has NO word _CHANGE_VERB_RE recognizes (the typo
    # "chnage" doesn't contain "chang"), so has_change_verb was False and
    # the entire free-text number-extraction branch below never ran at all.
    # Rather than attempt general typo-tolerance (fuzzy, risky — this
    # engine's "never guess" discipline), the arrow itself is treated as an
    # equally strong, unambiguous change signal — same tier as a real verb.
    _ARROW_RE = re.compile(r"->|→")

    # Removal verbs — user wants to DESELECT an already-chosen multi-select
    # option, not add a new one (docs: Ask page needs to let a customer
    # deselect a mount type, not just add more). Deliberately distinct from
    # _CHANGE_VERB_RE: "change X to Y" replaces a single-select's value,
    # while "remove X" subtracts one option from an existing multi-select
    # selection — different verbs, different target data structure
    # (filled_multi, never filled).
    _REMOVE_VERB_RE = re.compile(
        r"\b(remove|deselect|de-select|delete|drop|uncheck|take\s+out|"
        r"get\s+rid\s+of|don'?t\s+need)\b",
        re.IGNORECASE,
    )

    def detect_multi_select_removal(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled_multi: dict[str, list[str]],
    ) -> "tuple[ConfigAttr, list[str]] | None":
        """Detect "remove X"/"deselect X" against an already-selected
        multi-select option (e.g. "remove Jacket Magnetic Mount" after
        selecting both Shirt and Jacket).

        Confirmed live this was a real gap: apply_multi_answer/
        _handle_cascade's multi-select branch only ever UNIONS mentioned
        options with the current selection (by design, for the "also
        include X" add case) — there was no removal path at all, so
        "remove Jacket Magnetic Mount" fell straight through to "I didn't
        quite catch that" with both mounts still selected.

        Returns (attr, item_values_to_remove) or None. Only fires when a
        removal verb is present AND at least one mentioned option is
        genuinely already in the current selection — naming an option
        that isn't currently selected is not a removal request (falls
        through to the normal change-request/collision paths instead, same
        "never guess" discipline as everywhere else in this file).
        """
        if not self._REMOVE_VERB_RE.search(question):
            return None
        for attr in attrs:
            if attr.select_type != "multi":
                continue
            current = filled_multi.get(attr.variable_name)
            if not current:
                continue
            mentioned = self.apply_multi_answer(attr, question)
            to_remove = [iv for iv, _dn in mentioned if iv in current]
            if to_remove:
                return attr, to_remove
        return None

    # "add/activate/include/bring back/turn on X" — re-activating a real,
    # currently-excluded, optional catalog attr post-quote-generation
    # (docs/CPQ_POST_QUOTE_EDIT_AND_QA_PLAN.md D2). Deliberately distinct
    # from _CHANGE_VERB_RE: "change X to Y" replaces an already-visible
    # attr's value, while "add X" re-activates something not currently
    # part of the quote at all.
    _ADD_VERB_RE = re.compile(
        r"\b(add|activate|include|bring\s+back|re-?add|reactivate|turn\s+on)\b",
        re.IGNORECASE,
    )

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
        """Detect "add X"/"activate X" re-activating a real, currently-
        excluded, optional attribute (D2). Never an invented field, never
        a required one, never a bypass of a currently-active hiding rule.

        A single unified eligibility check covers all 3 of D2's source
        pools at once: `required == False`, not `attr.hidden` (BM-native
        permanent hidden — a different concept from rule-conditional
        hiding, never surfaced regardless of rule state), not already
        filled/selected, and NOT currently hidden by an active hiding
        rule (re-checked live against the CURRENT filled state via
        `apply_hiding_rules`, never a cached/stale exclusion set — an
        attr whose hiding condition is still true is never a candidate,
        full stop). This naturally covers a declined multi-select (empty
        `filled_multi`), a flow-exclusion-dropped attr
        (`payload_flow_exclusions`), and a hiding-rule-excluded attr
        whose condition lapsed — all three reduce to the same "real,
        optional, currently invisible, not rule-blocked" predicate.
        """
        if not self._ADD_VERB_RE.search(question):
            return None
        _visible_now, _msgs, hidden_now = self.apply_hiding_rules(
            attrs, filled, hiding_rules, bml_eval=bml_eval, filled_multi=filled_multi)
        q_lower = question.lower()
        for attr in attrs:
            vn = attr.variable_name
            if attr.required or attr.hidden:
                continue
            if vn in filled or filled_multi.get(vn):
                continue
            if vn in hidden_now:
                continue  # still genuinely hidden by an active rule
            if _label_mentioned_strict(attr.display_label.lower(), q_lower):
                return attr
        return None

    # "clear/unset/blank X" — nullifying an optional SINGLE-select attr's
    # current value back to empty (D4). Distinct from _REMOVE_VERB_RE
    # (multi-select deselection, a different data structure entirely) and
    # from _CHANGE_VERB_RE (replacing with a different concrete value).
    _CLEAR_VERB_RE = re.compile(
        r"\b(clear|unset|blank|leave\s+(?:it\s+)?(?:blank|empty|unset))\b",
        re.IGNORECASE,
    )

    def detect_attr_clear(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        rec_rules: list[RecommendationRule],
        con_rules: list[ConstraintRule],
        bml_eval: BmlEvaluator | None = None,
    ) -> ConfigAttr | None:
        """Detect "clear X"/"unset X" nullifying an optional single-select
        attribute's CURRENT value back to blank (D4) — never a required
        attr, and never one a still-active rule would immediately refill.

        Live-checked, not a static flag: simulates removing each
        candidate from `filled` and re-runs
        apply_recommendation_rules/apply_constraint_rules against that
        trial state — if a recommendation would refire, or a constraint
        narrows the attr to exactly one remaining valid option, clearing
        is refused (the very next rule pass would just put the same value
        straight back, silently, making the "clear" a no-op at best).
        """
        if not self._CLEAR_VERB_RE.search(question):
            return None
        q_lower = question.lower()
        for attr in attrs:
            vn = attr.variable_name
            if attr.required or attr.select_type == "multi":
                continue
            if not filled.get(vn):
                continue
            if not _label_mentioned_strict(attr.display_label.lower(), q_lower):
                continue
            trial_filled = dict(filled)
            trial_filled.pop(vn, None)
            rec_fires = self.apply_recommendation_rules(
                attrs, trial_filled, rec_rules, bml_eval=bml_eval)
            if vn in rec_fires:
                continue  # a recommendation would immediately refill it
            constrained = self.apply_constraint_rules(
                attrs, con_rules, trial_filled, bml_eval=bml_eval)
            allowed = constrained.get(attr.entity_id)
            if allowed is not None:
                valid_opts = [o for o in attr.options if o.item_value in allowed]
                if len(valid_opts) == 1:
                    continue  # constraint narrows to one — would refill immediately
            return attr
        return None

    # "change/set/update/make ... quantit(y|ies) ... to <number>" OR
    # "change/set/... both/all/every ... to <number>" — a bulk per-row
    # quantity update, distinct from _CHANGE_VERB_RE's single-attribute
    # value change. Live-verified gap (2026-07-22): "change both the
    # mounting type to 25" — no "quantity" word at all, just "both" —
    # missed the original quantity-only regex and fell into
    # detect_change_request_collision instead, where 25 (never a real
    # mount option) couldn't resolve either. The "both/all/every" branch
    # is intentionally broader; detect_bulk_quantity_change's own
    # restriction to resolve_array_grid_links' selectors with actually
    # resolvable selected rows is the real safety net, not this regex.
    _BULK_QTY_RE = re.compile(
        r"\b(?:change|set|update|make)\b.{0,80}"
        r"\b(?:quantit(?:y|ies)|both|all|every)\b.{0,60}"
        r"\bto\b\s*(\d+(?:\.\d+)?)",
        re.IGNORECASE | re.DOTALL,
    )

    def detect_bulk_quantity_change(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled_multi: dict[str, list[str]],
    ) -> "tuple[str, list[str], str] | None":
        """Detect "change both/all the mounting types quantity to 67" — set
        every currently-selected grid-row's quantity to one value at once.

        Live-verified gap: this phrasing was previously misread as a
        single-attribute value change ("change Mounting Type to 67"),
        which either mis-set the grid selector's own value or, on a
        catalog with two identically-labeled "Mounting Type" attrs (one
        single-select, one the real multi-select grid), forced an
        unresolvable disambiguation prompt — 67 was never going to be a
        valid answer for either one, since the real target is each row's
        quantity attr, not the selector's own value.

        Restricting candidates to `resolve_array_grid_links`' selectors
        sidesteps that label collision entirely: a plain single-select
        sibling (e.g. mountType_viSoln) never has grid links and so is
        never a candidate here, regardless of a shared display_label.

        Returns (selector_variable_name, item_values_to_update, new_qty)
        or None. Only matches selectors with at least one already-selected,
        quantity-resolvable row — never guesses at an unfilled selector.
        """
        m = self._BULK_QTY_RE.search(question)
        if not m:
            return None
        new_qty = m.group(1)
        grid_links = self.resolve_array_grid_links(attrs)
        if not grid_links:
            return None
        by_vn = {a.variable_name: a for a in attrs}
        candidates: list[tuple[str, list[str]]] = []
        for selector_vn, item_map in grid_links.items():
            selected = filled_multi.get(selector_vn) or []
            resolvable = [iv for iv in selected if iv.strip().lower() in item_map]
            if resolvable:
                candidates.append((selector_vn, resolvable))
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0][0], candidates[0][1], new_qty
        # Multiple grid selectors are in play — narrow by word overlap
        # against each selector's own display_label rather than guess.
        q_words = set(_variable_words(question.replace("_", " ")))
        scored = []
        for selector_vn, resolvable in candidates:
            attr = by_vn.get(selector_vn)
            label_words = set(_variable_words(attr.display_label)) if attr else set()
            if q_words & label_words:
                scored.append((selector_vn, resolvable))
        if len(scored) == 1:
            return scored[0][0], scored[0][1], new_qty
        return None

    def detect_approval(self, question: str) -> bool:
        """True when the user is approving/confirming the configuration (Step 8)."""
        return bool(self._APPROVAL_RE.search(question.strip()))

    # Decline keywords — user is explicitly rejecting the awaiting-approval
    # configuration (ISSUE-002, docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_
    # PLAN_2026_08_17.md). Anchored at the start of the message exactly like
    # _APPROVAL_RE above, deliberately NOT a bare substring search — a
    # substring match on "no" would false-positive on ordinary attribute
    # answers that happen to start with a negative word (e.g. "no carry
    # solution" as a value), which this detector must never be consulted
    # for anyway (callers only invoke it in awaiting-approval-adjacent
    # dispatch), but the anchored shape keeps the regex itself conservative
    # regardless of call site.
    _DECLINE_RE = re.compile(
        r"^no+\b[\s,!.]*$|"  # bare "no"/"noo" (optionally with trailing punctuation) alone
        r"^(?:no+\b[\s,!.]*)?"
        r"(?:i\s+(?:hereby\s+|just\s+|really\s+)?)?"
        r"(nope|declin(?:e|ed|ing)|reject(?:ed|ing)?|cancel(?:led|ing)?|"
        r"don'?t\s+(?:approve|submit|confirm|finali[sz]e|send\s+it|go\s+ahead)|"
        r"do\s+not\s+(?:approve|submit|confirm|finali[sz]e|send\s+it|go\s+ahead)|"
        r"not\s+(?:yet|now|ready)|hold\s+on|wait|"
        r"that'?s?\s+(?:wrong|not\s+(?:right|correct))|go\s+back)\b",
        re.IGNORECASE,
    )

    def detect_decline(self, question: str) -> bool:
        """True when the user is explicitly rejecting the awaiting-approval
        configuration (Step 8 rejection). See ISSUE-002 fix plan for the
        production bug this closes: an explicit "no, decline that" was being
        misdispatched as an approval because no deterministic decline
        detector existed at all.
        """
        return bool(self._DECLINE_RE.search(question.strip()))

    # "give/show me the (final) summary/configuration", "recap", "what do
    # I have so far" — a request to RE-SHOW the current configuration, not
    # a question about a specific attribute and not an approval. Live-
    # verified gap, 2026-08-13: with no dedicated category for this, "give
    # the final summary now" was classified OUT_OF_SCOPE by the LLM
    # classifier (none of its fixed categories represent "show it again"),
    # and a shorter phrasing like "give the configuration" could
    # coincidentally word-match a real catalog attribute whose own label
    # contains "configuration" (e.g. "Configuration Type"), silently
    # hijacking the turn into a change-target prompt for that unrelated
    # attribute instead. Checked deterministically, ahead of both paths.
    _SHOW_SUMMARY_RE = re.compile(
        r"(?i:"
        r"\b(?:show|give|send|display)\s+(?:me\s+)?(?:the\s+)?"
        r"(?:final\s+|current\s+|full\s+)?(?:summary|configuration|config)\b"
        r"|\brecap\b"
        r"|\breview\s+(?:the\s+|my\s+)?(?:configuration|config|summary|order)\b"
        r"|\bwhat\s+(?:do\s+i\s+have|have\s+i\s+(?:chosen|selected|picked))\s+so\s+far\b"
        r"|\bwhat'?s?\s+my\s+(?:current\s+)?(?:configuration|config)\b"
        r")"
    )

    def detect_show_summary_request(self, question: str) -> bool:
        """True when the customer is asking to see the configuration
        summary again, not naming a specific attribute or approving.
        """
        return bool(self._SHOW_SUMMARY_RE.search(question.strip()))

    def detect_qa_question(
        self,
        question: str,
        pending_attr: "ConfigAttr | None" = None,
        strict: bool = False,
    ) -> bool:
        """True when the user is asking a Q&A question rather than answering a config prompt.

        strict=True — only fires on explicit `?` or Q&A intent keywords. Use during
        active configuration to avoid intercepting free-text config answers.
        strict=False (default) — also fires when a long message doesn't match any
        option for the pending attr. Use during awaiting_approval review.
        """
        q = question.strip()
        if "?" in q:
            return True
        if self._QA_INTENT_RE.search(q):
            return True
        if strict:
            return False
        # Awaiting-approval heuristic: long message that matches no visible option → Q&A
        if pending_attr and pending_attr.options and len(q.split()) > 5:
            q_lower = q.lower()
            if not any(
                o.item_value.lower() in q_lower or o.display_name.lower() in q_lower
                for o in pending_attr.options
            ):
                return True
        return False

    def detect_change_request(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]] | None = None,
    ) -> "tuple[ConfigAttr, str] | None":
        """Detect if the user wants to change an already-filled attribute (Step 6).

        Returns (attr_to_change, new_value_hint) or None if no change detected.
        Strategy: look for change-verb vocabulary first; then fall back to
        checking if the raw message maps to a different value for any filled attr.

        filled_multi — multi-select selections (variable_name → item_values).
        Without it, multi-selects were INVISIBLE to change detection (the
        loop only consulted the scalar `filled` dict), so no multi-select
        could ever be changed after completion — confirmed live: "I wanted
        to include the mounting type: Locking Molle Mount" against a
        declined (empty, user-confirmed) mount grid fell through to the
        review nudge. A key present in filled_multi counts as filled —
        including the explicitly-declined empty selection; for multi attrs
        a "different value" means the mentioned option isn't already in
        the selected rows.

        Just the first match from `_change_request_matches` — see
        `detect_change_requests_multi` for a message naming several
        attrs at once.
        """
        return next(self._change_request_matches(question, attrs, filled, filled_multi), None)

    def detect_all_change_targets_without_value(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        *,
        filled_multi: dict[str, list[str]] | None = None,
        exclude_vns: set[str] | None = None,
        cap: int = 10,
    ) -> list[ConfigAttr]:
        """All already-filled attrs named in a valueless change utterance.

        Ordered by first appearance of the label/vn in the question so
        "change hardware version, service type and activation delay"
        yields a stable FIFO for pending_intent_queue. ``exclude_vns``
        skips already-handled targets; ``cap`` bounds the scan (default
        matches INTENT_QUEUE_CAP).
        """
        if not self._CHANGE_VERB_RE.search(question or ""):
            return []
        exclude = exclude_vns or set()
        multi = filled_multi or {}
        q_flat = (question or "").lower().replace("_", " ")
        matches: list[ConfigAttr] = []
        for a in attrs:
            if a.variable_name in exclude:
                continue
            if not (filled.get(a.variable_name) or multi.get(a.variable_name)):
                continue
            label_l = (a.display_label or "").lower()
            vn_flat = a.variable_name.lower().replace("_", " ")
            # Full label, variable_name, or a trailing multi-word slice of
            # the label (e.g. "service type" matching "Primary Service Type").
            hit = False
            if label_l and label_l in q_flat:
                hit = True
            elif vn_flat and vn_flat in q_flat:
                hit = True
            else:
                words = [w for w in label_l.split() if len(w) > 1]
                for n in range(min(len(words), 3), 1, -1):
                    tail = " ".join(words[-n:])
                    if tail in q_flat:
                        hit = True
                        break
            if hit:
                matches.append(a)
        # Prefer longer labels when one subsumes another (same as singular
        # detector's max-by-len), but keep appearance order among peers.
        # First drop subsumed shorter labels that share the same span.
        def _pos(a: ConfigAttr) -> int:
            label_l = (a.display_label or "").lower()
            vn_flat = a.variable_name.lower().replace("_", " ")
            positions = [i for i in (
                q_flat.find(label_l) if label_l else -1,
                q_flat.find(vn_flat) if vn_flat else -1,
            ) if i >= 0]
            return min(positions) if positions else 9999

        # Drop attrs whose label is a strict substring of another match's
        # label at the same region (e.g. "Type" inside "Service Type") —
        # keep the longest label at each position cluster.
        matches.sort(key=lambda a: (-len(a.display_label or ""), _pos(a), a.variable_name))
        kept: list[ConfigAttr] = []
        kept_labels: list[str] = []
        for a in matches:
            lab = (a.display_label or "").lower()
            if any(lab and lab != k and lab in k for k in kept_labels):
                continue
            kept.append(a)
            kept_labels.append(lab)
        # Stable user-facing order: appearance in the utterance.
        kept.sort(key=_pos)
        return kept[: max(0, cap)]

    def detect_change_target_without_value(
        self, question: str, attrs: list[ConfigAttr], filled: dict[str, str],
    ) -> ConfigAttr | None:
        """A change-verb naming an already-filled attr, but with no
        resolvable new value ("change hardware version", "change product")
        — distinct from detect_change_request, which requires BOTH a verb
        AND a value and returns None otherwise. Confirmed live
        (docs/CPQ_MID_CONFIG_CHANGE_REQUEST_PLAN.md Related finding 1): a
        valueless change message fell through every detector, regex and
        LLM, straight to the generic "I didn't quite catch that" nudge —
        this lets the caller instead ask which value, the same way
        detect_attr_query's "what values are available" answer already
        does. Only ever called AFTER detect_change_request/
        detect_change_requests_multi have already returned nothing, so a
        message with a resolvable value never reaches here.

        Returns the first of ``detect_all_change_targets_without_value``
        (appearance order) so multi-target callers can still use the
        singular form for "active" while enqueuing the rest.
        """
        all_targets = self.detect_all_change_targets_without_value(
            question, attrs, filled,
        )
        return all_targets[0] if all_targets else None

    # Cap on detect_change_requests_multi's result — a message naming more
    # than this is unusual enough that blindly trusting every match risks
    # silently misapplying something the user didn't actually intend
    # (product decision: cap 3, apply whichever parse, report the rest).
    _MAX_MULTI_CHANGE_REQUESTS = 3

    def detect_change_requests_multi(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]] | None = None,
    ) -> list[tuple[ConfigAttr, str]]:
        """Up to `_MAX_MULTI_CHANGE_REQUESTS` (attr, new_value_hint) matches
        from a SINGLE message naming several attrs at once — e.g. "change
        the Shirt Magnetic Mount Quantity to 25 and the Jacket Magnetic
        Mount Quantity to 25". `detect_change_request` only ever returns
        the first match (`_change_request_matches` is a generator; each
        `for attr in _try_order` iteration yields independently, so
        collecting more than one is exactly this: keep scanning instead of
        stopping at the first).

        Returns [] when no match is found, mirroring the "no change
        detected" contract callers already expect from the singular form.
        """
        out: list[tuple[ConfigAttr, str]] = []
        for match in self._change_request_matches(question, attrs, filled, filled_multi):
            out.append(match)
            if len(out) >= self._MAX_MULTI_CHANGE_REQUESTS:
                break
        return out

    # Generic connector/control words a leftover clause commonly contains
    # that are never themselves part of a real catalog label — excluded so
    # e.g. "...and confirm" doesn't count "confirm" as catalog-word overlap
    # just because some unrelated attr's label happens to share it.
    _GENERIC_CLAUSE_STOPWORDS = frozenset({
        "to", "the", "a", "an", "then", "please", "also", "and", "or",
        "change", "set", "update", "make", "it", "that", "this", "for",
        "with", "of", "in", "on", "confirm", "submit", "thanks", "thank",
        "yes", "no", "ok", "okay", "done",
    })

    def detect_unmatched_change_targets(
        self,
        question: str,
        attrs: list[ConfigAttr],
        matched_vns: "set[str]",
    ) -> list[str]:
        """Live-verified gap (2026-07-28): "change solution type and
        hardware type" — where "hardware type" names nothing real in this
        catalog (it's "Hardware Version", not "Hardware Type") — silently
        dropped "hardware type" entirely once "solution type" was
        successfully matched. The customer explicitly asked for two
        things and only saw one addressed, with no indication the second
        wasn't understood — indistinguishable from the system just
        forgetting it.

        Returns plain-language leftover phrases from the message that
        (a) weren't accounted for by any attr already in `matched_vns`,
        (b) don't match ANY real attr's label either (a genuine second
        VALID target — just one this caller hasn't resolved yet — is not
        "unmatched", it's simply not this function's problem), and
        (c) share at least one content word with SOME real catalog
        label, the signal that this was a plausible-but-failed naming
        attempt rather than an unrelated trailing clause ("...and
        confirm") that happens to split on the same connective.

        Deliberately conservative: only runs when the message has an
        actual change-verb AND a connective ("and"/","/"&") joining
        multiple clauses — a single-clause message has nothing "left
        over" to flag by construction.
        """
        verb_match = self._CHANGE_VERB_RE.search(question) or self._ARROW_RE.search(question)
        if not verb_match:
            return []
        if not re.search(r"\band\b|,|&", question, re.IGNORECASE):
            return []
        catalog_words: set[str] = set()
        for a in attrs:
            catalog_words |= set(re.findall(r"[a-z0-9]+", a.display_label.lower()))
        clauses = re.split(r"\band\b|,|&", question, flags=re.IGNORECASE)
        unmatched: list[str] = []
        for clause in clauses:
            clause = clause.strip()
            if not clause:
                continue
            clause_lower = clause.lower()
            # Already accounted for by an attr this caller DID match.
            if any(
                a.variable_name in matched_vns
                and _label_mentioned_strict(a.display_label.lower(), clause_lower)
                for a in attrs
            ):
                continue
            # Names a REAL attr — just not (yet) one in matched_vns. Not
            # this function's concern; a genuine second valid target is
            # not the same failure as naming nothing at all.
            if any(_label_mentioned_strict(a.display_label.lower(), clause_lower) for a in attrs):
                continue
            stripped = self._CHANGE_VERB_RE.sub("", clause, count=1).strip()
            stripped = self._ARROW_RE.sub("", stripped, count=1).strip()
            if not stripped or len(stripped.split()) > 6:
                continue
            clause_words = (
                set(re.findall(r"[a-z0-9]+", stripped.lower()))
                - self._GENERIC_CLAUSE_STOPWORDS
            )
            if clause_words & catalog_words:
                unmatched.append(stripped)
        return unmatched

    def _change_request_matches(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]] | None = None,
    ):
        """Generator yielding every (attr, new_value_hint) match — shared by
        `detect_change_request` (first match only) and
        `detect_change_requests_multi` (up to `_MAX_MULTI_CHANGE_REQUESTS`).
        See `detect_change_request`'s docstring for the matching contract;
        this is the same body with `return` turned into `yield` + `continue`
        so the `for attr in _try_order` loop keeps scanning afterward
        instead of exiting the whole function.
        """
        q_lower = question.lower()
        has_change_verb = bool(self._CHANGE_VERB_RE.search(question)) or bool(self._ARROW_RE.search(question))
        multi = filled_multi or {}

        # Each candidate attr's own label-mention span (start, end) in the
        # lowercased message, when found — used below to scope free-text
        # numeric extraction to the text near THIS attr's own mention
        # rather than the whole message. A message naming two sibling
        # quantity attrs (confirmed live: SVX's per-mount-type quantity
        # attrs are all named "mounting type {Mount Name} Quantity", one
        # per mount option) — e.g. "change the jacket magnetic mount
        # quantity to 15 and the pouch mount quantity to 8" — would
        # otherwise have BOTH attrs' searches independently grab the SAME
        # first number in the sentence, since neither search was scoped to
        # its own attr's mention; whichever attr `attrs` iteration reached
        # first won, regardless of which number was actually meant for it
        # (catalog order, not textual order — confirmed live by reversing
        # iteration order and getting "15" for the pouch attr instead of 8).
        label_spans: dict[str, tuple[int, int]] = {}
        for _attr in attrs:
            if _attr.variable_name not in filled and _attr.variable_name not in multi:
                continue
            span = _label_mention_span(_attr.display_label.lower(), q_lower)
            if span:
                label_spans[_attr.variable_name] = span

        # A candidate whose label is a literal SUBSTRING of another matching
        # candidate's label (e.g. "Quantity" inside "mounting type Locking
        # Molle Mount Quantity") is deprioritized — tried only as a fallback
        # if no more-specific candidate produces a result. This is narrower
        # than "shorter label loses": two independent sibling labels that
        # don't subsume each other (e.g. "Jacket Magnetic Mount Quantity" vs
        # "Pouch Mount Quantity") are NOT affected, preserving the existing
        # iteration-order contract for genuine siblings — only a real
        # substring/subsumption relationship reorders anything (confirmed
        # live: "Change the mounting type Locking Molle Mount Quantity to
        # 10" matched the generic accecsssoriesQuantityArray_viSoln — label
        # "Quantity" — instead of mountingTypeLockingMolleMountQuantity_
        # viSoln, whose real label IS "mounting type Locking Molle Mount
        # Quantity" — same principle detect_attr_query's own longest-match
        # tiebreak already applies, docs/CPQ_SESSION_2_OPEN_ISSUES.md item 2).
        _candidates = [a for a in attrs if a.variable_name in filled or a.variable_name in multi]
        _superseded: set[str] = set()
        for _a in _candidates:
            _a_label = _a.display_label.lower()
            for _b in _candidates:
                if _b is _a or _b.variable_name in _superseded:
                    continue
                _b_label = _b.display_label.lower()
                if _a_label != _b_label and _a_label in _b_label:
                    _superseded.add(_a.variable_name)
                    break
        _try_order = (
            [a for a in attrs if a.variable_name not in _superseded]
            + [a for a in attrs if a.variable_name in _superseded]
        )

        # Try each filled attr — find one where the user's message implies a different value
        for attr in _try_order:
            if attr.variable_name not in filled and attr.variable_name not in multi:
                continue
            vn_flat = attr.variable_name.lower().replace("_", "")
            label_lower = attr.display_label.lower()

            # Require the attr to be mentioned by name/label REGARDLESS of
            # change-verb presence (2026-07-28 fix) — the original gate
            # only skipped an unmentioned attr when has_change_verb was
            # True, which backwards-guarded exactly the wrong case: a bare
            # reply with NO change verb (e.g. a plain "77" meant to answer
            # a totally different pending free-text quantity attr) let
            # EVERY filled attr through unfiltered, since the whole
            # condition short-circuits False when has_change_verb is
            # False. Live-verified: with no verb and no mention, "77" got
            # tried against ultimateDestinationCountry's own apply_answer,
            # which treats a bare number as a 1-based option INDEX — and
            # position 77 in that catalog's 251-country list happens to be
            # United Kingdom — silently overwriting the country and
            # cascading a dozen dependent attrs, while the customer's
            # actual answer (a quantity) was never even attempted here.
            # Naming still isn't required through the SEPARATE hint-path
            # fallback further below (extract_hints's own token-to-vn
            # match is its own, narrower signal) — this only closes the
            # "nothing at all ties this attr to the message" hole.
            #
            # A multi-select attr's own OPTION VALUE mentioned in the text
            # counts too, not just its label/variable_name — "add the
            # Jacket Clip Mount too" legitimately names the value being
            # added, never the generic "Mounting Type" label itself
            # (pre-existing, tested behavior — test_cpq_grid_decline.py).
            _multi_option_mentioned = attr.select_type == "multi" and any(
                o.display_name.lower() in q_lower for o in attr.options
            )
            if (
                vn_flat not in q_lower.replace("_", "")
                and not _label_mentioned(label_lower, q_lower)
                and not _multi_option_mentioned
            ):
                continue

            # docs/config_consistency_issues_2026-07-30.md issue 4 follow-up
            # — a multi-select the customer never touched still gets a `[]`
            # entry in filled_multi from auto_fill/hiding-rule evaluation
            # (confirmed live: nearly every multi-select in a real catalog
            # carries this, touched or not), so the gate above alone lets a
            # BARE VALUE mention — with no explicit label/variable_name
            # naming at all — match an untouched, empty multi-select purely
            # because that value happens to also be one of ITS real
            # options. Live-confirmed: with Frequency Bands (single-select)
            # correctly the sole pending attribute, a bare "VHF" reply
            # still matched an unrelated, never-touched
            # modelSelectionFrequencyBandMsl_astro this way, writing the
            # reply into the wrong attribute and leaving the real pending
            # one stale (bom_gate re-detects it as invalid every confirm,
            # looping forever). An EMPTY multi-select stays eligible when
            # explicitly named by label/variable_name (test_cpq_grid_
            # decline.py's declined-grid-reconsidered case: "I wanted to
            # include the mounting type: X" must still work) — only a
            # bare, unnamed value-only mention requires the multi-select to
            # already hold a real selection.
            if (
                attr.select_type == "multi"
                and not multi.get(attr.variable_name)
                and vn_flat not in q_lower.replace("_", "")
                and not _label_mentioned(label_lower, q_lower)
            ):
                continue

            # Direct apply_answer match — checked FIRST so the full NL question
            # (with verbatim display-name substring matching) wins over the coarse
            # hint token. Without this ordering, "4G LTE Only" collapsed to "LTE"
            # by _HINT_PATTERNS can't be distinguished from "4G LTE+5G".
            # Guard: skip option-less (free-text) attrs — apply_answer's free-text
            # fallback would accept ANY string as a spurious "value".
            if attr.options and attr.variable_name in multi:
                mentioned = self.apply_multi_answer(attr, question)
                current_rows = set(multi.get(attr.variable_name, []))
                if any(iv not in current_rows for iv, _dn in mentioned):
                    yield attr, question
                continue
            if attr.options:
                result = self.apply_answer(attr, question)
                if result and _valid(result[0]) and result[0] != filled.get(attr.variable_name):
                    yield attr, question
                    continue
            elif has_change_verb:
                # Free-text attr (e.g. a per-mount quantity field) with an
                # explicit change verb — the label-mention gate above has
                # already confirmed THIS attr is the one being talked about,
                # but unlike options-backed attrs there's no menu list to
                # fuzzy-match a value against, and extract_hints() only knows
                # fixed concepts (country/region/hwversion) — never numbers
                # (confirmed live: "change the jacket magnetic mount quantity
                # to 15" fell through to "I didn't quite catch that" even
                # after the label-mention fix above, because nothing ever
                # extracted "15" out of the sentence). Anchor to the "to/from
                # N" phrasing FIRST — this catalog's own product names embed
                # digits (V200 Body Worn Camera, APX6500, both confirmed live
                # elsewhere in this file), so "change the V200 Body Worn
                # Camera quantity to 2" would otherwise match "200" before
                # the intended "2". Only fall back to the first standalone
                # number in the sentence when no directional verb is present.
                # Scoped to the text after THIS attr's own label mention (see
                # label_spans above) and before the next sibling attr's own
                # mention, if any — never the whole message, or a second
                # quantity attr named later in the same sentence would steal
                # this one's number (or vice versa).
                own_span = label_spans.get(attr.variable_name)
                if own_span:
                    window_start = own_span[1]
                    later_starts = [
                        s for vn2, (s, _e) in label_spans.items()
                        if vn2 != attr.variable_name and s >= window_start
                    ]
                    window_end = min(later_starts) if later_starts else len(question)
                    search_text = question[window_start:window_end]
                else:
                    # This attr matched only via vn_flat (the raw variable
                    # name literally in the message), not its display label
                    # — no span to scope by, so fall back to the whole
                    # message like before (rare: natural phrasing almost
                    # never types the internal snake_case variable name).
                    search_text = question
                m = (re.search(r"\bto\s+(-?\d+(?:\.\d+)?)", search_text, re.IGNORECASE)
                     or re.search(r"(?:->|→)\s*(-?\d+(?:\.\d+)?)", search_text)
                     or re.search(r"\bfrom\s+(-?\d+(?:\.\d+)?)", search_text, re.IGNORECASE))
                value = m.group(1) if m else None
                if value is None:
                    m2 = re.search(r"-?\d+(?:\.\d+)?", search_text)
                    value = m2.group(0) if m2 else None
                if value is not None and value != filled.get(attr.variable_name, ""):
                    yield attr, value
                    continue

            # Hint-path fallback — coarse extracted token (e.g. "LTE", "4G") confirms
            # the attr is mentioned but may not identify the exact option. Only reached
            # when apply_answer found no specific match (e.g. "make it LTE" with no
            # full option name in the message). Returns full question so _handle_cascade
            # can try apply_answer again with more context.
            hints_dcr = self.extract_hints(question)
            for hk, hv in hints_dcr.items():
                hk_flat = hk.lower().replace("_", "")
                if hk_flat in vn_flat or vn_flat in hk_flat:
                    if hv.lower() != filled.get(attr.variable_name, "").lower():
                        yield attr, question
                        break

    def find_cascade_dependents(
        self,
        changed_attr: "ConfigAttr",
        all_attrs: list[ConfigAttr],
        hiding_rules: list[HidingRule],
        rec_rules: list[RecommendationRule],
        con_rules: list[ConstraintRule],
    ) -> list[int]:
        """Return entity_ids of attrs that may be invalidated when changed_attr is re-valued.

        Covers:
          - Attrs targeted by hiding/recommendation/constraint rules conditioned on changed_attr.
          - Free-text cascade siblings (attrs sharing a decision key fragment with changed_attr).
        """
        dependents: set[int] = set()
        changed_ids = {changed_attr.entity_id}
        if changed_attr.source_id is not None:
            changed_ids.add(changed_attr.source_id)
        by_rule_id = self._attr_index(all_attrs)

        def _target_eid(target_attr_id: int) -> int:
            target = by_rule_id.get(target_attr_id)
            return target.entity_id if target else target_attr_id

        for rule in hiding_rules:
            if rule.condition_attr_id in changed_ids:
                dependents.add(_target_eid(rule.target_attr_id))
        for rule in rec_rules:
            if rule.condition_attr_id in changed_ids:
                dependents.add(_target_eid(rule.target_attr_id))
        for rule in con_rules:
            if rule.condition_attr_id in changed_ids:
                dependents.add(_target_eid(rule.target_attr_id))

        # Cascade-fill siblings (free-text attrs that mirror this attr's value)
        changed_vn_flat = changed_attr.variable_name.lower().replace("_", "")
        matched_dk = next(
            (dk for dk in _DECISION_REQUIRED_KEYS if dk in changed_vn_flat), None
        )
        if matched_dk:
            for attr in all_attrs:
                if attr.entity_id == changed_attr.entity_id or attr.options:
                    continue
                if matched_dk in attr.variable_name.lower().replace("_", ""):
                    dependents.add(attr.entity_id)

        return list(dependents)

    def build_review_prompt(
        self,
        product_name: str,
        attrs: list[ConfigAttr],
        display_filled: dict[str, str],
    ) -> str:
        """Build the Step 6 review message for user approval.

        Shows decision-required attrs (the choices the user made) prominently,
        and summarises auto-configured attrs as a count so the review is scannable.
        """
        by_vn: dict[str, ConfigAttr] = {a.variable_name: a for a in attrs}
        decision_lines: list[str] = []
        auto_count = 0

        for vn, disp_val in display_filled.items():
            if self._is_html_value(disp_val):
                continue
            attr = by_vn.get(vn)
            label = attr.display_label if attr else vn
            vn_flat = vn.lower().replace("_", "")
            is_decision = any(dk in vn_flat for dk in _DECISION_REQUIRED_KEYS)
            if is_decision:
                decision_lines.append(f"- **{label}**: {disp_val}")
            else:
                auto_count += 1

        parts = [f"✅ **{product_name}** is configured. Review your choices:"]
        if decision_lines:
            parts.extend(decision_lines)
        if auto_count:
            parts.append(f"\n*{auto_count} additional attributes auto-configured from graph defaults.*")
        parts.append(
            "\nSay **confirm** to generate the BOM, or describe what you'd like to change."
        )
        return "\n".join(parts)

    # ── Attribute option query detection ─────────────────────────────────────

    _OPTIONS_KEYWORDS: frozenset[str] = frozenset({
        "values", "options", "available", "what are", "list", "choices",
        "show me", "which", "can i choose", "what can",
    })

    def detect_label_collision(
        self, question: str, attrs: list[ConfigAttr],
    ) -> list[ConfigAttr] | None:
        """Detect an options-query naming a display_label 2+ distinct attrs
        share (BigMachines source-data reuse — confirmed real, not an
        ingestion artifact; see docs/CPQ_SESSION_2_OPEN_ISSUES.md item 2).

        Only fires for the label-matching tier — a variable_name match is
        already unambiguous by construction (variable_name is unique), so
        this must run BEFORE detect_attr_query's own label fallback tier
        silently resolves the tie via `max(..., key=len)`. Returns the tied
        candidates so the caller can ask the user to disambiguate instead of
        guessing, or None when there's no collision to report.

        docs/config_consistency_issues_2026-07-30.md — live-confirmed bug: a
        genuine COLLISION (one shared label, 2+ attrs) was being conflated
        with a compound question naming several DIFFERENT, unambiguous
        attrs by their own distinct labels in one sentence ("what are the
        Frequency Bands and Wireless Carrier available?" wrongly pulled
        wirelessCarrier_astro — label "Wireless Carrier", zero shared
        tokens with "Frequency Bands" — into the SAME disambiguation
        prompt, because the old check only counted `len(distinct_vns) >= 2`
        across ALL label matches combined, never checking whether they
        actually shared ONE label. Now groups matches by their OWN exact
        label text first — only a group where 2+ DISTINCT variable_names
        share the SAME label text is a real collision. Every `_narrow_label_
        collision` caller already assumes this invariant (its own docstring:
        "every candidate here has the IDENTICAL label by construction") —
        this fix makes that actually true instead of assumed.
        """
        q_lower = question.lower()
        if not any(kw in q_lower for kw in self._OPTIONS_KEYWORDS):
            return None
        q_flat = q_lower.replace("_", "")
        vn_matches = [
            attr for attr in attrs
            if attr.variable_name.lower().replace("_", "") in q_flat
            or attr.variable_name.lower() in q_lower
        ]
        if vn_matches:
            return None
        label_matches = [attr for attr in attrs if attr.display_label.lower() in q_lower]
        by_label: dict[str, list[ConfigAttr]] = {}
        for a in label_matches:
            by_label.setdefault(a.display_label.lower(), []).append(a)
        for group in by_label.values():
            if len({a.variable_name for a in group}) >= 2:
                return group
        return None

    def detect_change_request_collision(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]] | None = None,
    ) -> list[ConfigAttr] | None:
        """Same identical-label ambiguity as detect_label_collision, but for
        change requests rather than options-queries (docs/CPQ_SESSION_2_
        OPEN_ISSUES.md item 2 — that doc claimed this closed the gap for
        "the whole conversational flow", but detect_change_request only
        ever had the separate, narrower substring-subsumption fix, which
        does nothing when two candidates' labels are IDENTICAL rather than
        one subsuming the other — confirmed: "change service type to
        Premier" against 3 identically-labeled "Service Type" attrs
        resolved silently to whichever was first in catalog order).

        detect_label_collision itself isn't reused directly — it gates on
        _OPTIONS_KEYWORDS ("what options...", never present in a change
        request) and considers every attr, not just already-filled ones.
        Here the gate is a change-verb/arrow (mirrors detect_change_
        request's own has_change_verb check) and candidates are restricted
        to attrs actually in `filled`/`filled_multi` — an unfilled attr
        can't be the target of a "change X" request in the first place.

        Returns the tied candidates (so the caller can ask which one was
        meant), or None when there's no collision to report.
        """
        if not (self._CHANGE_VERB_RE.search(question) or self._ARROW_RE.search(question)):
            return None
        q_lower = question.lower()
        multi = filled_multi or {}
        # _label_mentioned_strict (2026-07-28 fix), NOT the loose
        # _label_mentioned — live-confirmed bug: "change solution type and
        # hardware type" (neither phrase contains "service type" anywhere)
        # still reported a "Service Type" collision, because the loose
        # matcher's leading-word-drop tier let "Service Type" degrade to
        # the single generic shared word "Type", which then substring-
        # matched "type" inside BOTH "solution type" and "hardware type".
        # _label_mentioned's own docstring says this loose tier is "safe
        # only as a coarse pre-filter" specifically because its OTHER
        # caller (detect_change_request) always requires a separate real
        # value-match before resolving anything — this function has no
        # such second check; it hands loose matches straight to the user
        # as a real collision, so it needs the strict variant instead,
        # which explicitly never degrades to a single generic shared word
        # (see _label_mentioned_strict's own docstring). Multi-word
        # dropped-prefix matches (e.g. "mounting type Shirt Magnetic Mount
        # Quantity" naming just "Shirt Magnetic Mount Quantity") still work
        # under the strict variant — only the single-generic-word
        # degradation is excluded.
        candidates = [
            a for a in attrs
            if (a.variable_name in filled or a.variable_name in multi)
            and _label_mentioned_strict(a.display_label.lower(), q_lower)
        ]
        # Group by the EXACT label text, not just "2+ candidates matched at
        # all" — a substring containment match (e.g. "Quantity" inside
        # "...Locking Molle Mount Quantity to 10") can pull in candidates
        # with genuinely DIFFERENT labels, which is detect_change_request's
        # own _superseded subsumption case, not an identical-label collision.
        by_label: dict[str, list[ConfigAttr]] = {}
        for a in candidates:
            by_label.setdefault(a.display_label.lower(), []).append(a)
        all_labels = set(by_label.keys())
        for label, group in by_label.items():
            if len({a.variable_name for a in group}) < 2:
                continue
            # A more specific match already present (e.g. "mounting type
            # Shirt Magnetic Mount Quantity" contains this group's generic
            # "mounting type" as its own prefix) resolves the request on its
            # own — the generic label's collision is superseded, not real
            # (confirmed live: "change mounting type Shirt Magnetic Mount
            # Quantity to 88" false-positived a "Mounting Type" collision
            # between mountType_viSoln/mountingTypeArray_viSoln even though
            # neither was meant — same principle as detect_change_request's
            # own _superseded mechanism, just not yet applied here).
            if any(other != label and label in other for other in all_labels):
                continue
            return group
        return None

    def count_turn_intents(
        self,
        question: str,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        filled_multi: dict[str, list[str]] | None = None,
    ) -> list[str]:
        """Read-only diagnostic (docs/CPQ_LLM_INTENT_FIRST_PLAN.md Fix 4,
        incremental step): runs every existing intent detector against one
        message and returns a plain-string label for each one that fired,
        WITHOUT changing what the turn actually does with the result —
        purely observational, logged by the caller.

        Confirmed live this session: "change solution type and primary
        service type" only ever got ONE of its two targets addressed,
        because `detect_change_request_collision` (and every other
        detector in the real turn-processing flow) stops at its own first
        match and the caller returns immediately. This counts how many
        DISTINCT intents a single message actually contains, so that gap
        can be measured against real traffic before any routing behavior
        changes — reuses every detector as-is, adds no new detection
        logic, and never influences the response.
        """
        hits: list[str] = []
        try:
            if self.detect_qa_question(question, None, strict=True):
                hits.append("qa_question")
        except Exception:  # noqa: BLE001 — diagnostic only, must never break the turn
            logger.debug("count_turn_intents: detect_qa_question failed", exc_info=True)
        try:
            mode = self.detect_response_mode_request(question)
            if mode:
                hits.append(f"mode_request:{mode}")
        except Exception:  # noqa: BLE001
            logger.debug("count_turn_intents: detect_response_mode_request failed", exc_info=True)
        try:
            collision = self.detect_change_request_collision(question, attrs, filled, filled_multi)
            if collision:
                hits.append(f"change_collision:{collision[0].display_label}")
        except Exception:  # noqa: BLE001
            logger.debug("count_turn_intents: detect_change_request_collision failed", exc_info=True)
        try:
            multi = self.detect_change_requests_multi(question, attrs, filled, filled_multi)
            for attr, _hint in multi:
                hits.append(f"change:{attr.variable_name}")
        except Exception:  # noqa: BLE001
            logger.debug("count_turn_intents: detect_change_requests_multi failed", exc_info=True)
        if not any(h.startswith("change:") for h in hits):
            try:
                single = self.detect_change_request(question, attrs, filled, filled_multi)
                if single:
                    hits.append(f"change:{single[0].variable_name}")
            except Exception:  # noqa: BLE001
                logger.debug("count_turn_intents: detect_change_request failed", exc_info=True)
        try:
            no_value = self.detect_change_target_without_value(question, attrs, filled)
            if no_value:
                hits.append(f"change_no_value:{no_value.variable_name}")
        except Exception:  # noqa: BLE001
            logger.debug("count_turn_intents: detect_change_target_without_value failed", exc_info=True)
        try:
            attr_q = self.detect_attr_query(question, attrs)
            if attr_q:
                hits.append(f"attr_query:{attr_q.variable_name}")
        except Exception:  # noqa: BLE001
            logger.debug("count_turn_intents: detect_attr_query failed", exc_info=True)
        return hits

    def detect_attr_query(
        self, question: str, attrs: list[ConfigAttr],
    ) -> ConfigAttr | None:
        """If the question asks about options for a specific attribute, return it.

        Detection: question contains an attribute's variable_name AND any
        option-query keyword. Reads options from already-loaded attrs — no DB
        call, no hardcoding.

        When more than one attr matches (e.g. "Hardware" and "Hardware
        Version" both appear in the same attribute list — confirmed live
        once two catalogs share a workspace), the LONGEST/most specific
        match wins rather than whichever happens to come first in list
        order, so a shorter, coincidentally-matching label can't shadow the
        attribute the user actually meant.

        Word-overlap fallback: BigMachines attributes are frequently exported
        with a near-useless leaf display_label (e.g. "Type") while the actual
        UI grouping the customer names ("Carry Solutions") only lives inside
        the variable_name itself ("carrySolutionsType_apcr"). When neither the
        exact-substring nor display_label check matches, fall back to scoring
        attrs by how many of their significant camelCase-split variable_name
        words appear in the question — requires at least 2 matching words (a
        single generic word must never hijack an unrelated question) and
        picks the attr with the most matched words.
        """
        q_lower = question.lower()
        has_options_keyword = any(kw in q_lower for kw in self._OPTIONS_KEYWORDS)
        if not has_options_keyword:
            return None
        q_flat = q_lower.replace("_", "")
        # Match by variable_name (case-insensitive, underscore-tolerant)
        vn_matches = [
            attr for attr in attrs
            if attr.variable_name.lower().replace("_", "") in q_flat
            or attr.variable_name.lower() in q_lower
        ]
        if vn_matches:
            return max(vn_matches, key=lambda a: len(a.variable_name))
        # Fallback: match by display_label
        label_matches = [attr for attr in attrs if attr.display_label.lower() in q_lower]
        if label_matches:
            return max(label_matches, key=lambda a: len(a.display_label))
        # Fallback: word-overlap against the camelCase-split variable_name.
        # Trailing tokens shared by many attrs in this list (e.g. "_apcr",
        # "_astro") are catalog/product-line codes, not customer-facing
        # words — computed here from the actual attrs rather than
        # hardcoded, so a future catalog's own suffix convention is picked
        # up automatically instead of needing a new hardcoded name.
        suffix_counts: dict[str, int] = {}
        for a in attrs:
            _, _, tail = a.variable_name.rpartition("_")
            if tail and tail.isalpha() and tail.islower() and len(tail) <= 8:
                suffix_counts[tail] = suffix_counts.get(tail, 0) + 1
        catalog_suffixes = {s for s, c in suffix_counts.items() if c >= 5}

        q_words = set(q_lower.replace("_", " ").split())
        best_attr: ConfigAttr | None = None
        best_score = 1  # require > 1 matched word
        for attr in attrs:
            vn = attr.variable_name
            base, _, tail = vn.rpartition("_")
            if base and tail in catalog_suffixes:
                vn = base
            words = _variable_words(vn)
            if len(words) < 2:
                continue
            score = sum(1 for w in words if w in q_words)
            if score == len(words) and score > best_score:
                best_score = score
                best_attr = attr
        return best_attr

    # Recognizes the recurring `allowedChars = "..."` character-allowlist
    # idiom in ValidationRule condition_scripts (confirmed live in both the
    # CC Aware 2026 and CC Aware "Allow only specific characters on PD
    # AGDOMAIN" rules) — the only script shape this describes; anything else
    # returns None rather than guessing at a description.
    _ALLOWED_CHARS_RE = re.compile(r'allowedChars\s*=\s*"([^"]*)"')

    @classmethod
    def _describe_char_allowlist(cls, script: str | None) -> str | None:
        # Raven review, 2026-07-28: this previously did a blind first-match
        # search with no guard against conditional branching or
        # reassignment — the established sibling pattern for exactly this
        # ambiguity class is bml.py's evaluate_constant_return, which bails
        # to None on any `if (` in the script and walks multiple
        # assignments in source order so the LAST one wins (never describes
        # a stale/conditionally-overridden value as if it were the real
        # constraint). Matched here for the same reason.
        if not script:
            return None
        if re.search(r'\bif\s*\(', script, re.IGNORECASE):
            return None
        matches = list(cls._ALLOWED_CHARS_RE.finditer(script))
        if not matches:
            return None
        chars = matches[-1].group(1)
        if not chars:
            return None
        has_upper = any(c.isupper() for c in chars)
        has_lower = any(c.islower() for c in chars)
        has_digit = any(c.isdigit() for c in chars)
        specials = sorted({c for c in chars if not c.isalnum()})
        parts: list[str] = []
        if has_upper and has_lower:
            parts.append("letters")
        elif has_upper:
            parts.append("uppercase letters")
        elif has_lower:
            parts.append("lowercase letters")
        if has_digit:
            parts.append("digits")
        if specials:
            parts.append("the characters " + " ".join(specials))
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + ", and " + parts[-1]

    def describe_free_text_constraint(
        self, attr: ConfigAttr, validation_rules: list["ValidationRule"] | None,
    ) -> str | None:
        """Plain-language description of a no-option attr's real constraint,
        for a Q&A "what values are allowed" question the attr has no
        options to answer with (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md
        Amendment 20 follow-up — confirmed live: agencyDomainName_ID_swSoln
        is free text with zero options, so the existing options-listing
        fast path has nothing to show, and its own ValidationRule's
        human-authored `message` ("Invalid selection") isn't descriptive
        either). Only describes the one script idiom confirmed above;
        returns None (never guesses) for any other rule shape.
        """
        target_ids = {attr.entity_id, attr.source_id}
        for rule in validation_rules or []:
            if rule.target_attr_id not in target_ids:
                continue
            desc = self._describe_char_allowlist(rule.condition_script)
            if desc:
                return desc
        return None

    def should_ask_free_text_attr(
        self,
        attr: ConfigAttr,
        validation_rules: list["ValidationRule"] | None,
        bml_eval: "BmlEvaluator | None",
    ) -> bool:
        """Generic (not catalog-specific) replacement for Amendment 19's
        reverted blanket "has a ValidationRule -> ask" heuristic (Amendment
        20, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md). Every deterministic
        signal available in this data (required flag, default_value, script
        shape, hiding-rule visibility) was confirmed identical between a
        genuine case and Amendment 20's false-positive case — so this
        escalates to a Tier-2 LLM judgment (Amendment 22), same discipline
        as every other "no cheaper signal exists" case in this codebase.
        Returns False (never asks) when there's no governing ValidationRule
        at all, or when bml_eval wasn't supplied — same opt-out convention
        every other bml_eval=None caller already gets elsewhere.
        """
        if bml_eval is None:
            return False
        target_ids = {attr.entity_id, attr.source_id}
        rule = next(
            (r for r in (validation_rules or []) if r.target_attr_id in target_ids),
            None,
        )
        if rule is None:
            return False
        return bml_eval.classify_ask_worthy(
            attr.display_label, rule.message, rule.condition_script, attr.entity_id,
        )

    # ── Announcement label disambiguation ──────────────────────────────────────

    @staticmethod
    def disambiguated_label(attr: ConfigAttr, attrs: list[ConfigAttr]) -> str:
        """`attr.display_label`, suffixed to stay unique when 2+ attrs in
        `attrs` share the same raw catalog label.

        Live-confirmed gap (2026-07-28): `serviceType_astro`,
        `serviceTypeRSM_astro`, and `serviceTypeAdditionalDMSCoverage_astro`
        all carry the literal display_label "Service Type" — when a cascade
        turn changes more than one of them (the user's own change plus an
        independently-firing recommendation rule), the customer sees
        multiple identical "Updated **Service Type** → ..." lines that read
        as duplicates/contradictions instead of distinct facts. This is the
        same root cause `_label_collision_for` already disambiguates at
        QUESTION time — this is the ANNOUNCEMENT-time equivalent.

        No catalog field carries a friendly, human grouping name for an
        attr (checked live: the raw ingested JSON has only structural/UI
        codes — "category": "2", not a label) — so the fallback is the
        attr's own variable_name, camelCase/acronym-split into words, with
        the words already present in the shared label removed. E.g.
        "serviceTypeRSM_astro" vs. shared label "Service Type" -> "RSM";
        "serviceTypeAdditionalDMSCoverage_astro" -> "Additional DMS
        Coverage". The catalog suffix (e.g. "_astro") is stripped first —
        it's shared by every attr, never a distinguishing fact. Returns the
        bare label unchanged when a sibling's variable_name has no fragment
        left to distinguish it (e.g. the "plainest" one, whose variable_name
        collapses to the label itself) rather than surface a raw,
        customer-meaningless variable_name.
        """
        label = attr.display_label
        siblings = [a for a in attrs if a.display_label == label]
        if len(siblings) < 2:
            return label
        label_words = {w.lower() for w in re.split(r"[^A-Za-z0-9]+", label) if w}
        # `attr.catalog_prefix` is a different, BM-type-level field (e.g.
        # "ApxNextConfig") — NOT the "_astro"-style suffix variable_names
        # actually carry, so it can't be used to strip that suffix (live-
        # verified: checking it left "astro" un-stripped, leaking as a
        # meaningless "Service Type (astro)"). Instead, derive it: any
        # underscore-part shared by EVERY sibling's variable_name is by
        # definition not a distinguishing fact for one of them — exclude
        # those words the same way label_words are excluded.
        _sibling_parts = [
            {p.lower() for p in s.variable_name.split("_") if p} for s in siblings
        ]
        _shared_parts = set.intersection(*_sibling_parts) if _sibling_parts else set()
        _excluded = label_words | _shared_parts
        for part in attr.variable_name.split("_"):
            if not part or part.lower() in _shared_parts:
                continue
            spaced = _CAMEL_BOUNDARY_RE.sub(r"\1 \2", part)
            spaced = _ACRONYM_BOUNDARY_RE.sub(r"\1 \2", spaced)
            words = [w for w in spaced.split() if w.lower() not in _excluded]
            if words:
                return f"{label} ({' '.join(words)})"
        # No distinguishing fragment left after stripping shared label
        # words and the catalog suffix (this attr's variable_name IS the
        # label, e.g. the plainest sibling among several sharing it) —
        # better to leave it as the bare label than surface a raw,
        # customer-meaningless variable_name fragment.
        return label

    # ── Next question ─────────────────────────────────────────────────────────

    def next_question_prompt(
        self,
        attr: ConfigAttr,
        context_sentence: str = "",
        constrained_item_values: list[str] | None = None,
        validation_rules: list["ValidationRule"] | None = None,
    ) -> str:
        """Build the hybrid question shown to the sales rep for one pending attr.

        context_sentence — explains WHY this attr is being asked based on rules
          (e.g. "Since 5G was selected, we now need a compatible antenna.").
        constrained_item_values — when active constraint rules apply, only these
          item_values are presented in the numbered list.
        validation_rules — when given, a free-text attr (no options) proactively
          shows its format constraint up front (e.g. "must only contain letters,
          digits, and the characters - . _") instead of a bare "Please provide a
          value." — confirmed live a rep has no way to know the expected format
          otherwise, since BigMachines' own source data has no help-text field
          for these attrs at all (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md
          Amendment 21's describe_free_text_constraint, previously only reachable
          reactively via a Q&A question — now shown proactively too). None when
          not supplied (default), same opt-out convention as bml_eval=None
          elsewhere — never guesses a constraint that can't be described.
        """
        # Use _presentable (not _valid) so codes like "NA" (North America) appear
        # in the numbered list even though _valid("NA")=False prevents auto-fill.
        effective_opts = [
            o for o in attr.options
            if _presentable(o.item_value)
            and (constrained_item_values is None or o.item_value in constrained_item_values)
        ]
        ctx_prefix = f"{context_sentence}\n\n" if context_sentence else ""
        if effective_opts:
            if len(effective_opts) > _MAX_ENUMERATED_OPTIONS:
                # An unconstrained master list (confirmed live: the product
                # selector carries the full ~325-model portfolio in every
                # catalog, and the country attr ~250 entries) is unusable as
                # a numbered menu — ask for the exact name instead of
                # dumping it. Threshold-based and generic: applies to ANY
                # oversized attr, no attribute-specific hardcoding. The
                # typed reply flows through apply_answer's existing
                # exact/display/word-boundary matching unchanged, and the
                # explicit "what are the options for X" Q&A path still
                # enumerates in full for clients who really want the list.
                # "Please provide" (not "type") — the batched-mode e2e test
                # counts question blocks by the "choose one"/"Please provide"
                # phrases, and this prompt must stay countable as one block.
                examples = ", ".join(f"*{o.display_name}*" for o in effective_opts[:3])
                return (
                    f"{ctx_prefix}**{attr.display_label}** has "
                    f"{len(effective_opts)} available options — too many to "
                    f"list here. Please provide the exact name "
                    f"(e.g. {examples}), or ask *\"what are the options for "
                    f"{attr.display_label}\"* to see the full list."
                )
            numbered = "\n".join(
                f"{i + 1}. {opt.display_name}"
                for i, opt in enumerate(effective_opts)
            )
            # An optional multi-select reaching this prompt at all is, by
            # construction, a grid selector (resolve_array_grid_links) —
            # every OTHER optional multi-select is auto-filled empty
            # without ever being asked (auto_fill's own optional-tier
            # branch). ask_api.py already recognizes "skip"/"none"/"no...
            # needed" as a valid decline for exactly this case (confirmed
            # live: mountingTypeArray_viSoln correctly resolves to an
            # empty selection), but the prompt never told the user that —
            # confirmed live: nobody would think to type "skip" without
            # being told it's an option.
            skip_hint = (
                "\n\n*(Optional — say \"skip\" or \"none needed\" if you "
                "don't need any.)*"
                if attr.select_type == "multi" and not attr.required else ""
            )
            return f"{ctx_prefix}**{attr.display_label}** — choose one:\n\n{numbered}{skip_hint}"
        constraint_desc = self.describe_free_text_constraint(attr, validation_rules)
        constraint_hint = (
            f"\n\n*Must only contain {constraint_desc}.*" if constraint_desc else ""
        )
        return f"{ctx_prefix}**{attr.display_label}**\n\nPlease provide a value.{constraint_hint}"

    def apply_answer(
        self,
        attr: ConfigAttr,
        user_answer: str,
        constrained_item_values: list[str] | None = None,
    ) -> tuple[str, str] | None:
        """Match the user's natural-language answer to a valid option.

        constrained_item_values — when active constraint rules apply (same
        set passed to `next_question_prompt`), only these item_values may
        match — an answer for an option outside the currently-allowed set
        is rejected rather than silently accepted (Phase I).

        Returns (item_value, display_name) or None if no match found.
        """
        ua = user_answer.strip().lower()
        allowed = set(constrained_item_values) if constrained_item_values is not None else None
        options = (
            [o for o in attr.options if o.item_value in allowed]
            if allowed is not None else attr.options
        )

        # Numeric selection: user typed "1", "2", etc. → pick by position in the
        # presented option list (only _presentable options, matching next_question_prompt).
        if ua.isdigit():
            presentable = [o for o in options if _presentable(o.item_value)]
            idx = int(ua) - 1
            if 0 <= idx < len(presentable) and _valid(presentable[idx].item_value):
                return presentable[idx].item_value, presentable[idx].display_name

        # Exact item_value match
        for opt in options:
            if opt.item_value.lower() == ua:
                return opt.item_value, opt.display_name

        # Exact display-name match
        for opt in options:
            if opt.display_name.lower() == ua:
                if _valid(opt.item_value):
                    return opt.item_value, opt.display_name

        # User answer contained in option's display name (user typed a prefix)
        for opt in options:
            if ua in opt.display_name.lower():
                if _valid(opt.item_value):
                    return opt.item_value, opt.display_name

        # Option display name found in user answer with word boundaries on both sides.
        # Uses (?<!\w)…(?!\w) rather than \b because standard \b fails at the end
        # of names like "APX NEXT (4G LTE Only)" where the trailing ")" is a
        # non-word char with no \b transition. Sorted longest-first so
        # "APX NEXT (4G LTE Only)" wins over "APX NEXT" when both could match.
        # The right-side (?!\w) also blocks short codes like "AP" from matching
        # inside "APX" — "ap" followed by "x" fails (?!\w).
        for opt in sorted(options, key=lambda o: len(o.display_name), reverse=True):
            dn = opt.display_name.lower()
            if re.search(r"(?<!\w)" + re.escape(dn) + r"(?!\w)", ua):
                if _valid(opt.item_value):
                    return opt.item_value, opt.display_name

        # Option display name found as a whole WORD in user answer — word-boundary
        # prevents "me" (Middle East code) from matching in "north a*me*rica".
        for opt in options:
            dn_lower = opt.display_name.lower()
            if re.search(r"\b" + re.escape(dn_lower) + r"\b", ua):
                if _valid(opt.item_value):
                    return opt.item_value, opt.display_name

        # Country alias fallback — a direct reply naming a country by a
        # DIFFERENT alias than the option's own item_value/display_name
        # (e.g. "USA" replying to an attr whose real option is
        # item_value="US", display_name="United States") previously fell
        # through every check above to a hard miss with no logging at all
        # (confirmed live 2026-08-14: Ultimate Destination Country accepted
        # "US" via the exact item_value check above but rejected "USA").
        # Uses _country_alias_group -- the same 249-real-country,
        # bidirectional alias table auto_fill's hint-priority path uses
        # (Priority 4 above) -- so a fix to the underlying data closes the
        # gap in both places at once. Narrow and safe — only fires when
        # `ua` (the whole trimmed reply) exactly equals a known alias,
        # never a substring/fuzzy guess.
        alias_group = _country_alias_group(ua)
        if alias_group:
            for opt in options:
                if (opt.item_value.lower() in alias_group
                        or opt.display_name.lower() in alias_group):
                    if _valid(opt.item_value):
                        logger.info(
                            "cpq_apply_answer_alias_match attr=%s reply=%r "
                            "resolved_to=%r",
                            attr.variable_name, user_answer, opt.item_value,
                        )
                        return opt.item_value, opt.display_name

        # Free-text field
        if not attr.options and allowed is None and _valid(user_answer):
            return user_answer.strip(), user_answer.strip()

        return None

    def apply_multi_answer(
        self,
        attr: ConfigAttr,
        user_answer: str,
        constrained_item_values: list[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Match ALL option names mentioned in a multi-select answer.

        apply_answer() deliberately returns only the single best match — the
        right behavior for a single-select question. A multi-select answer
        like "Shirt Magnetic Mount, Jacket Magnetic Mount, ..." names several
        options at once; using apply_answer() alone silently keeps only one
        (confirmed live: naming all 6 real mounting-type options in one
        answer captured just 1). This scans for every option whose display
        name appears in the answer, consuming matched text so a shorter
        option name already covered by a longer one isn't double-counted
        (e.g. "TEK-LOK Belt Mount" vs "Belt Mount").

        Returns a list of (item_value, display_name) pairs, in the order
        their names appear in the answer text — empty if none matched.
        """
        allowed = set(constrained_item_values) if constrained_item_values is not None else None
        options = (
            [o for o in attr.options if o.item_value in allowed]
            if allowed is not None else attr.options
        )
        ua = user_answer.lower()
        remaining = ua
        matches: list[tuple[int, str, str]] = []  # (position, item_value, display_name)
        for opt in sorted(options, key=lambda o: len(o.display_name), reverse=True):
            if not _valid(opt.item_value):
                continue
            dn = opt.display_name.lower()
            if not dn:
                continue
            pattern = re.compile(r"(?<!\w)" + re.escape(dn) + r"(?!\w)")
            m = pattern.search(remaining)
            if m:
                matches.append((m.start(), opt.item_value, opt.display_name))
                # Blank out the matched span so a shorter, overlapping option
                # name (already covered by this longer match) can't also match.
                remaining = remaining[:m.start()] + " " * (m.end() - m.start()) + remaining[m.end():]
        matches.sort(key=lambda t: t[0])
        return [(iv, dn) for _pos, iv, dn in matches]

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
        """Assemble a correct BOM payload OUTSIDE a live conversational
        turn, with the SAME defaulting and ordering guarantees a live turn
        gets — the structural fix for docs/APX_Next_RootCause_And_Fix_
        Report Issue 1 ("no path sets a rule-driven attr when a payload is
        assembled directly") and Issue 2 (payload key ordering).

        A live conversational turn (ask_api.py's per-turn handler) already
        calls evaluate_rules_loop (hide -> recommend -> constrain -> auto-
        fill until stable) before build_payload — that loop is what
        actually populates rule-driven attrs like a recommendation-rule
        target. A payload assembled directly by a script has historically
        skipped straight to something payload-shaped without ever running
        it, silently missing every attr only that loop can fill. This
        method runs the identical loop (empty `hints={}` is a valid,
        supported input — hints normally come from conversational text via
        extract_flag_hints/extract_catalog_hints, but evaluate_rules_loop
        itself has no dependency on conversation state) then calls
        build_payload with `rules` populated for dependency-aware ordering,
        so both issues are fixed by one call for any standalone caller.

        Returns (payload, unresolved). `unresolved` is
        find_unresolvable_context_attrs' output: every attr still missing
        that NO rule could ever fill (the genuine customerType-class gap —
        never guessed, always surfaced instead of silently omitted). An
        empty `unresolved` list does not guarantee the payload is complete
        against every catalog requirement — only that nothing MORE could
        have been resolved automatically without guessing.

        Catalog-agnostic: attrs/rules/scripts are all loaded fresh from
        `reader`/`workspace_id` via the same generic loaders every other
        catalog-facing method here uses — no attribute or rule name is
        hardcoded, and this works identically for any ingested BM export.
        """
        attrs, resolved_product_name = self.load_product_config(
            reader, workspace_id, product_hint)
        catalog_prefix = attrs[0].catalog_prefix if attrs else ""
        hiding_rules = self.load_hiding_rules(workspace_id, catalog_prefix)
        rec_rules, con_rules = self.load_recommendation_and_constraint_rules(
            workspace_id, catalog_prefix)
        bml_eval = self.build_bml_evaluator(workspace_id, catalog_prefix)

        working_filled = dict(filled)
        working_multi = dict(filled_multi or {})
        visible_attrs, working_filled, _display_filled, _constrained_opts = self.evaluate_rules_loop(
            attrs, hints or {}, working_filled, hiding_rules, rec_rules, con_rules,
            bml_eval=bml_eval, filled_multi=working_multi, country=country,
        )

        payload = self.build_payload(
            working_filled, None, working_multi, visible_attrs,
            rules=[*hiding_rules, *rec_rules, *con_rules],
        )
        unresolved = self.find_unresolvable_context_attrs(
            visible_attrs, working_filled, workspace_id, catalog_prefix,
            rec_rules, con_rules,
        )
        return payload, unresolved

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
    ) -> dict[str, Any]:
        """Return the final CPQ BOM API payload as ``{"configData": {...}}``.

        product_quantity — the session-level order quantity, added as a
        top-level ``"quantity"`` key SIBLING to ``configData`` (never
        inside it — that dict is a mirror of real catalog variable_names
        only, never a synthetic key). Live-verified gap, 2026-08-13: the
        overall order quantity reached the human-readable text summary
        but never the actual submitted JSON payload at all. Strictly
        opt-in — omitted entirely (not even a null key) when not
        supplied, so this can never change the payload shape for any
        existing caller that doesn't pass it.

        display_order — optional {variable_name: rank} from
        `load_layout_display_order` (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_
        PLAN.md §2). When supplied, applied as a FINAL filter+resort after
        every other rule below — restricts the payload to exactly the
        attrs present in the map (the catalog's real native-UI visible
        set) and orders them by rank, winning over the dependency-topo-
        sort/order_number tie-break described for `rules` below (every
        attr that survives this filter is, by construction, a real layout
        member with a real rank). `None` (the default) keeps today's
        behavior — every other exclusion/ordering rule below unchanged.

        Root key is ``configData`` per the actual integration contract —
        previously ``configAttributes``, an internal assumption never
        matched by the consumer.

        hidden_vns — variable_names an active hiding rule currently matches
        (from ``apply_hiding_rules``' third return value, computed by the
        caller against the exact same ``filled``/rules this turn already
        loaded). When set, these are excluded from the payload even if
        present in ``filled`` — this is the auto-fix side of the hiding-type
        rule-consistency check (docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md
        §4.1): a hidden attr's value was never a real customer decision, so
        dropping it is a certain, safe correction rather than a guess. This
        is DIFFERENT from constraint/recommendation-type inconsistencies,
        which are surfaced to the user instead of silently auto-fixed (same
        doc, §4.1) — hiding is the one case the engine can be certain about.

        Excludes HTML template values (layout/display fields, not real
        configuration inputs) and underscore-prefixed / integration-noise
        variables (``_is_noise_var`` — session/system fields like
        ``_BM_USER_CURRENCY`` or ``CRM_BILL_COUNTRY``, not real BOM
        selections). A value confirmed by the user against a real menu
        option is valid BY DEFINITION: none-like codes (``NA``, ``0``, ...)
        survive when their provenance is a confirmed source; only
        unconfirmed auto-fills are dropped.

        filled_multi (select_type=="multi" attrs) merges in — see per-type
        shape below. CpqSession.filled stays str-only
        (CPQ_CASCADE_CONVERSATION_PLAN.md §4).

        attrs — optional; when supplied, per-type serialization matches the
        REAL CPQ BOM API contract (confirmed against the documented payload
        spec, docs/CPQ_RULE_TOOL_FLOW_PLAN.md §15b/16 — every shape below
        was checked against a real example, not assumed):
          - hide_in_trans=1 attrs (e.g. productInformationText_astro) are
            excluded entirely — the real API rejected both with "cannot be
            modified" when included.
          - boolean            -> bare ``true``/``false`` (no wrapper at
            all — the real API rejected ``{"value": true}`` too, only a
            bare boolean is accepted).
          - currency           -> ``{"value": <float>, "currency": <code>}``
            (code sourced from ``_BM_USER_CURRENCY`` in ``filled`` when
            present, else "USD" — no other currency signal exists in this
            catalog's own data).
          - integer / float    -> bare numeric value.
          - date               -> bare string value (already in the
            source's own date format; no reformatting attempted).
          - single-select menu (attr has real options) -> ``{"value":..,
            "displayValue":..}`` — previously missing ``displayValue``
            entirely.
          - multi-select menu  -> ``{"items": [{"value":..,
            "displayValue":..}, ...]}`` — previously a bare list of value
            strings (``{"value": [...]}``), a materially different shape
            than the API documents and a SEPARATE bug from the
            filled-vs-filled_multi routing issue fixed earlier.
          - plain text / no matching ConfigAttr found -> bare string.
        Omitting attrs preserves the EXACT prior behavior (every value
        wrapped as ``{"value": v}``) for existing callers that don't pass
        it — the per-type behavior above only applies when a ConfigAttr for
        that variable_name is actually available.

        rules — optional combined iterable of HidingRule/ConstraintRule/
        RecommendationRule (any mix; each only needs condition_attr_id,
        target_attr_id, and optionally conditions). When supplied, the
        final key order is a dependency-aware topological sort — an attr
        gated by another (e.g. Product's allowed values restricted by
        Hardware Version, per a real declarative constraint rule) is
        placed AFTER the attr that gates it, never before. bm_config_attr's
        own order_number (ConfigAttr.order, used below when rules is
        omitted) reflects catalog UI/display layout only — confirmed live
        it can directly contradict a rule-proven dependency (a target
        ranked far ahead of its own gating condition) — so it is used here
        only as the tie-break between attrs with no dependency relation to
        each other, not as the primary signal. Only DECLARATIVE conditions
        (conditions/condition_attr_id) contribute edges; script-backed
        rules (script/condition_script set, condition_attr_id==0) have no
        single extractable condition attr and fall back to the
        order_number tie-break for that edge, same as an attr with no
        rule-derived ordering constraint at all — never guessed. A cycle
        (rule data conflict) never drops or crashes on a key: anything left
        after the topological pass is appended, sorted by order_number,
        same fallback as no-`rules`-supplied behavior. Catalog-agnostic —
        no attribute or rule name is hardcoded; works for any ingested BM
        export.
        """
        sources = filled_source or {}
        attr_by_vn = {a.variable_name: a for a in (attrs or [])}
        out: dict[str, Any] = {}
        hidden = hidden_vns or set()

        # is_array_control_attr=1 attrs (e.g. mountingArrayControl_viSoln)
        # ARE expected in the real payload — confirmed live against a
        # genuine reference payload (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 3
        # revision) as a BARE int equal to the array-set's row count, not
        # excluded as previously assumed. There is still no ingested link
        # from a control attr to its own selector attr (that requires the
        # bm_config_attr_set ingestion scoped in
        # docs/CPQ_ARRAY_SET_PAYLOAD_PLAN.md) — deriving the count by
        # NAME-matching control<->selector would be exactly the guessing
        # resolve_array_grid_links's own docstring already refuses to do for
        # this catalog family. So this only derives a count when the link is
        # STRUCTURALLY unambiguous: exactly one is_array_control attr and
        # exactly one select_type=="multi" attr among the attrs this turn
        # loaded — the count is that multi-select's number of selected
        # values. Any other shape (0 or 2+ of either) abstains rather than
        # guess, same "match or bail" discipline used everywhere else.
        array_control_count: int | None = None
        if attrs:
            control_attrs = [a for a in attrs if a.is_array_control]
            multi_attrs = [a for a in attrs if a.select_type == "multi"]
            if len(control_attrs) == 1 and len(multi_attrs) == 1:
                selector_vn = multi_attrs[0].variable_name
                selected = (filled_multi or {}).get(selector_vn) or []
                array_control_count = len(selected)

        # Real per-option quantity attrs feeding an array-set's own qty
        # member column (docs/CPQ_ARRAY_SET_PAYLOAD_PLAN.md, quantity-
        # nesting gap): mountingTypeArrayqty_viSoln-style array-set qty
        # members are NEVER themselves populated by the real conversation
        # flow — resolve_pending_grid_quantities fills the per-option NAMED
        # attrs instead (e.g. mountingTypeLockingMolleMountQuantity_viSoln,
        # confirmed live against real workspace-19 sessions). Computed once,
        # before either serialization loop below, so both the flat scalar
        # loop (which must SKIP these, not ship them standalone) and the
        # array-set grouping pass (which folds their value into the row
        # under the qty member's own key name) agree on the same mapping.
        grid_links = self.resolve_array_grid_links(attrs or [])
        array_set_qty_source: dict[str, str] = {}  # per-option qty vn -> owning qty-member vn
        consumed_by_array_set: set[str] = set()
        if attrs:
            _by_set: dict[int, list[ConfigAttr]] = {}
            for a in attrs:
                if a.array_set_id is not None and a.array_set_role == "member":
                    _by_set.setdefault(a.array_set_id, []).append(a)
            for _members in _by_set.values():
                _selector = next((a for a in _members if a.options), None)
                _qty_member = next((a for a in _members if not a.options), None)
                if not _selector or not _qty_member:
                    continue
                for _qty_vn in grid_links.get(_selector.variable_name, {}).values():
                    array_set_qty_source[_qty_vn] = _qty_member.variable_name
                    consumed_by_array_set.add(_qty_vn)

        if hidden:
            dropped = [k for k in filled if k in hidden and filled[k]]
            if dropped:
                logger.info(
                    "cpq: build_payload auto-fix — dropping %s (active hiding rule matches, "
                    "rule-consistency check — docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §4.1)",
                    dropped,
                )

        def _display_for(attr: "ConfigAttr", value: str) -> str:
            return next(
                (o.display_name for o in attr.options if o.item_value == value),
                value,
            )

        for k, v in filled.items():
            if k in hidden:
                continue
            if not v or self._is_html_value(v) or self._is_noise_var(k):
                continue
            if k in consumed_by_array_set:
                # Folded into its array-set row under the qty member's own
                # key name instead (see array_set_qty_source above) — must
                # not ALSO ship as a separate flat top-level key.
                continue
            attr = attr_by_vn.get(k)
            if attr is not None and attr.hide_in_trans:
                continue
            if attr is not None and attr.is_array_control:
                # Bare int = row count when unambiguous (see derivation
                # above); otherwise abstain rather than ship the
                # disconnected, coincidental raw value that caused the
                # original 5-vs-7 mismatch this exclusion was meant to fix.
                if array_control_count is not None:
                    out[k] = array_control_count
                continue
            if attr is not None and attr.set_type == "2" and not attr.auto_lock:
                # Transient UI/action-layer attr (see ConfigAttr.set_type) —
                # confirmed live: the real CPQ API rejects every one of
                # these with "has an invalid payload" (APX catalog's own
                # population: _price_book_var_name/mergePackage/update/
                # clearPackageJson/testPager2...), same treatment as
                # hide_in_trans. They still drive rules and conversation —
                # only the POST excludes them.
                #
                # auto_lock=1 is the exception (docs/CPQ_SESSION_2_OPEN_
                # ISSUES.md, auto_lock double-wrap finding): a set_type=="2"
                # attr with auto_lock=1 (e.g. archeType_viSoln,
                # modelSelectionSelectModel_viSoln, serviceType_viSoln — the
                # SAME attrs an earlier pass wrongly assumed were always
                # transient) is a real, includable value — falls through to
                # normal serialization below, then gets double-wrapped.
                continue
            if (attr is not None and not attr.options
                    and v == attr.default_value
                    and v in attr_by_vn and v != k):
                # Unresolved pointer token (Issue 11): the value still
                # equals the attr's own pointer default — another attr's
                # variable name, not data. Fill-time guards prevent new
                # fills, but a session filled on an older build carries the
                # token in its saved state; scrub it here so a stale
                # session can never ship '"modelname_all":
                # "_bm_model_variable_name"'.
                continue
            if not (_valid(v) or sources.get(k) in self._CONFIRMED_SOURCES):
                continue
            if attr is None:
                out[k] = {"value": v}
                continue
            select_type = attr.select_type
            if select_type == "boolean":
                out[k] = v.strip().lower() in ("true", "yes")
            elif select_type == "currency":
                try:
                    amount: float | str = float(v)
                except ValueError:
                    amount = v  # not numeric — pass through rather than guess
                out[k] = {
                    "value": amount,
                    "currency": filled.get("_BM_USER_CURRENCY", "USD"),
                }
            elif select_type in ("integer", "float") and attr.options:
                # A MENU-backed numeric (e.g. bWCNumberOfRefreshes_viSoln:
                # data_type=3 but real menu items "1"/"2"/"3") is a menu to
                # the API — bare numeric was rejected live ("has an invalid
                # payload"); the menu shape below is what its siblings with
                # identical menus use. Menu presence wins over data_type.
                out[k] = {"value": v, "displayValue": _display_for(attr, v)}
            elif select_type == "integer":
                out[k] = int(v) if re.fullmatch(r"-?\d+", v) else v
            elif select_type == "float":
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
            elif select_type == "date":
                out[k] = v
            elif attr.options:
                out[k] = {"value": v, "displayValue": _display_for(attr, v)}
            else:
                out[k] = v
            if attr.set_type == "2" and attr.auto_lock and k in out:
                # Confirmed live (archeType_viSoln, modelSelectionSelectModel_
                # viSoln — both set_type=="2"/auto_lock=1, data_type=1/
                # menu_type=1, i.e. ordinary single-select) — the real API
                # wraps this class of attr ONE level deeper than every other
                # menu attr: {"value": {"value":..,"displayValue":..}}. Wraps
                # whatever shape was just built above, generic over
                # select_type — not special-cased to the single-select
                # branch, since no other select_type + auto_lock=1
                # combination has been observed yet either way.
                out[k] = {"value": out[k]}
        # Array-set members (docs/CPQ_ARRAY_SET_PAYLOAD_PLAN.md — BigMachines'
        # composite "array set": a driver/control attr + ordered member
        # columns, e.g. Mounting Type's selector + its own per-row quantity)
        # are accumulated separately here and grouped into _index-keyed rows
        # AFTER this loop, instead of each member becoming its own flat
        # top-level key. array_set_rows: set_id -> {member_variable_name:
        # [selected values]}.
        array_set_rows: dict[int, dict[str, list[str]]] = {}
        for k, vals in (filled_multi or {}).items():
            if k in hidden or not vals or self._is_noise_var(k):
                continue
            attr = attr_by_vn.get(k)
            if attr is not None and attr.hide_in_trans:
                continue
            if (attr is not None and attr.array_set_id is not None
                    and attr.array_set_role == "member"):
                # Array-set membership takes precedence over the generic
                # set_type=="2" exclusion below — confirmed live (APX NEXT/
                # DM4400, re-ingested workspace 25): quantityVX650ItemType_
                # astro (a REAL array-set member, needed in every row) is
                # itself flagged set_type=="2", which would otherwise drop
                # it entirely before it ever reaches the grouping pass. The
                # set_type=="2" exclusion's own evidence (workspace 14) was
                # about standalone transient UI attrs, never array-set rows.
                array_set_rows.setdefault(attr.array_set_id, {})[k] = list(vals)
                continue
            if attr is not None and attr.set_type == "2":
                continue  # transient layer — same exclusion as above
            if attr is not None:
                out[k] = {"items": [
                    {"value": val, "displayValue": _display_for(attr, val)}
                    for val in vals
                ]}
            else:
                out[k] = {"value": list(vals)}

        if array_set_rows:
            drivers_by_set_id = {
                a.array_set_id: a for a in (attrs or [])
                if a.array_set_id is not None and a.array_set_role == "driver"
            }
            for set_id, member_vals in array_set_rows.items():
                driver = drivers_by_set_id.get(set_id)
                if driver is None or not driver.array_set_wrapper_key:
                    continue
                # Dummy/placeholder members (confirmed real example:
                # MountingQuantityDummyArrayAttribute_viSoln — hidden=1,
                # boolean, untouched default) are excluded from the row;
                # both real members (selector + quantity) are hidden=0.
                member_attrs = sorted(
                    (a for a in (attrs or [])
                     if a.array_set_id == set_id and a.array_set_role == "member"
                     and not a.hidden and a.variable_name in member_vals),
                    key=lambda a: a.array_col_order,
                )
                if not member_attrs:
                    continue
                max_len = max(len(member_vals[a.variable_name]) for a in member_attrs)
                # Quantity fallback: a qty-type member (no options) that has
                # no filled_multi entry of its own — the real conversation
                # flow instead filled a per-option NAMED attr for it (see
                # array_set_qty_source above). Sourced per-row from the
                # selector's own selected value at that index.
                selector = next((a for a in member_attrs if a.options), None)
                qty_fallback_members = [
                    a for a in (attrs or [])
                    if a.array_set_id == set_id and a.array_set_role == "member"
                    and not a.hidden and not a.options
                    and a.variable_name not in member_vals
                ]
                item_map = grid_links.get(selector.variable_name, {}) if selector else {}
                rows: list[dict[str, Any]] = []
                for idx in range(max_len):
                    row: dict[str, Any] = {"_index": idx}
                    for a in member_attrs:
                        vlist = member_vals[a.variable_name]
                        if idx >= len(vlist):
                            continue
                        val = vlist[idx]
                        if a.options:
                            row[a.variable_name] = {
                                "value": val, "displayValue": _display_for(a, val),
                            }
                        elif re.fullmatch(r"-?\d+", val):
                            row[a.variable_name] = int(val)
                        else:
                            row[a.variable_name] = val
                    if selector and qty_fallback_members:
                        sel_vlist = member_vals[selector.variable_name]
                        sel_val = sel_vlist[idx] if idx < len(sel_vlist) else None
                        if sel_val:
                            real_qty_vn = item_map.get(sel_val.strip().lower())
                            if real_qty_vn and real_qty_vn in filled:
                                raw = filled[real_qty_vn]
                                for qty_member in qty_fallback_members:
                                    row[qty_member.variable_name] = (
                                        int(raw) if re.fullmatch(r"-?\d+", raw) else raw
                                    )
                    rows.append(row)
                out[driver.array_set_wrapper_key] = {"items": rows}
                # The driver's own value ships as a SIBLING bare int (row
                # count), NOT nested inside the wrapper — confirmed by a
                # real reference payload. Supersedes the narrower
                # is_array_control heuristic above (single control + single
                # multi-select) whenever a real array-set link exists.
                out[driver.variable_name] = len(rows)
        if rules:
            ordered_keys = self._dependency_ordered_keys(list(out.keys()), attr_by_vn, rules)
        else:
            # Present in the same order the XML/graph itself defines
            # (bm_config_attr.order_number, loaded into ConfigAttr.order)
            # rather than insertion order from auto_fill's hint/default/
            # rule/fallback passes — the two are unrelated, and callers
            # cross-checking the payload against the raw catalog expect the
            # catalog's own order. Keys with no matching ConfigAttr (e.g.
            # hidddenRecordSeparator_allFamilly) keep their original
            # relative position, sorted after every real attr. See
            # _dependency_ordered_keys' docstring for why order_number
            # alone is not a reliable proxy for true submission sequence —
            # this branch only runs when the caller didn't supply `rules`.
            ordered_keys = sorted(
                out.keys(),
                key=lambda k: (attr_by_vn[k].order if k in attr_by_vn else 10**9),
            )
        if display_order is not None:
            ordered_keys = sorted(
                (k for k in ordered_keys if k in display_order),
                key=lambda k: display_order[k],
            )
        result: dict[str, Any] = {"configData": {k: out[k] for k in ordered_keys}}
        if product_quantity is not None:
            result["quantity"] = product_quantity
        return result

    @staticmethod
    def _rule_condition_edges(
        attrs: list["ConfigAttr"],
        rules: list[Any],
    ) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[int, str]]:
        """Shared, UNFILTERED rule-condition -> target edge extraction.

        Returns (predecessors, successors, id_to_vn):
          predecessors[target_vn] = set of condition_vn that gate it
          successors[condition_vn] = set of target_vn it gates
          id_to_vn = BM-native id -> variable_name (ConfigAttr.source_id
            preferred, falls back to entity_id — same dual-id convention
            _attr_index already uses)

        Edges come from every rule with a real DECLARATIVE condition
        (`conditions`, or a nonzero `condition_attr_id`) — one edge per
        distinct attr_id referenced. Unlike a payload-key-ordering
        consumer (_dependency_ordered_keys), this does NOT restrict edges
        to any subset of attrs/keys: a rule's condition attribute may be
        currently hidden or unfilled (and so absent from a given turn's
        output) while still being a real, structural gate that rule-
        specificity ranking (_attribute_depth_ranks) needs to see.
        """
        attr_by_vn = {a.variable_name: a for a in attrs}
        id_to_vn: dict[int, str] = {}
        for vn, a in attr_by_vn.items():
            id_to_vn.setdefault(a.entity_id, vn)
        for vn, a in attr_by_vn.items():
            if a.source_id is not None:
                id_to_vn[a.source_id] = vn

        predecessors: dict[str, set[str]] = {}

        def _add_edge(cond_id: int, target_id: int) -> None:
            cond_vn = id_to_vn.get(cond_id)
            target_vn = id_to_vn.get(target_id)
            if cond_vn and target_vn and cond_vn != target_vn:
                predecessors.setdefault(target_vn, set()).add(cond_vn)

        for r in rules:
            target_id = getattr(r, "target_attr_id", None)
            if not target_id:
                continue
            conditions = getattr(r, "conditions", None)
            if conditions:
                for cond_id, *_rest in conditions:
                    _add_edge(cond_id, target_id)
            else:
                cond_id = getattr(r, "condition_attr_id", 0)
                if cond_id:
                    _add_edge(cond_id, target_id)

        successors: dict[str, set[str]] = {}
        for target_vn, conds in predecessors.items():
            for c in conds:
                successors.setdefault(c, set()).add(target_vn)

        return predecessors, successors, id_to_vn

    @staticmethod
    def _attribute_depth_ranks(
        attrs: list["ConfigAttr"],
        rules: list[Any],
    ) -> dict[str, int]:
        """Longest-path-from-root depth per variable_name in the rule
        condition-gating graph (see _rule_condition_edges) — a generic,
        catalog-agnostic stand-in for "how broad vs. specific is this
        attribute" (docs/CPQ_RULE_SPECIFICITY_EXECUTION_ORDER_PLAN_
        2026_08_04.md): depth 0 = nothing gates this attribute (coarsest
        anchor); each attribute's depth = 1 + the max depth of whatever
        gates it (e.g. the confirmed Hardware Version -> Product
        Selection constraint means Product Selection's depth is Hardware
        Version's depth + 1).

        Cycle-safe: a genuine cycle (or anything transitively downstream
        of one) never reaches zero remaining in-degree during the
        Kahn's-algorithm peel below. Those nodes get max(all resolved
        depths) + 1 rather than depth 0 — an unverifiable/cyclic
        dependency must never be treated as "most trusted," which depth
        0 would imply.
        """
        predecessors, successors, _id_to_vn = CpqEngine._rule_condition_edges(attrs, rules)
        all_vns = {a.variable_name for a in attrs}

        remaining = {vn: len(predecessors.get(vn, ())) for vn in all_vns}
        depth: dict[str, int] = {}
        ready = [vn for vn, n in remaining.items() if n == 0]
        for vn in ready:
            depth[vn] = 0
        visited: set[str] = set(ready)

        while ready:
            vn = ready.pop(0)
            for succ in successors.get(vn, ()):
                if succ not in all_vns:
                    continue
                depth[succ] = max(depth.get(succ, 0), depth[vn] + 1)
                remaining[succ] -= 1
                if remaining[succ] == 0 and succ not in visited:
                    visited.add(succ)
                    ready.append(succ)

        resolved_depths = list(depth.values())
        fallback_depth = (max(resolved_depths) + 1) if resolved_depths else 0
        for vn in all_vns:
            if vn not in depth:
                depth[vn] = fallback_depth
        return depth

    def rank_rules_by_specificity(
        self,
        attrs: list["ConfigAttr"],
        hiding_rules: list["HidingRule"],
        rec_rules: list["RecommendationRule"],
        con_rules: list["ConstraintRule"],
        display_order: dict[str, int] | None = None,
    ) -> tuple[list["HidingRule"], list["RecommendationRule"], list["ConstraintRule"]]:
        """Stable-sort hiding/recommendation rules coarsest-condition-first,
        most-specific-condition-last, so the existing "last rule wins"
        semantics in apply_hiding_rules/apply_recommendation_rules resolve
        same-target conflicts via provable specificity instead of
        whatever order fetch_rules()/fetch_value_rules() happened to
        return (neither has an ORDER BY — confirmed in rdb.py). See
        docs/CPQ_RULE_SPECIFICITY_EXECUTION_ORDER_PLAN_2026_08_04.md.

        display_order — docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2b:
        the catalog's FULL layout document order (`_load_layout_full_
        order` — includes layout-hidden attrs like a derived Base Model,
        unlike `load_layout_display_order`'s visible-only map, since a
        rule's condition attribute is very often itself hidden). When
        supplied, tier 2 below (a real declarative condition) ranks by the
        MAX layout position among the condition's attribute(s) instead of
        _attribute_depth_ranks' graph depth — confirmed live to matter:
        `hWVersion_astro` sits at a shallow depth in the dependency graph
        but gates real downstream decisions, while depth alone doesn't
        reflect the real native UI's own notion of "how far into the
        configuration flow" a condition sits. A condition attribute absent
        from the layout (shouldn't normally happen — every real condition
        attribute is a real catalog attribute — but the layout file may
        simply not mention it) ranks at position -1 within tier 2, i.e.
        least specific among real declarative conditions, never treated as
        equal-or-better than a measured position (this codebase's
        "unknown never outranks known" convention). `None` (the default)
        keeps today's depth-based ranking completely unchanged.

        con_rules is returned UNCHANGED — apply_constraint_rules' allowed-
        value intersection (_intersect) is commutative, so reordering it
        can never change its result; doing so would only reorder log
        lines/BML prefetch scheduling for zero correctness benefit.

        Three specificity TIERS, least to most specific (a rule's own
        `condition_script` — a separate gating script — is structural
        metadata we can see without parsing script CONTENT; the graph
        depth from _attribute_depth_ranks only ever comes from real
        declarative conditions, since that's the only thing it can
        extract edges from):

          0. No gating condition at all — no `conditions`, no
             `condition_attr_id`, no `condition_script` (whether or not
             it has a value-only `script`, e.g. a hiding/recommendation
             rule that just always returns one fixed outcome/value with
             no separate condition). Least specific — sorts first.
          1. Gated by a `condition_script` but no declarative condition
             info at all — a real, live example: workspace 39004's
             "Default to Latest Release if not NA/fed customer" is
             condition_script-gated with condition_attr_id=0/no
             conditions, competing against "Set default to Baseline
             Release" (tier 0, a bare value script, no condition_script)
             on the same target. We can't measure exactly how deep the
             condition_script's own logic sits, but its mere presence
             proves the rule is MORE narrowly scoped than an
             unconditional tier-0 rule, so it ranks after tier 0 and
             wins ties against it — without ever parsing what the
             script actually checks.
          2. A real declarative condition (`conditions`/
             `condition_attr_id`) — ranked by the MAX depth
             (_attribute_depth_ranks) among the attribute(s) it
             references. Most specific, provably ordered within this
             tier; always sorts after tiers 0 and 1.

        Within tiers 0/1 (where exact specificity isn't measurable),
        ties are broken by the rule's own target's ConfigAttr.order —
        never by "last unknown wins," matching apply_hiding_rules'/
        apply_recommendation_rules' own "unknown -> don't act/don't
        guess" convention for script outcomes elsewhere in this file.

        attrs MUST be the full, pre-loop catalog as passed into
        evaluate_rules_loop — never a loop-local `attrs` already shrunk
        by apply_hiding_rules, which would wrongly zero out predecessors
        for hidden attributes.
        """
        id_to_vn: dict[int, str] = {}
        for a in attrs:
            id_to_vn.setdefault(a.entity_id, a.variable_name)
        for a in attrs:
            if a.source_id is not None:
                id_to_vn[a.source_id] = a.variable_name
        order_by_vn = {a.variable_name: a.order for a in attrs}

        depth_by_vn = self._attribute_depth_ranks(attrs, [*hiding_rules, *rec_rules])

        def _rule_rank(rule: Any) -> tuple[int, int, int]:
            cond_ids: list[int] = []
            conditions = getattr(rule, "conditions", None)
            if conditions:
                cond_ids = [cid for cid, *_rest in conditions]
            else:
                cid = getattr(rule, "condition_attr_id", 0)
                if cid:
                    cond_ids = [cid]
            cond_vns = [
                id_to_vn[cid] for cid in cond_ids
                if cid in id_to_vn and id_to_vn[cid] in depth_by_vn
            ]
            if cond_vns:
                if display_order is not None:
                    return (2, max(display_order.get(vn, -1) for vn in cond_vns), 0)
                return (2, max(depth_by_vn[vn] for vn in cond_vns), 0)

            target_id = getattr(rule, "target_attr_id", None)
            target_vn = id_to_vn.get(target_id) if target_id else None
            fallback_order = order_by_vn.get(target_vn, 10**9) if target_vn else 10**9
            if getattr(rule, "condition_script", None):
                return (1, 0, fallback_order)
            return (0, 0, fallback_order)

        sorted_hiding = sorted(hiding_rules, key=_rule_rank)
        sorted_rec = sorted(rec_rules, key=_rule_rank)
        return sorted_hiding, sorted_rec, con_rules

    @staticmethod
    def _dependency_ordered_keys(
        keys: list[str],
        attr_by_vn: dict[str, "ConfigAttr"],
        rules: list[Any],
    ) -> list[str]:
        """Topological sort of `keys` by rule-proven attribute dependency.

        Builds a "must come before" edge condition_vn -> target_vn for
        every rule with a real DECLARATIVE condition (conditions, or a
        nonzero condition_attr_id) whose condition and target are both
        present in `keys`. Kahn's algorithm, with ConfigAttr.order
        (bm_config_attr.order_number) as the tie-break for which
        zero-remaining-dependency key is emitted next, so output stays
        deterministic and close to the catalog's own display order
        whenever no dependency constrains it either way.

        Rule ids reference attributes by their BM-native id — matches
        ConfigAttr.source_id first (falls back to entity_id), the same
        dual-id convention _attr_index already uses. Edge extraction
        itself is shared with _attribute_depth_ranks via
        _rule_condition_edges; this method applies its own `keys`
        restriction on top since only-what's-being-emitted is a payload-
        key-ordering-specific constraint.
        """
        attrs = list(attr_by_vn.values())
        predecessors_all, _successors_all, _id_to_vn = CpqEngine._rule_condition_edges(
            attrs, rules)

        key_set = set(keys)
        predecessors: dict[str, set[str]] = {
            target_vn: {c for c in conds if c in key_set}
            for target_vn, conds in predecessors_all.items()
            if target_vn in key_set
        }

        successors: dict[str, set[str]] = {}
        for target_vn, conds in predecessors.items():
            for c in conds:
                successors.setdefault(c, set()).add(target_vn)

        def _order_key(vn: str) -> int:
            a = attr_by_vn.get(vn)
            return a.order if a is not None else 10**9

        remaining = {vn: len(predecessors.get(vn, ())) for vn in keys}
        ready = sorted((vn for vn, n in remaining.items() if n == 0), key=_order_key)
        result: list[str] = []
        visited: set[str] = set()
        while ready:
            vn = ready.pop(0)
            if vn in visited:
                continue
            visited.add(vn)
            result.append(vn)
            newly_ready = []
            for succ in successors.get(vn, ()):
                remaining[succ] -= 1
                if remaining[succ] == 0 and succ not in visited:
                    newly_ready.append(succ)
            if newly_ready:
                ready.extend(newly_ready)
                ready.sort(key=_order_key)
        # A cycle in rule data (never expected, but rule authoring can be
        # messy) leaves some keys with remaining > 0 forever — append them
        # by order_number rather than drop or crash, same "never lose a
        # key" contract the no-rules branch already has.
        leftover = sorted((vn for vn in keys if vn not in visited), key=_order_key)
        result.extend(leftover)
        return result

    # ── Summary renderer ──────────────────────────────────────────────────────

    @staticmethod
    def _is_noise_var(variable_name: str) -> bool:
        """True for underscore-prefixed or integration/system-prefixed vars.

        Structural, not name-list-based (§3e): an underscore prefix, or a
        leading `_`-delimited segment that is fully uppercase (e.g.
        `CRM_BILL_COUNTRY`) — the same shape live data showed for
        integration fields, derived from casing convention rather than a
        hardcoded prefix list.
        """
        if variable_name.startswith("_"):
            return True
        head = variable_name.split("_", 1)[0]
        return len(head) >= 2 and head.isalpha() and head.isupper()

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
    ) -> bool:
        """True when a filled attr should not get a summary line.

        Boolean-shaped values (yes/no/true/false, or select_type=="boolean")
        are excluded even when user-chosen — the ask was to only surface
        substantive selections. Secondary-* attrs (inactive duplicates like
        the secondary SIM) and warranty attrs are excluded by name; warranty
        must also match the VALUE ("Service Type → 1 Year Standard
        Warranty" carries the word only there). Product/product-line attrs
        are excluded too — the summary header already names the product, so
        those lines are redundant; they must match the VARIABLE NAME as
        well (`productLineName`, `bm_prd_level_product_line`, ...) because
        several carry labels without the word. Duration-shaped values
        ("1 Year", "3 Years") are excluded as well — subscription terms,
        not configuration choices.
        """
        if value.strip().lower() in self._BOOLEAN_DISPLAY_VALUES:
            return True
        if self._YEAR_VALUE_RE.search(value):
            return True
        if attr is not None and attr.select_type == "boolean":
            return True
        # Issue 5 items 1/2 (docs/config_consistency_issues_2026-07-30.md):
        # build_payload() already excludes hide_in_trans==1 attrs (the
        # source system's own "don't submit this at transaction time"
        # marker) and set_type=="2" (transient UI/action-layer, non-auto-
        # lock) attrs from the submitted BOM — but the conversational
        # summary never applied the same two checks, so a sales rep could
        # see a line in "Associated Options" for a field that will never
        # actually appear in what gets submitted. Same checks, same attr
        # object already available here — mirrors build_payload exactly,
        # no separate exclusion set needed for these two.
        if attr is not None and attr.hide_in_trans:
            return True
        if attr is not None and attr.set_type == "2" and not attr.auto_lock:
            return True
        if attr is not None and attr.hidden and source != "user":
            # hidden=1 in the raw XML means BigMachines' own UI renders this
            # inline as part of a grid widget rather than as its own summary
            # line (confirmed live: 248 hidden attrs in workspace 14, almost
            # all genuine internal/system fields — _config_operation_context,
            # customerUIN, subscriptionStatus_all — never customer-answered).
            # But a grid-quantity companion (e.g.
            # mountingTypeLockingMolleMountQuantity_viSoln) IS hidden=1 yet
            # still gets asked and answered directly in this chat interface,
            # which has no grid rendering to fall back on — excluding it
            # silently dropped the one number the customer actually gave
            # (confirmed live: "15" survived in `filled`/the real payload,
            # just never shown back to them). Only user-sourced answers get
            # this carve-out; rule/default-filled hidden attrs stay excluded.
            return True
        label_l = display_label.lower()
        if "secondary" in label_l:
            return True
        if "warranty" in label_l or "warranty" in value.lower():
            return True
        if variable_name == "productSelectionProduct_all":
            # Exempted from the "product" exclusion below: that rule
            # assumes "the summary header already names the product," but
            # the header shows the internal BOM codename (e.g. "aSTRO25_
            # bom"), never the real, customer-facing product name — this
            # IS that real name (confirmed live: "APX NEXT Enhanced" was
            # silently missing from every summary despite being correctly
            # filled). Every other product/product-line attr this
            # exclusion targets (productLineName, bm_prd_level_product_
            # line, ...) stays excluded.
            return False
        return "product" in label_l or "product" in variable_name.lower()

    def _filled_summary_triples(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
        sources: dict[str, str] | None = None,
        display_order: dict[str, int] | None = None,
    ) -> list[tuple[str, str, str]]:
        """Filtered (variable_name, display_label, value) triples worth
        summarising — same filtering as filled_summary_pairs, but keeps
        variable_name so callers (render_filled_summary's category
        grouping) can pattern-match on it. See filled_summary_pairs for the
        filtering rules this applies.

        display_order — optional {variable_name: rank} from
        `load_layout_display_order` (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_
        PLAN.md §2). When supplied, restricts to exactly the attrs present
        in the map and sorts by rank instead of `display_filled`'s
        fill-order — the same catalog layout the real native UI shows,
        instead of an incidental artifact of resolution order. `None`
        (the default) keeps today's behavior unchanged.
        """
        if not display_filled:
            return []
        by_vn: dict[str, "ConfigAttr"] = {a.variable_name: a for a in attrs} if attrs else {}
        label_map: dict[str, str] = {vn: a.display_label for vn, a in by_vn.items()}
        # Disambiguate a display_label 2+ distinct attrs share (real
        # BigMachines source-data reuse, docs/CPQ_SESSION_2_OPEN_ISSUES.md
        # item 2) by appending variable_name — otherwise two unrelated rows
        # render as identical, unreadable duplicate lines in the summary.
        _label_counts: dict[str, int] = {}
        for _lbl in label_map.values():
            _label_counts[_lbl] = _label_counts.get(_lbl, 0) + 1
        for vn, lbl in list(label_map.items()):
            if _label_counts.get(lbl, 0) >= 2:
                label_map[vn] = f"{lbl} ({vn})"
        items = [
            (var, label) for var, label in display_filled.items()
            if not self._is_html_value(label)
            and not self._is_noise_var(var)
            and not self._is_summary_excluded(
                var, label_map.get(var, var), label, by_vn.get(var),
                source=(sources or {}).get(var))
            # "(none)" is the engine's own literal placeholder for an
            # unfilled multi/array-typed field (e.g. Promotion, Solution
            # Set) — confirmed live: it survives every other filter since
            # it's a real, deliberately-set display value, not noise by any
            # existing rule. Worth summarising nothing, so drop it here.
            and label.strip() != "(none)"
        ]
        if rule_governed_ids is not None:
            items = [
                (var, label) for var, label in items
                if (attr := by_vn.get(var)) and attr.entity_id in rule_governed_ids
                # rule_governed_ids alone is STATIC — "targeted by some rule
                # somewhere in the catalog," regardless of whether that
                # rule's condition actually held THIS turn. As more real
                # rules got correctly wired up this session, that static set
                # grew, silently widening "Associated Options" past the
                # intended "key attributes actually decided" scope. Narrow
                # further to filled_source, the one per-turn signal that
                # tracks whether a rule genuinely fired (source="rule"/
                # "country_derived") or the user genuinely chose something
                # (source="user"/"hint"/"cascade"/"cascade-dependent") —
                # excluding bland "default"/"optional"/"auto" fills that
                # were never actually reasoned about this turn.
                and (sources is None or sources.get(var) in self._SUMMARY_ACTIVE_SOURCES)
            ]
            # Curated business-relevance filter — Associated Options only
            # (the catch-all fallback category); Product Name/Service Plan/
            # Quantity & Duration are already narrow by category definition
            # and stay as-is. Gated the same as the narrowing above — only
            # for callers that opted into the narrowed "sales rep talking
            # points" scope (rule_governed_ids supplied); beautify_rows'/
            # beautify_text's full-detail dump (rule_governed_ids=None)
            # must keep showing every filled attr, unaffected.
            items = [
                (var, label) for var, label in items
                if self._summary_category(var) != _SUMMARY_FALLBACK_CATEGORY
                or any(frag in var.lower().replace("_", "") for frag in _ASSOCIATED_OPTIONS_KEY_FRAGMENTS)
            ]
        if display_order is not None:
            items = sorted(
                (item for item in items if item[0] in display_order),
                key=lambda item: display_order[item[0]],
            )
        return [(var, label_map.get(var, var), label) for var, label in items]

    def filled_summary_pairs(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
        sources: dict[str, str] | None = None,
        display_order: dict[str, int] | None = None,
    ) -> list[tuple[str, str]]:
        """Filtered (display_label, value) pairs worth summarising.

        Uses display_label (human name) as the key when attrs are supplied,
        falling back to variable_name only when the attr is not found.
        Skips HTML template values (layout/display fields), system/
        integration noise (`_is_noise_var`, §3e), and low-signal lines
        (`_is_summary_excluded`: boolean values, secondary attrs, warranty
        attrs, product/product-line attrs, year-duration values).

        rule_governed_ids — when supplied (see `rule_governed_ids()`), only
        attrs a hiding, recommendation, or constraint rule actually
        reasoned about survive (Phase K/§3g). The rest are silently
        omitted — no count of remaining auto-configured fields.
        """
        return [
            (label, value)
            for _var, label, value in self._filled_summary_triples(
                display_filled, attrs, rule_governed_ids, sources, display_order)
        ]

    @staticmethod
    def _summary_category(variable_name: str) -> str:
        """Classify a filled attr into one of the 5 scannable summary
        sections, purely by variable_name fragment — never a literal
        per-catalog field name, so it applies to any ingested XML the same
        way. See _SUMMARY_CATEGORY_KEYS docstring for the matching order.
        """
        vn_flat = (variable_name or "").lower().replace("_", "")
        for category, fragments in _SUMMARY_CATEGORY_KEYS:
            if any(frag in vn_flat for frag in fragments):
                return category
        return _SUMMARY_FALLBACK_CATEGORY

    def beautify_text(
        self,
        product_name: str,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
    ) -> str:
        """Human-readable ``Label : Value`` block for the Beautify button.

        Reuses filled_summary_pairs' noise/low-signal filtering (§ above) so
        Beautify shows the same substantive fields as the conversational
        summary — as aligned key:value lines instead of prose, no LLM call.
        Used as-is by clients that display plain text (e.g. Streamlit's
        st.code). Clients that render a real table use
        beautify_rows()'s structured pairs instead of parsing this string.
        """
        pairs = [("Product", product_name)] + self.filled_summary_pairs(display_filled, attrs)
        width = max(len(label) for label, _ in pairs)
        return "\n".join(f"{label.ljust(width)} : {value}" for label, value in pairs)

    def beautify_rows(
        self,
        product_name: str,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
    ) -> list[dict[str, str]]:
        """Structured [{label, value}, ...] pairs for clients that render a
        real tabular UI (e.g. the Next.js Beautify panel) instead of plain
        text — same data and filtering as beautify_text(), just not
        flattened into a display string. No LLM call.
        """
        pairs = [("Product", product_name)] + self.filled_summary_pairs(display_filled, attrs)
        return [{"label": label, "value": value} for label, value in pairs]

    def render_filled_summary(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
        sources: dict[str, str] | None = None,
        product_quantity: int | None = None,
    ) -> str:
        """Deterministic, categorized summary of what has been auto-filled.

        Groups `filled_summary_pairs()` (which owns ALL the filtering) under
        4 scannable headed sections — Product Name, Service Plan, Quantity
        & Duration, Associated Options — instead of one flat bullet list,
        classified purely by variable_name fragment (`_summary_category`,
        generic across any ingested catalog, never a per-catalog literal).
        Used directly as the fallback whenever the LLM-narrated paragraph
        (ask_api `_cpq_summary_text`) is unavailable or fails.

        product_quantity — forwarded to `categorized_summary_groups` so
        this deterministic fallback shows the same Product Quantity fact,
        in the same position, as the LLM-narrated path.
        """
        groups = self.categorized_summary_groups(
            display_filled, attrs, rule_governed_ids, sources,
            product_quantity=product_quantity)
        if not groups:
            return ""
        heading = "**Configured so far:**" if rule_governed_ids is None else "**Key decisions:**"
        lines = [heading]
        for category, group in groups:
            lines.append(f"\n**{category}:**")
            if category == _SUMMARY_FALLBACK_CATEGORY:
                # This category is a catch-all for everything not
                # classified into the other 3 (confirmed live: 20-50+
                # items on a real quote) — a bullet per item is no longer
                # scannable at that volume, unlike Product Name/Service
                # Plan/Quantity & Duration which stay small. Render as one
                # short, deterministic plain-text line instead — no LLM
                # call, so this path never depends on the narrator being
                # reachable (see this method's own docstring constraint).
                lines.append("; ".join(f"{label}: {value}" for label, value in group) + ".")
            else:
                lines.extend(f"- **{label}** → {value}" for label, value in group)
        return "\n".join(lines)

    def categorized_summary_groups(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
        sources: dict[str, str] | None = None,
        display_order: dict[str, int] | None = None,
        product_quantity: int | None = None,
    ) -> list[tuple[str, list[tuple[str, str]]]]:
        """(category, [(label, value), ...]) groups, non-empty categories
        only, in the fixed display order (Product Name, Service Plan,
        Quantity & Duration, Associated Options — see
        _SUMMARY_CATEGORY_KEYS). Same filtering and classification
        `render_filled_summary` uses for its bullet output; exposed
        separately so callers that build their own presentation (e.g.
        ask_api's LLM-narrated summary) can group the same facts the same
        way instead of inventing their own grouping.

        display_order — see `_filled_summary_triples`; restricts to and
        orders WITHIN each of the fixed categories above by layout rank
        when supplied. Does not replace the 4-category grouping itself.

        product_quantity — the session-level order quantity (a virtual
        fact, not a real catalog attribute, so it can never come out of
        `_filled_summary_triples`). Injected here as the FIRST fact under
        Product Name, labeled "Product Quantity" — previously appended as
        a hardcoded suffix after every category regardless of catalog
        shape, which always put it last (live-verified gap, 2026-08-13).
        Only injected when there's an actual configuration to attach it
        to (`triples` non-empty) — never synthesizes a Product Name
        section out of nothing when no product has been selected yet.
        """
        triples = self._filled_summary_triples(
            display_filled, attrs, rule_governed_ids, sources, display_order)
        if not triples:
            return []
        by_category: dict[str, list[tuple[str, str]]] = {}
        for var, label, value in triples:
            by_category.setdefault(self._summary_category(var), []).append((label, value))
        if product_quantity is not None:
            by_category.setdefault("Product Name", [])
            by_category["Product Name"] = [
                ("Product Quantity", str(product_quantity)),
                *by_category["Product Name"],
            ]
        section_order = [c for c, _ in _SUMMARY_CATEGORY_KEYS] + [_SUMMARY_FALLBACK_CATEGORY]
        return [
            (category, by_category[category])
            for category in section_order
            if by_category.get(category)
        ]
