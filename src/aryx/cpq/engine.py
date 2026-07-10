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
from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.rdb import get_cpq_rdb
from aryx.cpq.state import (
    ConfigAttr, ConstraintRule, CpqSession, HidingRule, MenuOption,
    RecommendationRule,
)

logger = logging.getLogger(__name__)

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


# ── CPQ intent detection ───────────────────────────────────────────────────────
_CPQ_TRIGGER = re.compile(
    r"\b(quote|configure|configuration|build.*quote|create.*quote|"
    r"radio|apx|mototrbo|sl3500|dpx|xpr|"
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
    ("hwversion", r"\b5g\b", "5G"),
    ("hwversion", r"\blte\b", "LTE"),
    ("hwversion", r"\b4g\b", "4G"),
    # Specific country shortcuts — passed as-is to word-boundary display matching.
    # Only list codes/aliases the DB display name won't spell out verbatim.
    ("country", r"\b(us|usa|u\.s\.)\b", "United States"),
    ("country", r"\b(uk|u\.k\.)\b", "United Kingdom"),
    # Product line variants — must come BEFORE the generic APX Next pattern so
    # "APX NEXT XE" is never downgraded to the generic "APX Next" hint.
    # Spec rule 3: if user says "APX NEXT XE", map to XE, not Single Band.
    ("product", r"\bapx\s*next\s+xe\b", "APX NEXT XE"),
    ("product", r"\bapx\s*next\s+xn\b", "APX NEXT XN"),
    ("product", r"\bapx\s*next\s*enhanced\b", "APX NEXT Enhanced"),
    # Generic fallback — fires only when no variant keyword was present
    ("product", r"\bapx\s*next\b", "APX Next"),
    ("product", r"\bapx\s+n\d+\b", "APX Next"),
    ("product", r"\bsl\s*3500\b", "SL3500e"),
]

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

