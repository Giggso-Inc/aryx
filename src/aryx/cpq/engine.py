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
from typing import Any

from aryx.config import get_settings
from aryx.cpq.bml import (
    BmlEvaluator, evaluate_declarative_conditions, extract_literal_comparisons,
)
from aryx.cpq.logging_context import install_run_id_logging
from aryx.cpq.rdb import get_cpq_rdb
from aryx.resolution.classical import string_score
from aryx.cpq.state import (
    ConfigAttr, ConstraintRule, CpqSession, HidingRule, MenuOption,
    RecommendationRule,
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
    min_words = max(2, len(words) - max_dropped_leading)
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


def _condition_value_matches(current_val: str, condition_value: str) -> bool:
    """True when current_val satisfies a single condition_attr/condition_value pair.

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
    """
    allowed = {v.strip().lower() for v in condition_value.split("~") if v.strip()}
    return current_val.strip().lower() in allowed


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


# ── CPQ intent detection ───────────────────────────────────────────────────────
# Generic CPQ-domain vocabulary only — the English words customers use to
# signal configuration intent ("quote", "configure", "bom", ...) are a fixed
# set of the language, not workspace-ingested data, so listing them isn't the
# same kind of hardcoding a product-name list is. Product-name literals
# (formerly apx|mototrbo|sl3500|dpx|xpr here) were removed — is_cpq_question()
# now also checks the workspace's actually-ingested product names dynamically.
_CPQ_TRIGGER = re.compile(
    r"\b(quote|configure|configuration|build.*quote|create.*quote|"
    r"radio|"
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
_COUNTRY_HINT_SHORTHAND: dict[str, tuple[str, ...]] = {
    "united states": ("US", "USA"),
    "united kingdom": ("UK", "GB"),
}

# Generic country extraction — captures any proper-noun country name from NL
# phrases like "customer in Australia", "located in New Zealand", "for Canada".
# The extracted name is matched word-boundary against DB option display names,
# so no country → item_value mapping is needed here.
_COUNTRY_PREP = re.compile(
    r"\b(?:in|for|from|customer\s+in|located\s+in|based\s+in)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
    re.IGNORECASE,
)

# Region hints (abbreviations the generic extractor won't catch as country names)
_REGION_PATTERNS: list[tuple[str, str]] = [
    (r"\b(north\s+america|namer)\b", "NA"),
    (r"\bemea\b", "EMEA"),
    (r"\bapac\b", "APAC"),
    (r"\blatin\s+america\b", "LA"),
]

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
    ("Product Name", ("selectmodel", "basemodel", "modelname", "productname",
                       "productselection", "producttype")),
    ("Service Plan", ("service", "billing", "plan", "solutiontype", "archetype")),
    ("Quantity & Duration", ("quantity", "duration", "qty")),
)
_SUMMARY_FALLBACK_CATEGORY = "Associated Options"

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
        """
        if _CPQ_TRIGGER.search(question):
            return True
        if reader is None:
            return False
        q_norm = re.sub(r"[^a-z0-9]", "", question.lower())
        if not q_norm:
            return False
        return any(
            re.sub(r"[^a-z0-9]", "", name.lower()) in q_norm
            for name in self._ingested_product_names(reader, workspace_id)
            if name
        )

    def extract_hints(self, question: str) -> dict[str, str]:
        """Extract attribute value hints from natural language.

        Returns {attr_key_fragment: hint_value} where hint_value is matched
        word-boundary against DB option display names — no hardcoded country list.
        """
        hints: dict[str, str] = {}

        # Specific shortcut patterns — first match wins per key; more specific
        # patterns must be listed first in _HINT_PATTERNS (see ordering comment there).
        for key, pattern, value in _HINT_PATTERNS:
            if key not in hints and re.search(pattern, question, re.IGNORECASE):
                hints[key] = value

        # Generic country extraction: "customer in Australia", "located in New Zealand"
        # Captures the proper-noun after a preposition and matches it against DB display names.
        if "country" not in hints:
            m = _COUNTRY_PREP.search(question)
            if m:
                hints["country"] = m.group(1).strip().title()

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
                for text in (opt.item_value, opt.display_name):
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
            vn, item_value = entries[0]
            if vn in hints:
                continue  # a longer, more specific phrase already matched this attr
            if _is_negated_before(q_lower, q_index_map[idx]):
                continue  # "exclude ... <phrase>" — not a selection
            hints[vn] = item_value

        negated_vns: set[str] = set()
        for phrase, owners in all_owners.items():
            idx = _find_plural_tolerant(q_norm, phrase)
            if idx == -1:
                continue
            if not _is_negated_before(q_lower, q_index_map[idx]):
                continue
            negated_vns.update(owners)
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
            scored = self._fuzzy_score_candidates(q_norm, ordered)
            if scored and scored[0][1] >= _PRODUCT_FUZZY_MATCH_THRESHOLD:
                return alias_map[scored[0][0]]
        return next((v for k, v in hints.items() if "product" in k), "")

    @staticmethod
    def _fuzzy_score_candidates(
        q_norm: str, ordered: list[tuple[str, str]],
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
        scored = self._fuzzy_score_candidates(q_norm, ordered)
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
        fallback_candidates: list[tuple[int, int]] = []  # (entity_id, option_count)
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
                try:
                    neighbor_count = len(reader.neighbors(ent["id"]))
                except Exception:
                    neighbor_count = 0
                fallback_candidates.append((ent["id"], neighbor_count))
        if target_id is None and fallback_candidates:
            target_id = max(fallback_candidates, key=lambda c: c[1])[0]
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
            attr_ents.extend(reader.find_entities(ontology_type=attr_type, limit=500))

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
        for ent in attr_ents:
            eid = ent["id"]
            try:
                neighbors = reader.neighbors(eid)
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

        # Single batch fetch for all menu items across all attrs
        all_menu_pg = self._batch_fetch(all_menu_ids, workspace_id) if all_menu_ids else {}

        menu_by_attr: dict[int, list[MenuOption]] = {}
        for eid, menu_ids in neighbor_map.items():
            opts: list[MenuOption] = []
            # (item_value, display_name) pairs already added for this attr —
            # company-level/global BM attrs (e.g. _BM_USER_CURRENCY,
            # _BM_USER_LANGUAGE, _BM_USER_NUMBER_FORMAT) share one native id
            # across every ingested catalog from the same BM tenant, and
            # reader.neighbors() has no catalog-prefix scoping of its own, so
            # a workspace holding 2+ catalogs can surface the same option
            # more than once for these specific attrs (confirmed live: "US
            # Dollar" offered twice). See docs/CPQ_MULTI_CATALOG_ASK_FLOW_BUGS_PLAN.md
            # Bug 1 — this is the safe, minimal backstop; product-specific
            # attrs never hit this since their menu items are never
            # re-exported verbatim across catalogs.
            seen_opts: set[tuple[str, str]] = set()
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
                    key = (iv_lo, dt_lo)
                    if key in seen_opts:
                        continue
                    seen_opts.add(key)
                    opts.append(MenuOption(item_value=iv, display_name=dt, order=order))
            opts.sort(key=lambda x: x.order)
            menu_by_attr[eid] = opts

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
            if is_hidden and not default_val and not (is_array_control or is_grid_qty_candidate):
                # Hidden with nothing to contribute — never shown/asked, and
                # no default to feed BML scripts, so still fully dropped.
                continue

            hide_in_trans_raw = str(pg.get("hide_in_trans") or "0").strip().lower()
            is_hide_in_trans = hide_in_trans_raw in ("1", "true", "yes")

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
            ))

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
        """
        rdb = get_cpq_rdb()
        inputs_by_rule: dict[int, list[tuple[int, str]]] = {}
        for rid, aid, val in rdb.fetch_rule_inputs(workspace_id, catalog_prefix):
            inputs_by_rule.setdefault(rid, []).append((aid, val))
        actions_by_rule: dict[int, list[tuple[int, int, str, int, int]]] = {}
        for rid, aid, at, val, fn, st in rdb.fetch_rule_actions(workspace_id, catalog_prefix):
            actions_by_rule.setdefault(rid, []).append((aid, at, val, fn, st))
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
        return rdb, inputs_by_rule, actions_by_rule, marked_by_rule, chain_by_rule

    @staticmethod
    def _resolve_targets(
        rule_key: int,
        actions_by_rule: dict[int, list[tuple[int, int, str, int, int]]],
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
            return [(aid, at) for aid, at, _v, _f, _st in acts]
        marked = marked_by_rule.get(rule_key)
        if marked:
            return [(aid, 2) for aid in marked]
        seen: set[int] = {rule_key}
        current = chain_by_rule.get(rule_key)
        hops = 0
        while current is not None and current not in seen and hops < max_hops:
            acts = actions_by_rule.get(current, [])
            if acts:
                return [(aid, at) for aid, at, _v, _f, _st in acts]
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
        rules: list[HidingRule] = []
        script_missing = 0
        unresolved = 0
        try:
            rdb, inputs, actions, marked, chain = self._load_rule_join_data(
                workspace_id, catalog_prefix)
            scripts = rdb.fetch_function_scripts(workspace_id, catalog_prefix)
            for eid, src_id, rule_name, fn_id in rdb.fetch_rules(workspace_id, "11", catalog_prefix):
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
                cond_attr_id, cond_value = inp_list[-1]
                for target_attr_id, action_type in targets:
                    rules.append(HidingRule(
                        rule_name=rule_name or str(eid),
                        condition_attr_id=cond_attr_id,
                        condition_value=cond_value,
                        target_attr_id=target_attr_id,
                        hide=(int(action_type or 2) == 2),
                        conditions=list(inp_list),
                    ))
        except Exception:
            logger.debug("cpq: hiding rule load failed", exc_info=True)

        script_backed = sum(1 for r in rules if r.script is not None)
        logger.info(
            "cpq: loaded %d hiding rules (%d declarative, %d script-backed, "
            "%d missing script, %d unresolved)",
            len(rules), len(rules) - script_backed, script_backed,
            script_missing, unresolved)
        return rules

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
    ) -> dict[int, str]:
        """Map every id a rule may reference → the attr's filled value."""
        out: dict[int, str] = {}
        for a in attrs:
            if a.variable_name in filled:
                val = filled[a.variable_name]
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

        Returns:
          filtered_attrs — attrs still visible after rules are applied
          rule_messages  — human-readable list of rules that fired (for reporting)
          hidden_vns     — variable_names explicitly hidden by a fired rule
        """
        if not rules:
            return attrs, [], set()

        by_rule_id = self._attr_index(attrs)
        filled_by_rule_id = self._filled_by_rule_id(attrs, filled)

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
                elif hide is False:
                    hidden_eids.discard(target.entity_id)
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
                if not _condition_value_matches(current_val, rule.condition_value):
                    continue
            if rule.hide:
                hidden_eids.add(target.entity_id)
                messages.append(
                    f"*Rule '{rule.rule_name}' hid **{target.display_label}***"
                )
            else:
                hidden_eids.discard(target.entity_id)

        hidden_vns = {a.variable_name for a in attrs if a.entity_id in hidden_eids}
        filtered = [a for a in attrs if a.entity_id not in hidden_eids]
        return filtered, messages, hidden_vns

    # ── Recommendation rule loader ────────────────────────────────────────────

    def _load_value_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> tuple[list[RecommendationRule], list[ConstraintRule]]:
        """Load recommendation + constraint rules together in one pass.

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
        default). This classifies every non-hiding rule by inspecting its
        own actions instead of trusting rule_type/action_type.

        Hiding rules (rule_type=11) are unaffected by any of this — that
        code has proven reliable across both catalogs and is loaded
        separately by load_hiding_rules().

        catalog_prefix — scopes to one ingested catalog (see
        _load_rule_join_data) when the workspace holds more than one
        product's XML export. "" preserves the original workspace-wide load.
        """
        rec_rules: list[RecommendationRule] = []
        con_rules: list[ConstraintRule] = []
        script_constraints = 0
        script_recommendations_wired = 0
        cond_script_skipped = 0
        script_condition_gated = 0
        ambiguous_recommendations_skipped = 0
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
                workspace_id, catalog_prefix,
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
                for aid, _at, _val, act_fn, act_set_type in acts:
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
                    cond_attr_id, cond_value = 0, ""
                else:
                    if not inp_list:
                        continue
                    cond_attr_id, cond_value = inp_list[-1]

                # Declarative actions, bucketed per target by set_type.
                # BigMachines packs multiple allowed values for one action
                # into a single value1 field, tilde-delimited (confirmed live:
                # "DEVICE RENTAL~DEVICE INSTALLATION~DEVICE PROGRAMMING" for
                # one rule_action row) — split before use or the whole glued
                # string gets treated as one (non-existent) option, leaving
                # the target with zero real valid values.
                restrict_by_target: dict[int, list[str]] = {}
                recommend_by_target: dict[int, str] = {}
                for aid, _at, val, act_fn, set_type in acts:
                    if act_fn != -1 or not val:
                        continue
                    parts = [p.strip() for p in val.split("~") if p.strip()]
                    if set_type == -1:
                        restrict_by_target.setdefault(aid, []).extend(parts)
                    elif len(parts) == 1:
                        recommend_by_target.setdefault(aid, parts[0])
                    else:
                        # A recommendation assigns ONE default value — several
                        # tilde-delimited candidates means picking one would be
                        # guessing (same D2 "never guess" rule that governs
                        # auto_fill elsewhere). Never guessed in code — routed
                        # to a human via aryx_ingest_question instead. An
                        # already-answered rule resolves like any other
                        # RecommendationRule; an unanswered one stays skipped
                        # (visible in the queue, not a dead-end log line).
                        job_id = f"cpq-rule-{eid}-{aid}"
                        existing = existing_questions.get(job_id)
                        if (existing and existing.get("status") == "answered"
                                and existing.get("answer") in parts):
                            recommend_by_target.setdefault(aid, existing["answer"])
                            continue
                        ambiguous_recommendations_skipped += 1
                        logger.info(
                            "cpq: rule %r has a multi-value recommendation "
                            "action for target=%d (%r) — ambiguous which is "
                            "the default, %s", rule_name, aid, parts,
                            "awaiting human answer (already queued)" if existing
                            else "queued for human answer")
                        if not existing and ingest_store is not None:
                            try:
                                ingest_store.enqueue(
                                    workspace_id, job_id=job_id,
                                    kind="cpq_ambiguous_recommendation",
                                    prompt=(
                                        f"Rule '{rule_name}' recommends one of "
                                        f"{parts} for attribute {aid} — which "
                                        "should be the default?"),
                                    options=parts, suggested="")
                                existing_questions[job_id] = {"status": "pending"}
                            except Exception:
                                logger.debug(
                                    "cpq: failed to enqueue ambiguous-"
                                    "recommendation ingest question",
                                    exc_info=True)

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
                    con_rules.append(ConstraintRule(
                        rule_name=rule_name or str(eid),
                        condition_attr_id=cond_attr_id,
                        condition_value=cond_value,
                        target_attr_id=target_attr_id,
                        allowed_values=allowed,
                        conditions=list(inp_list) if condition_script is None else None,
                        condition_script=condition_script,
                    ))
                for target_attr_id, rec_val in recommend_by_target.items():
                    rec_rules.append(RecommendationRule(
                        rule_name=rule_name or str(eid),
                        condition_attr_id=cond_attr_id,
                        condition_value=cond_value,
                        target_attr_id=target_attr_id,
                        recommended_value=rec_val,
                        conditions=list(inp_list) if condition_script is None else None,
                        condition_script=condition_script,
                    ))
        except Exception:
            logger.debug("cpq: value-rule load failed", exc_info=True)
        logger.info(
            "cpq: loaded %d recommendation rules, %d constraint rules "
            "(%d script-backed constraints, %d script-backed recommendations "
            "wired, %d script-condition rules gating a declarative action, "
            "%d script-condition rules skipped, %d ambiguous "
            "multi-value recommendations skipped)",
            len(rec_rules), len(con_rules), script_constraints,
            script_recommendations_wired, script_condition_gated,
            cond_script_skipped, ambiguous_recommendations_skipped)
        return rec_rules, con_rules

    def load_recommendation_and_constraint_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> tuple[list[RecommendationRule], list[ConstraintRule]]:
        """Both rule sets in a single pass — the call callers wanting BOTH
        should use. load_recommendation_rules()/load_constraint_rules() each
        independently call _load_value_rules(), which repeats the same 4
        join-table queries plus a full function-script scan; calling both
        back-to-back (as every CPQ turn does) doubles that DB work for no
        reason. Prefer this method whenever both lists are needed."""
        return self._load_value_rules(workspace_id, catalog_prefix)

    def load_recommendation_rules(
        self, workspace_id: int, catalog_prefix: str = "",
    ) -> list[RecommendationRule]:
        """Recommendation rules for this catalog — see _load_value_rules for
        how rule semantics are classified (NOT by rule_type/action_type).
        If you also need constraint rules, call
        load_recommendation_and_constraint_rules() instead to avoid fetching
        the same rule data twice."""
        rec_rules, _con_rules = self._load_value_rules(workspace_id, catalog_prefix)
        return rec_rules

    def apply_recommendation_rules(
        self,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        rules: list[RecommendationRule],
        bml_eval: BmlEvaluator | None = None,
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
        """
        if not rules:
            return {}
        by_rule_id = self._attr_index(attrs)
        filled_by_rule_id = self._filled_by_rule_id(attrs, filled)
        new_fills: dict[str, tuple[str, str]] = {}
        for rule in rules:
            target = by_rule_id.get(rule.target_attr_id)
            if not target or target.variable_name in filled:
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
                        filled_by_rule_id[rule.condition_attr_id], rule.condition_value
                    ):
                        continue
                recommended_value = rule.recommended_value
            matched_display = next(
                (o.display_name for o in target.options
                 if o.item_value.lower() == recommended_value.lower()),
                recommended_value,
            )
            if _valid(recommended_value):
                new_fills[target.variable_name] = (recommended_value, matched_display)
        if new_fills:
            logger.info("cpq: recommendation rules auto-filled %s", list(new_fills.keys()))
        return new_fills

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
        _rec_rules, con_rules = self._load_value_rules(workspace_id, catalog_prefix)
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
        try:
            scripts = get_cpq_rdb().fetch_function_scripts(workspace_id, catalog_prefix)
        except Exception:  # noqa: BLE001
            logger.debug("cpq: function script fetch failed", exc_info=True)
            scripts = {}
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
    ) -> dict[int, list[str]]:
        """Return {attr_entity_id: [allowed_item_values]} for attrs with active constraints.

        Multiple rules for the same target are intersected (AND semantics) so
        only values permitted by ALL active constraint rules remain valid.

        Script-backed rules (rule.script set) derive their allowed list from
        the BML evaluator using the current filled variables (keyed by
        variable_name — BML scripts compare variable names directly). An
        unknown script outcome (None) applies no constraint rather than
        allowing everything.
        """
        if not rules:
            return {}
        by_rule_id = self._attr_index(attrs)
        filled_by_rule_id = self._filled_by_rule_id(attrs, filled)
        constrained: dict[int, list[str]] = {}

        def _intersect(target_eid: int, allowed: list[str]) -> None:
            if target_eid in constrained:
                existing = set(constrained[target_eid])
                constrained[target_eid] = [v for v in allowed if v in existing]
            else:
                constrained[target_eid] = list(allowed)

        for rule in rules:
            target = by_rule_id.get(rule.target_attr_id)
            if target is None:
                continue
            if rule.script is not None:
                if bml_eval is None:
                    continue
                allowed = bml_eval.allowed_values_for_script(rule.script, filled)
                if allowed:
                    _intersect(target.entity_id, allowed)
                continue
            if rule.condition_script is not None:
                if bml_eval is None:
                    continue
                fires = bml_eval.condition_holds(rule.condition_script, filled)
                if fires is True:
                    _intersect(target.entity_id, rule.allowed_values)
                continue  # False or unknown — never guess, no constraint applied
            if rule.conditions:
                matched, _blocked = evaluate_declarative_conditions(
                    rule.conditions, filled_by_rule_id)
                if matched is not True:
                    continue
            else:
                if rule.condition_attr_id not in filled_by_rule_id:
                    continue
                if not _condition_value_matches(
                    filled_by_rule_id[rule.condition_attr_id], rule.condition_value
                ):
                    continue
            _intersect(target.entity_id, rule.allowed_values)
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

        _visible, _msgs, hidden_vns = self.apply_hiding_rules(attrs, filled, hiding_rules, bml_eval)
        for vn in hidden_vns:
            if filled.get(vn):
                issues.append({
                    "attr": vn, "value": filled[vn], "rule_type": "hiding",
                    "issue": "filled but an active hiding rule matches",
                })

        constrained_opts = self.apply_constraint_rules(attrs, con_rules, filled, bml_eval)
        for vn, value in filled.items():
            attr = by_vn.get(vn)
            allowed = constrained_opts.get(attr.entity_id) if attr else None
            if allowed is not None and value not in allowed:
                issues.append({
                    "attr": vn, "value": value, "rule_type": "constraint",
                    "issue": f"value not in active allowed set {allowed}",
                })

        by_rule_id = self._attr_index(attrs)
        filled_by_rule_id = self._filled_by_rule_id(attrs, filled)
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
                        and _condition_value_matches(current_val, rule.condition_value)
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
    ) -> tuple[list[ConfigAttr], dict[str, str], dict[str, str], dict[int, list[str]]]:
        """Run hide → recommend → constrain → auto-fill until state is stable.

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

        for _ in range(_MAX_LOOPS):
            prev_filled_keys = set(filled.keys())
            prev_visible_ids = {a.entity_id for a in attrs}

            # Apply hiding rules first so auto_fill only fills visible attrs
            attrs, _msgs, hidden_vns = self.apply_hiding_rules(
                attrs, filled, hiding_rules, bml_eval=bml_eval)

            # Strip values ONLY for attrs an explicit hiding rule removed from
            # view. Popping everything not currently visible (the old
            # behaviour) also destroyed confirmed answers whose attr merely
            # wasn't part of this load — dropping user data from the payload.
            for k in hidden_vns:
                filled.pop(k, None)
                display_filled.pop(k, None)
                sources.pop(k, None)
                multi.pop(k, None)

            governed_ids = self.governed_target_ids(attrs, hiding_rules, rec_rules, con_rules)
            rule_ids = self.rule_governed_ids(attrs, hiding_rules, rec_rules, con_rules)
            filled, display_filled, _ = self.auto_fill(
                attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
                filled_source=sources, governed_ids=governed_ids,
                already_filled_multi=multi, dropped_multi=dropped,
                rule_governed_ids=rule_ids, country=country, rec_rules=rec_rules,
                negated_vns=negated_vns, skip_always_ask=skip_always_ask,
            )

            new_fills = self.apply_recommendation_rules(attrs, filled, rec_rules, bml_eval=bml_eval)
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
                    sources.setdefault(k, "rule")

            constrained_opts = self.apply_constraint_rules(
                attrs, con_rules, filled, bml_eval=bml_eval,
            )

            if (set(filled.keys()) == prev_filled_keys
                    and {a.entity_id for a in attrs} == prev_visible_ids):
                break

        return attrs, filled, display_filled, constrained_opts

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
    def derive_region(country: str, attr: ConfigAttr) -> tuple[str, str] | None:
        """Resolve a region attr's value from a known country, without
        inventing a code the catalog doesn't actually offer.

        Looks up `country` in `_COUNTRY_TO_REGION` for a standard region
        abbreviation, then matches that abbreviation against `attr`'s real
        menu options (exact item_value first, then display_name) — a
        country with no mapping, or a catalog whose Region attr doesn't
        offer the derived code, returns None so the caller falls back to
        asking rather than guessing.
        """
        if not country:
            return None
        region_code = _COUNTRY_TO_REGION.get(country.strip().lower())
        if not region_code:
            return None
        for opt in attr.options:
            if opt.item_value.upper() == region_code:
                return opt.item_value, opt.display_name
        for opt in attr.options:
            if region_code in opt.display_name.upper():
                return opt.item_value, opt.display_name
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
    ) -> tuple[dict[str, str], dict[str, str], list[ConfigAttr]]:
        """Auto-fill attributes. Never assigns None/null/empty values.

        Priority order (first match wins):
          1. Already filled in a prior turn.
          2. User-stated value matched from NL hints.
          3. Valid default_value from XML (not None/null/0).
          4. Rule-governed default-or-first (D2/§3) — only for attrs in
             `governed_ids`; everything else falls through to (5). Before
             falling to "first by order", checks whether `rec_rules` has a
             recommendation targeting this exact attr whose condition is
             ALREADY satisfied by the current `filled` state — if so, uses
             that value instead. Without this check, a rule-governed attr
             whose real recommendation condition happens to already be true
             this same pass still got the blind first-option pick here
             (this method runs before `apply_recommendation_rules()` in
             `evaluate_rules_loop`), permanently locking in the wrong value
             since neither mechanism revisits an attr already in `filled`
             (confirmed live: hWVersion_astro's region=NA recommendation
             never fired because first-by-order claimed it first).
          5. First eligible item_value by order_number, but ONLY when exactly
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
          - multi: the allowed set from an active constraint rule IS the
            selected set (written to the returned filled_multi); with no
            active constraint and no default, left unselected — auto-picking
            several options with nothing to justify the choice is the same
            guessing risk D2 exists to prevent.

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

        # Selectors resolve_array_grid_links() confirmed drive a real
        # quantity attr (e.g. mountingTypeArray_viSoln -> the 6 mounting-
        # type quantities) are NOT cosmetic optional checkboxes even though
        # required="0" — silently defaulting them to empty would silently
        # skip a real BOM decision (docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_
        # GRID_PLAN.md §5). Excluded from the optional-multi-select
        # auto-empty branch below so they're asked like any other real
        # question instead; every other optional multi-select is unaffected.
        grid_selector_vns = set(self.resolve_array_grid_links(attrs).keys())

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

            if vn in filled:
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
                    # Priority 4: country full-name → abbreviation shorthand.
                    # Only for the "country" hint key — a full country name
                    # can never substring-match a shorter code-only option
                    # (chargerCountryPlug_apcr's "US", not "United States").
                    if not value and hint_key == "country":
                        for code in _COUNTRY_HINT_SHORTHAND.get(hv_lower, ()):
                            for opt in attr.options:
                                if opt.item_value.upper() == code or opt.display_name.upper() == code:
                                    value = opt.item_value
                                    display = opt.display_name
                                    break
                            if value:
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

            # 2. Default value (pointer-defaults excluded — see
            # _is_pointer_default above; the post-pass resolves them)
            if not value and _valid(attr.default_value) and not _is_pointer_default(attr):
                value = attr.default_value
                source = "default"
                display = next(
                    (o.display_name for o in attr.options
                     if o.item_value == attr.default_value),
                    attr.default_value,
                )
            elif (not value and attr.select_type == "boolean"
                    and attr.default_value.strip().lower() in ("true", "false")):
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
                if len(valid_opts) == 1:
                    # Exactly one choice — auto-fill, no user decision needed
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
                        # The allowed set from an active constraint IS the
                        # selected set — never guess a subset with nothing
                        # to justify it (allowed_for_attr is None → no
                        # active constraint narrowed this attr → leave
                        # unselected, ask the user).
                        if allowed_for_attr is not None:
                            filled_multi[vn] = [o.item_value for o in valid_opts]
                            display_filled[vn] = ", ".join(o.display_name for o in valid_opts)
                            sources.setdefault(vn, governed_source)
                            filled_multi_now = True
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
                        rec_value = rec_display = None
                        for aid_key in (attr.entity_id, attr.source_id):
                            if aid_key is None or rec_value:
                                continue
                            for rrule in rec_by_target.get(aid_key, []):
                                cond_attr = attr_by_rule_id.get(rrule.condition_attr_id)
                                if not cond_attr:
                                    continue
                                cond_val = filled.get(cond_attr.variable_name)
                                if (cond_val is not None
                                        and _condition_value_matches(cond_val, rrule.condition_value)):
                                    match = next(
                                        (o for o in valid_opts
                                         if o.item_value.lower() == rrule.recommended_value.lower()),
                                        None,
                                    )
                                    if match:
                                        rec_value, rec_display = match.item_value, match.display_name
                                        break
                        if rec_value:
                            value, display, source = rec_value, rec_display, "rule"
                        else:
                            # single/boolean, 2+ options, no default: first by
                            # menu order — well-defined for boolean (only two
                            # states) and safe here because a rule REQUIRES this
                            # attr to be resolved for the cascade to proceed.
                            value = valid_opts[0].item_value
                            display = valid_opts[0].display_name
                            source = governed_source
                # else: 0 or 2+ options, ungoverned → pending (user must choose)
            elif not value and is_governed and not is_decision_attr and attr.select_type == "boolean":
                # Governed boolean with no menu options at all: default to
                # "false" (unchecked) rather than leaving it perpetually
                # pending — a boolean's absent-default state is well-defined.
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
            elif (
                attr.select_type == "multi" and not attr.required
                and vn not in grid_selector_vns
            ):
                # An unconstrained multi-select (no active constraint narrowed
                # it, no single-remaining-option, not marked required=1 in
                # the raw XML) reaches here with nothing that justifies
                # picking any subset — but real Oracle CPQ UI behavior for an
                # optional checkbox-list field is an empty selection, not a
                # forced choice (confirmed against raw XML: every attr this
                # applies to in practice has required="0", and their BML
                # scripts only narrow/disallow values under OTHER conditions,
                # never enforce a minimum-selection count). Auto-assign empty
                # rather than asking — a required=1 multi-select still falls
                # through to the pending branch below instead. Grid-linked
                # selectors (vn in grid_selector_vns) are excluded from this
                # branch — see grid_selector_vns comment above.
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
                (attr.options or is_decision_attr)
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

        # Sort pending: hwversion first (Level 1 anchor per spec Step 2),
        # then other decision-required attrs (country, region), then the rest.
        _LEVEL1_KEY = "hwversion"
        hw_pending = [
            a for a in pending
            if _LEVEL1_KEY in a.variable_name.lower().replace("_", "")
        ]
        decision_pending = [
            a for a in pending
            if a not in hw_pending
            and any(dk in a.variable_name.lower().replace("_", "") for dk in _DECISION_REQUIRED_KEYS)
        ]
        other_pending = [
            a for a in pending if a not in hw_pending and a not in decision_pending
        ]
        pending = hw_pending + decision_pending + other_pending

        return filled, display_filled, pending

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
        r"^(yes|confirm(?:ed)?|approve(?:d)?|submit|finali[sz]e|"
        r"looks?\s+good|that'?s?\s+(correct|right|good|it)|go\s+ahead|"
        r"proceed|ok(?:ay)?|all\s+good|perfect|great|send\s+it|let'?s?\s+go)\b",
        re.IGNORECASE,
    )

    # Q&A intent signals — user is asking a question, not answering a config prompt
    _QA_INTENT_RE = re.compile(
        r"^(what|why|how|explain|tell\s+me|describe|what'?s?\s*(is|are)?|"
        r"difference\s+between|compare|which\s+is\s+(better|best)|"
        r"can\s+you\s+explain|why\s+can'?t|how\s+does|how\s+do)",
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

    def detect_approval(self, question: str) -> bool:
        """True when the user is approving/confirming the configuration (Step 8)."""
        return bool(self._APPROVAL_RE.search(question.strip()))

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
        """
        q_lower = question.lower()
        has_change_verb = bool(self._CHANGE_VERB_RE.search(question))
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

        # Try each filled attr — find one where the user's message implies a different value
        for attr in attrs:
            if attr.variable_name not in filled and attr.variable_name not in multi:
                continue
            vn_flat = attr.variable_name.lower().replace("_", "")
            label_lower = attr.display_label.lower()

            # When a change verb is present, require the attr to be mentioned by name/label
            if (
                has_change_verb
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
                    return attr, question
                continue
            if attr.options:
                result = self.apply_answer(attr, question)
                if result and _valid(result[0]) and result[0] != filled.get(attr.variable_name):
                    return attr, question
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
                     or re.search(r"\bfrom\s+(-?\d+(?:\.\d+)?)", search_text, re.IGNORECASE))
                value = m.group(1) if m else None
                if value is None:
                    m2 = re.search(r"-?\d+(?:\.\d+)?", search_text)
                    value = m2.group(0) if m2 else None
                if value is not None and value != filled.get(attr.variable_name, ""):
                    return attr, value

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
                        return attr, question

        return None

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
        distinct_vns = {a.variable_name for a in label_matches}
        if len(distinct_vns) >= 2:
            return label_matches
        return None

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

    # ── Next question ─────────────────────────────────────────────────────────

    def next_question_prompt(
        self,
        attr: ConfigAttr,
        context_sentence: str = "",
        constrained_item_values: list[str] | None = None,
    ) -> str:
        """Build the hybrid question shown to the sales rep for one pending attr.

        context_sentence — explains WHY this attr is being asked based on rules
          (e.g. "Since 5G was selected, we now need a compatible antenna.").
        constrained_item_values — when active constraint rules apply, only these
          item_values are presented in the numbered list.
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
            return f"{ctx_prefix}**{attr.display_label}** — choose one:\n\n{numbered}"
        return f"{ctx_prefix}**{attr.display_label}**\n\nPlease provide a value."

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

    def build_payload(
        self,
        filled: dict[str, str],
        filled_source: dict[str, str] | None = None,
        filled_multi: dict[str, list[str]] | None = None,
        attrs: list["ConfigAttr"] | None = None,
        hidden_vns: set[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Return the final CPQ BOM API payload as ``{"configData": {...}}``.

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
        """
        sources = filled_source or {}
        attr_by_vn = {a.variable_name: a for a in (attrs or [])}
        out: dict[str, Any] = {}
        hidden = hidden_vns or set()
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
            attr = attr_by_vn.get(k)
            if attr is not None and attr.hide_in_trans:
                continue
            if attr is not None and attr.is_array_control:
                # is_array_control_attr=1 (e.g. mountingArrayControl_viSoln)
                # is BigMachines-internal array-size scaffolding, hidden=1 in
                # the raw XML and never surfaced by the native UI. Its value
                # has no real connection to the answered per-row quantity —
                # that's captured separately by resolve_pending_grid_quantities
                # (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 3) — so shipping it
                # would only ever be a coincidental, disconnected number.
                continue
            if attr is not None and attr.set_type == "2":
                # Transient UI/action-layer attr (see ConfigAttr.set_type) —
                # confirmed live: the real CPQ API rejects every one of
                # these with "has an invalid payload" (SVX model-selection
                # panel: modelSelectionSelectModel/archeType/serviceType/
                # dMSDuration_viSoln), same treatment as hide_in_trans.
                # They still drive rules and conversation — only the POST
                # excludes them.
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
        for k, vals in (filled_multi or {}).items():
            if k in hidden or not vals or self._is_noise_var(k):
                continue
            attr = attr_by_vn.get(k)
            if attr is not None and attr.hide_in_trans:
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
        # Present in the same order the XML/graph itself defines
        # (bm_config_attr.order_number, loaded into ConfigAttr.order) rather
        # than insertion order from auto_fill's hint/default/rule/fallback
        # passes — the two are unrelated, and callers cross-checking the
        # payload against the raw catalog expect the catalog's own order.
        # Keys with no matching ConfigAttr (e.g. hidddenRecordSeparator_allFamilly)
        # keep their original relative position, sorted after every real attr.
        ordered = sorted(
            out.items(),
            key=lambda kv: (attr_by_vn[kv[0]].order if kv[0] in attr_by_vn else 10**9),
        )
        return {"configData": dict(ordered)}

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
    ) -> list[tuple[str, str, str]]:
        """Filtered (variable_name, display_label, value) triples worth
        summarising — same filtering as filled_summary_pairs, but keeps
        variable_name so callers (render_filled_summary's category
        grouping) can pattern-match on it. See filled_summary_pairs for the
        filtering rules this applies.
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
            ]
        return [(var, label_map.get(var, var), label) for var, label in items]

    def filled_summary_pairs(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
        sources: dict[str, str] | None = None,
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
                display_filled, attrs, rule_governed_ids, sources)
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
    ) -> str:
        """Deterministic, categorized summary of what has been auto-filled.

        Groups `filled_summary_pairs()` (which owns ALL the filtering) under
        4 scannable headed sections — Product Name, Service Plan, Quantity
        & Duration, Associated Options — instead of one flat bullet list,
        classified purely by variable_name fragment (`_summary_category`,
        generic across any ingested catalog, never a per-catalog literal).
        Used directly as the fallback whenever the LLM-narrated paragraph
        (ask_api `_cpq_summary_text`) is unavailable or fails.
        """
        groups = self.categorized_summary_groups(display_filled, attrs, rule_governed_ids, sources)
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
    ) -> list[tuple[str, list[tuple[str, str]]]]:
        """(category, [(label, value), ...]) groups, non-empty categories
        only, in the fixed display order (Product Name, Service Plan,
        Quantity & Duration, Associated Options — see
        _SUMMARY_CATEGORY_KEYS). Same filtering and classification
        `render_filled_summary` uses for its bullet output; exposed
        separately so callers that build their own presentation (e.g.
        ask_api's LLM-narrated summary) can group the same facts the same
        way instead of inventing their own grouping.
        """
        triples = self._filled_summary_triples(display_filled, attrs, rule_governed_ids, sources)
        if not triples:
            return []
        by_category: dict[str, list[tuple[str, str]]] = {}
        for var, label, value in triples:
            by_category.setdefault(self._summary_category(var), []).append((label, value))
        section_order = [c for c, _ in _SUMMARY_CATEGORY_KEYS] + [_SUMMARY_FALLBACK_CATEGORY]
        return [
            (category, by_category[category])
            for category in section_order
            if by_category.get(category)
        ]