# Product name extraction patterns for display
_PRODUCT_PATTERNS: list[tuple[str, str]] = [
    (r"\bapx\s*next\s+xe\b", "APX NEXT XE"),
    (r"\bapx\s*next\s+xn\b", "APX NEXT XN"),
    (r"\bapx\s*next\b", "APX NEXT"),
    (r"\bsl\s*3500e?\b", "SL3500e"),
    (r"\bdpx\s*\d+\b", "DPX"),
    (r"\bxpr\s*\d+\b", "XPR"),
    (r"\bmototrbo\b", "MOTOTRBO"),
]

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

    Confirmed derivation (CPQ_CASCADE_CONVERSATION_PLAN.md §4), verified
    against the full real config-attr population of the reference sample
    (all 15 attrs: is_array_control_attr uniformly "0", data_type uniformly
    "1", display_type never "10" in that export — so this classifier is
    logic-confirmed but not yet exercised end-to-end on a real multi/boolean
    example; treat those two branches as higher-risk until one does).

    Priority matters: array-control checked first, then the boolean pair,
    else default to "single" — dropdowns (display_type=="3") and any other
    shape (free-text, etc.) both fall through to "single" safely.
    """
    if str(attrs.get("is_array_control_attr", "")).strip() == "1":
        return "multi"
    if (str(attrs.get("display_type", "")).strip() == "10"
            or str(attrs.get("data_type", "")).strip() == "4"):
        return "boolean"
    return "single"


class CpqEngine:
    """Drives guided CPQ configuration within the Ask conversation."""

    # Maximum turns before declaring complete (even if attrs remain)
    MAX_TURNS: int = 5

    # ── Intent detection ──────────────────────────────────────────────────────

    def is_cpq_question(self, question: str) -> bool:
        """True when the question is a CPQ configuration / quote request."""
        return bool(_CPQ_TRIGGER.search(question))

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

    def detect_product_mention(self, question: str, hints: dict[str, str]) -> str:
        """Best-effort product display label from NL text, or "" if none found.

        D1 (CPQ_CASCADE_CONVERSATION_PLAN.md §2): the anchor gate is now
        sequential (product, then country) rather than a single-shot block
        requiring product+line+country together — hwVersion (formerly the
        "product line" anchor) resolves through the normal rule cascade
        instead, like any other dependent variable.
        """
        q_lower = question.lower()
        return next(
            (label for pattern, label in _PRODUCT_PATTERNS
             if re.search(pattern, q_lower, re.IGNORECASE)),
            next((v for k, v in hints.items() if "product" in k), ""),
        )

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
                menu_ids = [
                    n["id"] for n in neighbors
                    if "menuitem" in (n.get("type") or "").lower().replace("_", "")
                ]
                if menu_ids:
                    neighbor_map[eid] = menu_ids
                    all_menu_ids.extend(menu_ids)
            except Exception:
                logger.debug("cpq: neighbor fetch failed for attr %d", eid, exc_info=True)

        # Single batch fetch for all menu items across all attrs
        all_menu_pg = self._batch_fetch(all_menu_ids, workspace_id) if all_menu_ids else {}

        menu_by_attr: dict[int, list[MenuOption]] = {}
        for eid, menu_ids in neighbor_map.items():
            opts: list[MenuOption] = []
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

            hidden_raw = str(pg.get("hidden") or "0").strip().lower()
            if hidden_raw in ("1", "true", "yes"):
                continue  # hidden attributes are never shown or auto-filled

            display = str(pg.get("name") or ent.get("name") or var_name).strip()
            required_raw = str(pg.get("required") or "0").strip().lower()
            required = required_raw in ("1", "true", "yes")
            default_val = str(pg.get("default_value") or "").strip()
            order = int(pg.get("order_number") or pg.get("order") or 999)

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
            ))

        config_attrs.sort(key=lambda a: a.order)
        return config_attrs, product_hint

    # ── Rule loaders (dialect-agnostic via cpq.rdb) ──────────────────────────

    def _load_rule_join_data(self, workspace_id: int):
        """Shared fetch for the rule loaders.

        BmConfigRuleInput/Action rows reference their rule by the BM-native
        rule id (``bm_config_rule_id`` from the source XML), NOT by the aryx
        entity id — the join key is the rule entity's own attrs ``id``.
        Returns (rdb, inputs_by_rule, actions_by_rule, marked_by_rule,
        chain_by_rule).
        """
        rdb = get_cpq_rdb()
        inputs_by_rule: dict[int, tuple[int, str]] = {}
        for rid, aid, val in rdb.fetch_rule_inputs(workspace_id):
            inputs_by_rule[rid] = (aid, val)
        actions_by_rule: dict[int, list[tuple[int, int, str, int]]] = {}
        for rid, aid, at, val, fn in rdb.fetch_rule_actions(workspace_id):
            actions_by_rule.setdefault(rid, []).append((aid, at, val, fn))
        # bm_config_marked_attr: the real target linkage for many declarative
        # hiding rules — verified against real data where BmConfigRuleAction
        # and the rule's own attr_id both carry no target (docs/CPQ_GRAPH_FIX_PLAN.md §6a).
        marked_by_rule: dict[int, list[int]] = {}
        for rid, aid in rdb.fetch_marked_attrs(workspace_id):
            marked_by_rule.setdefault(rid, []).append(aid)
        # bm_config_rule_assoc: some rules chain to a child rule rather than
        # declaring their own target; the terminal rule holds the real one.
        chain_by_rule: dict[int, int] = {}
        for rid, cid in rdb.fetch_rule_chain_links(workspace_id):
            chain_by_rule[rid] = cid
        return rdb, inputs_by_rule, actions_by_rule, marked_by_rule, chain_by_rule

    @staticmethod
    def _resolve_targets(
        rule_key: int,
        actions_by_rule: dict[int, list[tuple[int, int, str, int]]],
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
            return [(aid, at) for aid, at, _v, _f in acts]
        marked = marked_by_rule.get(rule_key)
        if marked:
            return [(aid, 2) for aid in marked]
        seen: set[int] = {rule_key}
        current = chain_by_rule.get(rule_key)
        hops = 0
        while current is not None and current not in seen and hops < max_hops:
            acts = actions_by_rule.get(current, [])
            if acts:
                return [(aid, at) for aid, at, _v, _f in acts]
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

    def load_hiding_rules(self, workspace_id: int) -> list[HidingRule]:
        """Load hiding rules (rule_type=11) from the RDB.

        Declarative rules become HidingRule objects. Script-backed rules
        (condition_function_id != -1) cannot be expressed as a simple
        hide/show pair — they are counted and logged (never silently
        dropped) so coverage is visible per workspace.
        """
        rules: list[HidingRule] = []
        script_backed = 0
        unresolved = 0
        try:
            rdb, inputs, actions, marked, chain = self._load_rule_join_data(workspace_id)
            for eid, src_id, rule_name, fn_id in rdb.fetch_rules(workspace_id, "11"):
                if fn_id != -1:
                    script_backed += 1
                    logger.info(
                        "cpq: hiding rule %r is script-backed (function_id=%d) — "
                        "hide/show semantics not derivable from BML, rule visible "
                        "in coverage but not evaluated", rule_name, fn_id)
                    continue
                key = self._rule_key(eid, src_id, inputs, actions)
                inp = inputs.get(key)
                if not inp:
                    unresolved += 1
                    continue
                targets = self._resolve_targets(key, actions, marked, chain)
                if not targets:
                    unresolved += 1
                    logger.info(
                        "cpq: hiding rule %r (id=%s) has a condition but no "
                        "resolvable target via action/marked_attr/chain — "
                        "excluded, not silently guessed", rule_name, key)
                    continue
                cond_attr_id, cond_value = inp
                for target_attr_id, action_type in targets:
                    rules.append(HidingRule(
                        rule_name=rule_name or str(eid),
                        condition_attr_id=cond_attr_id,
                        condition_value=cond_value,
                        target_attr_id=target_attr_id,
                        hide=(int(action_type or 2) == 2),
                    ))
        except Exception:
            logger.debug("cpq: hiding rule load failed", exc_info=True)

        logger.info(
            "cpq: loaded %d declarative hiding rules (%d script-backed logged, "
            "%d unresolved)", len(rules), script_backed, unresolved)
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
    ) -> tuple[list[ConfigAttr], list[str], set[str]]:
        """Apply hiding rules against current filled values.

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
            current_val = filled_by_rule_id.get(rule.condition_attr_id)
            if current_val is None:
                continue  # condition attr not filled yet — rule doesn't fire
            if current_val.lower() == rule.condition_value.lower():
                target = by_rule_id.get(rule.target_attr_id)
                if target:
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

    def load_recommendation_rules(self, workspace_id: int) -> list[RecommendationRule]:
        """Load recommendation rules (rule_type=10) from the RDB.

        When a condition attribute equals a specific value, the engine
        auto-selects the recommended item_value for the target attribute
        without asking the user. Script-backed rules are counted and logged.
        """
        rules: list[RecommendationRule] = []
        script_backed = 0
        try:
            rdb, inputs, actions, _marked, _chain = self._load_rule_join_data(workspace_id)
            for eid, src_id, rule_name, fn_id in rdb.fetch_rules(workspace_id, "10"):
                if fn_id != -1:
                    script_backed += 1
                    logger.info(
                        "cpq: recommendation rule %r is script-backed "
                        "(function_id=%d) — logged, not evaluated", rule_name, fn_id)
                    continue
                key = self._rule_key(eid, src_id, inputs, actions)
                inp = inputs.get(key)
                # action_type=3 → set/recommend; value1 holds the recommended item_value
                act = next(
                    ((aid, val) for aid, at, val, _f in actions.get(key, [])
                     if at == 3 and val),
                    None,
                )
                if inp and act:
                    cond_attr_id, cond_value = inp
                    target_attr_id, rec_val = act
                    rules.append(RecommendationRule(
                        rule_name=rule_name or str(eid),
                        condition_attr_id=cond_attr_id,
                        condition_value=cond_value,
                        target_attr_id=target_attr_id,
                        recommended_value=rec_val,
                    ))
        except Exception:
            logger.debug("cpq: recommendation rule load failed", exc_info=True)
        logger.info("cpq: loaded %d recommendation rules (%d script-backed logged)",
                    len(rules), script_backed)
        return rules

    def apply_recommendation_rules(
        self,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        rules: list[RecommendationRule],
    ) -> dict[str, tuple[str, str]]:
        """Apply recommendation rules. Returns {variable_name: (item_value, display)}.

        Only fills attrs that are not already filled. Does not override prior
        user selections or auto-fills from earlier loop iterations.
        """
        if not rules:
            return {}
        by_rule_id = self._attr_index(attrs)
        filled_by_rule_id = self._filled_by_rule_id(attrs, filled)
        new_fills: dict[str, tuple[str, str]] = {}
        for rule in rules:
            if rule.condition_attr_id not in filled_by_rule_id:
                continue
            if filled_by_rule_id[rule.condition_attr_id].lower() != rule.condition_value.lower():
                continue
            target = by_rule_id.get(rule.target_attr_id)
            if not target or target.variable_name in filled:
                continue
            matched_display = next(
                (o.display_name for o in target.options
                 if o.item_value.lower() == rule.recommended_value.lower()),
                rule.recommended_value,
            )
            if _valid(rule.recommended_value):
                new_fills[target.variable_name] = (rule.recommended_value, matched_display)
        if new_fills:
            logger.info("cpq: recommendation rules auto-filled %s", list(new_fills.keys()))
        return new_fills

    # ── Constraint rule loader ────────────────────────────────────────────────

    def load_constraint_rules(self, workspace_id: int) -> list[ConstraintRule]:
        """Load constraint rules (rule_type=5) from the RDB — declarative AND script.

        Declarative form: when the condition attribute equals condition_value,
        only the listed item_values (action_type=4) remain valid for the
        target attribute. Multiple rules for one target are intersected.

        Script form: actions whose logic lives in a BML function
        (function_id != -1) get the raw script attached; allowed values are
        derived at apply time by the BML evaluator from the current filled
        variables. These rules were previously dropped entirely — the direct
        cause of illegal configurations (e.g. hardware/frequency mismatches).
        """
        rules: list[ConstraintRule] = []
        script_rules = 0
        cond_script_skipped = 0
        try:
            rdb, inputs, actions, _marked, _chain = self._load_rule_join_data(workspace_id)
            scripts = rdb.fetch_function_scripts(workspace_id)
            for eid, src_id, rule_name, fn_id in rdb.fetch_rules(workspace_id, "5"):
                key = self._rule_key(eid, src_id, inputs, actions)
                inp = inputs.get(key)
                acts = actions.get(key, [])

                # Script-backed actions: the BML function returns the allowed
                # list; the script embeds its own conditions on variable names.
                for aid, _at, _val, act_fn in acts:
                    if act_fn != -1:
                        script = scripts.get(act_fn)
                        if script:
                            rules.append(ConstraintRule(
                                rule_name=rule_name or str(eid),
                                condition_attr_id=(inp[0] if inp else 0),
                                condition_value="",
                                target_attr_id=aid,
                                allowed_values=[],
                                script=script,
                            ))
                            script_rules += 1
                        else:
                            logger.warning(
                                "cpq: constraint rule %r references function_id=%d "
                                "but no BmFunction script was found", rule_name, act_fn)

                if fn_id != -1:
                    # Condition itself is a script (boolean BML) — not derivable
                    # by the value-list evaluator; logged for coverage.
                    cond_script_skipped += 1
                    logger.info(
                        "cpq: constraint rule %r has a script condition "
                        "(condition_function_id=%d) — declarative actions for it "
                        "are not gated", rule_name, fn_id)
                    continue

                if not inp:
                    continue
                cond_attr_id, cond_value = inp
                # Declarative include-actions grouped per target attribute
                by_target: dict[int, list[str]] = {}
                for aid, at, val, act_fn in acts:
                    if act_fn == -1 and at == 4 and val:
                        by_target.setdefault(aid, []).append(val)
                for target_attr_id, allowed in by_target.items():
                    rules.append(ConstraintRule(
                        rule_name=rule_name or str(eid),
                        condition_attr_id=cond_attr_id,
                        condition_value=cond_value,
                        target_attr_id=target_attr_id,
                        allowed_values=allowed,
                    ))
        except Exception:
            logger.debug("cpq: constraint rule load failed", exc_info=True)
        logger.info(
            "cpq: loaded %d constraint rules (%d script-backed, %d script-condition logged)",
            len(rules), script_rules, cond_script_skipped)
        return rules

    def build_bml_evaluator(self, workspace_id: int) -> BmlEvaluator:
        """BML evaluator over this workspace's BmFunction scripts."""
        try:
            scripts = get_cpq_rdb().fetch_function_scripts(workspace_id)
        except Exception:  # noqa: BLE001
            logger.debug("cpq: function script fetch failed", exc_info=True)
            scripts = {}
        return BmlEvaluator(scripts)

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
            if rule.condition_attr_id not in filled_by_rule_id:
                continue
            if filled_by_rule_id[rule.condition_attr_id].lower() != rule.condition_value.lower():
                continue
            _intersect(target.entity_id, rule.allowed_values)
        if constrained:
            names = [by_rule_id[eid].variable_name for eid in constrained if eid in by_rule_id]
            logger.info("cpq: constraint rules active for %s", names)
        return constrained

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
            attrs, _msgs, hidden_vns = self.apply_hiding_rules(attrs, filled, hiding_rules)

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
                rule_governed_ids=rule_ids, country=country,
            )

            new_fills = self.apply_recommendation_rules(attrs, filled, rec_rules)
            if new_fills:
                filled.update({k: iv for k, (iv, _d) in new_fills.items()})
                display_filled.update({k: d for k, (_iv, d) in new_fills.items()})
                for k in new_fills:
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
    ) -> tuple[dict[str, str], dict[str, str], list[ConfigAttr]]:
        """Auto-fill attributes. Never assigns None/null/empty values.

        Priority order (first match wins):
          1. Already filled in a prior turn.
          2. User-stated value matched from NL hints.
          3. Valid default_value from XML (not None/null/0).
          4. Rule-governed default-or-first (D2/§3) — only for attrs in
             `governed_ids`; everything else falls through to (5).
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
        """
        filled: dict[str, str] = dict(already_filled or {})
        filled_multi = already_filled_multi if already_filled_multi is not None else {}
        display_filled: dict[str, str] = {}
        pending: list[ConfigAttr] = []
        sources = filled_source if filled_source is not None else {}
        governed = governed_ids or set()
        rule_governed = rule_governed_ids if rule_governed_ids is not None else governed
        dropped = dropped_multi if dropped_multi is not None else {}

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
                    if not value and not attr.options and _valid(hint_val):
                        value = hint_val
                        display = hint_val
                    if value:
                        source = "hint"
                    break

            # 2. Default value
            if not value and _valid(attr.default_value):
                value = attr.default_value
                source = "default"
                display = next(
                    (o.display_name for o in attr.options
                     if o.item_value == attr.default_value),
                    attr.default_value,
                )

            # 3/4. Rule-governed default-or-first (D2/§3), else the
            # conservative single-remaining-option fallback (NO EAGER
            # EVALUATION — Issue 6's "Stop and Wait" safeguard for anything
            # not rule-governed). Decision-required attrs (country/region —
            # hwVersion removed per D1, it's a normal dependent now) always
            # ask regardless of governance.
            is_decision_attr = any(
                dk in vn_flat for dk in _DECISION_REQUIRED_KEYS
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
                elif is_governed and not is_decision_attr and valid_opts:
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
                filled[vn] = value
                display_filled[vn] = display or value
                sources.setdefault(vn, source)
            elif attr.options or is_decision_attr:
                # Attrs with a meaningful choice set OR decision-required free-text
                # attrs (region/country) go to pending for user input.
                # Free-text CRM/system fields with no options and no decision
                # requirement are skipped — they are filled by integration.
                pending.append(attr)

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
        r"\b(swapp?(?:ing)?|chang(?:e|ing)|switch(?:ing)?|replac(?:e|ing)|"
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
    ) -> "tuple[ConfigAttr, str] | None":
        """Detect if the user wants to change an already-filled attribute (Step 6).

        Returns (attr_to_change, new_value_hint) or None if no change detected.
        Strategy: look for change-verb vocabulary first; then fall back to
        checking if the raw message maps to a different value for any filled attr.
        """
        q_lower = question.lower()
        has_change_verb = bool(self._CHANGE_VERB_RE.search(question))

        # Try each filled attr — find one where the user's message implies a different value
        for attr in attrs:
            if attr.variable_name not in filled:
                continue
            vn_flat = attr.variable_name.lower().replace("_", "")
            label_lower = attr.display_label.lower()

            # When a change verb is present, require the attr to be mentioned by name/label
            if has_change_verb and vn_flat not in q_lower.replace("_", "") and label_lower not in q_lower:
                continue

            # Check hint extraction for this attr's key fragment
            hints = self.extract_hints(question)
            for hk, hv in hints.items():
                hk_flat = hk.lower().replace("_", "")
                if hk_flat in vn_flat or vn_flat in hk_flat:
                    if hv.lower() != filled.get(attr.variable_name, "").lower():
                        return attr, hv

            # Direct apply_answer match with a different value.
            # Guard: skip option-less (free-text) attrs — apply_answer's free-text
            # fallback would accept ANY string, turning a raw change-request sentence
            # into a spurious "value" for attrs like CRM_BILL_COUNTRY.
            if attr.options:
                result = self.apply_answer(attr, question)
                if result and _valid(result[0]) and result[0] != filled.get(attr.variable_name):
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

    def detect_attr_query(
        self, question: str, attrs: list[ConfigAttr],
    ) -> ConfigAttr | None:
        """If the question asks about options for a specific attribute, return it.

        Detection: question contains an attribute's variable_name AND any
        option-query keyword. Reads options from already-loaded attrs — no DB
        call, no hardcoding.
        """
        q_lower = question.lower()
        has_options_keyword = any(kw in q_lower for kw in self._OPTIONS_KEYWORDS)
        if not has_options_keyword:
            return None
        # Match by variable_name (case-insensitive, underscore-tolerant)
        for attr in attrs:
            vn_flat = attr.variable_name.lower().replace("_", "")
            if vn_flat in q_lower.replace("_", "") or attr.variable_name.lower() in q_lower:
                return attr
        # Fallback: match by display_label
        for attr in attrs:
            if attr.display_label.lower() in q_lower:
                return attr
        return None

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
    ) -> dict[str, str | list[str]]:
        """Return the final CPQ BOM API payload {variable_name: item_value}.

        Excludes HTML template values — those are layout/display fields, not
        real configuration inputs for the BOM API. A value confirmed by the
        user against a real menu option is valid BY DEFINITION: none-like
        codes (``NA``, ``0``, ...) survive when their provenance is a
        confirmed source; only unconfirmed auto-fills are dropped.

        filled_multi (select_type=="multi" attrs) merges in as JSON arrays —
        CpqSession.filled stays str-only (CPQ_CASCADE_CONVERSATION_PLAN.md §4).
        """
        sources = filled_source or {}
        out: dict[str, str | list[str]] = {}
        for k, v in filled.items():
            if not v or self._is_html_value(v):
                continue
            if _valid(v) or sources.get(k) in self._CONFIRMED_SOURCES:
                out[k] = v
        for k, vals in (filled_multi or {}).items():
            if vals:
                out[k] = list(vals)
        return out

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
        attr: "ConfigAttr | None",
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
        label_l = display_label.lower()
        if "secondary" in label_l:
            return True
        if "warranty" in label_l or "warranty" in value.lower():
            return True
        return "product" in label_l or "product" in variable_name.lower()

    def filled_summary_pairs(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
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
        if not display_filled:
            return []
        by_vn: dict[str, "ConfigAttr"] = {a.variable_name: a for a in attrs} if attrs else {}
        label_map: dict[str, str] = {vn: a.display_label for vn, a in by_vn.items()}
        items = [
            (var, label) for var, label in display_filled.items()
            if not self._is_html_value(label)
            and not self._is_noise_var(var)
            and not self._is_summary_excluded(var, label_map.get(var, var), label, by_vn.get(var))
        ]
        if rule_governed_ids is not None:
            items = [
                (var, label) for var, label in items
                if (attr := by_vn.get(var)) and attr.entity_id in rule_governed_ids
            ]
        return [(label_map.get(var, var), label) for var, label in items]

    def render_filled_summary(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
        rule_governed_ids: set[int] | None = None,
    ) -> str:
        """Deterministic bullet-list summary of what has been auto-filled.

        Formats `filled_summary_pairs()` (which owns ALL the filtering) as
        markdown bullets. Used directly as the fallback whenever the
        LLM-narrated paragraph (ask_api `_cpq_summary_text`) is
        unavailable or fails.
        """
        pairs = self.filled_summary_pairs(display_filled, attrs, rule_governed_ids)
        if not pairs:
            return ""
        heading = "**Configured so far:**" if rule_governed_ids is None else "**Key decisions:**"
        return "\n".join([heading, *(f"- **{label}** → {value}" for label, value in pairs)])
