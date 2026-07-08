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
from aryx.cpq.state import (
    ConfigAttr, ConstraintRule, CpqSession, HidingRule, MenuOption,
    RecommendationRule,
)
from aryx.store.pool import get_pool

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
    # attr_key_fragment is matched word-by-word against the attribute's variable_name
    ("hwversion", r"\b5g\b", "5G"),
    ("hwversion", r"\blte\b", "LTE"),
    ("hwversion", r"\b4g\b", "4G"),
    # Specific country shortcuts — passed as-is to word-boundary display matching.
    # Only list codes/aliases the DB display name won't spell out verbatim.
    ("country", r"\b(us|usa|u\.s\.)\b", "United States"),
    ("country", r"\b(uk|u\.k\.)\b", "United Kingdom"),
    # Product name hints
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

# Attr key fragments that represent "decision-required" choices — never auto-fill
# via first-option fallback. Only filled via explicit hint or valid default_value.
_DECISION_REQUIRED_KEYS: frozenset[str] = frozenset({
    "hwversion", "country", "region",
})

# Public alias so ask_api can access it without importing a private name.
DECISION_REQUIRED_KEYS = _DECISION_REQUIRED_KEYS

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

# ── Anchor extraction ─────────────────────────────────────────────────────────
# Step 1: the 3 mandatory independent attributes that must be present in the
# user's NL request before the CPQ configuration loop can begin. Without a
# known product family and destination country the graph query is underdetermined.
_ANCHOR_PRODUCT_RE = re.compile(
    r"\b(apx\s*next|mototrbo|sl\s*3500e?|dpx\s*\d+|xpr\s*\d+)\b",
    re.IGNORECASE,
)
# Product-line variant keywords (XE / XN / SINGLE / ENHANCED) — when present,
# resolved from NL; when absent, resolved through Step 4 config flow from DB options.
_ANCHOR_LINE_RE = re.compile(
    r"\b(xe|xn|single|enhanced)\b",
    re.IGNORECASE,
)

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

        # Specific shortcut patterns (abbreviations/codes the DB won't spell out)
        for key, pattern, value in _HINT_PATTERNS:
            if re.search(pattern, question, re.IGNORECASE):
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

    def validate_anchors(
        self, question: str, hints: dict[str, str],
    ) -> list[str]:
        """Return labels of missing mandatory anchors, or [] if all present.

        Step 1 guard: blocks the CPQ config loop until all three anchors are
        extractable — product_family, product_line, and ultimate_destination_country.
        product_line (XE / XN / Single / Enhanced) must be stated up front so the
        correct model variant is loaded from the graph before any rule evaluation.
        """
        missing: list[str] = []
        if not _ANCHOR_PRODUCT_RE.search(question):
            missing.append(
                "the **product family** (e.g., *APX Next*, *MOTOTRBO*, *SL3500e*)"
            )
        if not _ANCHOR_LINE_RE.search(question):
            missing.append(
                "the **product line** (e.g., *XE*, *XN*, *Single*, *Enhanced*)"
            )
        if "country" not in hints:
            missing.append(
                "the **destination country** (e.g., *United States*, *Canada*, *Germany*)"
            )
        return missing

    # ── PostgreSQL attribute fetch ────────────────────────────────────────────

    def _batch_fetch(
        self, entity_ids: list[int], workspace_id: int,
    ) -> dict[int, dict[str, Any]]:
        """Batch-fetch entity attribute JSON from PostgreSQL."""
        if not entity_ids:
            return {}
        result: dict[int, dict[str, Any]] = {}
        try:
            with get_pool(get_settings().rdb_dsn).connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, attributes FROM aryx_entity "
                        "WHERE id = ANY(%s) AND workspace_id = %s",
                        (entity_ids, workspace_id),
                    )
                    for row in cur.fetchall():
                        eid, attrs = row
                        if isinstance(attrs, str):
                            attrs = json.loads(attrs)
                        result[int(eid)] = attrs or {}
        except Exception:
            logger.debug("cpq batch-fetch failed", exc_info=True)
        return result

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
        # Step 1 — find config attr entities (XML ingestion produces CamelCase types)
        attr_ents = reader.find_entities(ontology_type="BmConfigAttr", limit=500)
        if not attr_ents:
            # Fallback: snake_case or any type containing "attr"
            attr_ents = reader.find_entities(ontology_type="bm_config_attr", limit=500)
        if not attr_ents:
            attr_ents = [
                e for e in reader.find_entities(limit=1000)
                if "configattr" in (e.get("type") or "").lower().replace("_", "")
                and not self._is_layout_noise(e.get("type") or "")
            ]

        if not attr_ents:
            logger.info("cpq: no bm_config_attr entities found in graph")
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

            config_attrs.append(ConfigAttr(
                entity_id=eid,
                variable_name=var_name,
                display_label=display,
                required=required,
                default_value=default_val,
                options=menu_by_attr.get(eid, []),
                order=order,
            ))

        config_attrs.sort(key=lambda a: a.order)
        return config_attrs, product_hint

    # ── Hiding rule loader ────────────────────────────────────────────────────

    def load_hiding_rules(self, workspace_id: int) -> list[HidingRule]:
        """Load declarative hiding rules (rule_type=11, condition_type=1) from PostgreSQL.

        Only simple rules with BmConfigRuleInput records are loaded — script-based
        rules (condition_function_id != -1) require a BML evaluator and are skipped.

        Returns a list of HidingRule objects. Empty if none found or on error.
        """
        rules: list[HidingRule] = []
        try:
            with get_pool(get_settings().rdb_dsn).connection() as conn:
                with conn.cursor() as cur:
                    # Step 1: get simple hiding rules
                    cur.execute(
                        """
                        SELECT id,
                               attributes->>'name'              AS rule_name,
                               (attributes->>'condition_function_id')::int AS fn_id
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND ontology_type = 'BmConfigRule'
                          AND (attributes->>'rule_type') = '11'
                        """,
                        (workspace_id,),
                    )
                    simple_rules = {
                        row[0]: row[1]
                        for row in cur.fetchall()
                        if row[2] == -1  # no function → declarative only
                    }

                    if not simple_rules:
                        return rules

                    # Step 2: get BmConfigRuleInput for these rules
                    cur.execute(
                        """
                        SELECT
                            (attributes->>'bm_config_rule_id')::bigint  AS rule_id,
                            (attributes->>'attribute_id')::bigint        AS cond_attr_id,
                            attributes->>'value1'                        AS cond_value
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND ontology_type = 'BmConfigRuleInput'
                        """,
                        (workspace_id,),
                    )
                    inputs: dict[int, tuple[int, str]] = {}
                    for rule_id, cond_attr_id, cond_value in cur.fetchall():
                        if rule_id and cond_attr_id:
                            inputs[int(rule_id)] = (int(cond_attr_id), cond_value or "")

                    # Step 3: get BmConfigRuleAction for these rules (target attr + action)
                    cur.execute(
                        """
                        SELECT
                            (attributes->>'bm_config_rule_id')::bigint AS rule_id,
                            (attributes->>'attribute_id')::bigint       AS target_attr_id,
                            (attributes->>'action_type')::int           AS action_type
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND ontology_type = 'BmConfigRuleAction'
                        """,
                        (workspace_id,),
                    )
                    actions: dict[int, tuple[int, int]] = {}
                    for rule_id, target_attr_id, action_type in cur.fetchall():
                        if rule_id and target_attr_id:
                            # action_type=2 → hide; action_type=1 → show
                            actions[int(rule_id)] = (int(target_attr_id), int(action_type or 2))

                    # Step 4: join inputs + actions to build HidingRule objects
                    for rule_entity_id, rule_name in simple_rules.items():
                        inp = inputs.get(rule_entity_id)
                        act = actions.get(rule_entity_id)
                        if inp and act:
                            cond_attr_id, cond_value = inp
                            target_attr_id, action_type = act
                            rules.append(HidingRule(
                                rule_name=rule_name or str(rule_entity_id),
                                condition_attr_id=cond_attr_id,
                                condition_value=cond_value,
                                target_attr_id=target_attr_id,
                                hide=(action_type == 2),
                            ))
        except Exception:
            logger.debug("cpq: hiding rule load failed", exc_info=True)

        logger.info("cpq: loaded %d declarative hiding rules", len(rules))
        return rules

    def apply_hiding_rules(
        self,
        attrs: list[ConfigAttr],
        filled: dict[str, str],
        rules: list[HidingRule],
    ) -> tuple[list[ConfigAttr], list[str]]:
        """Apply hiding rules against current filled values.

        Returns:
          filtered_attrs — attrs still visible after rules are applied
          rule_messages  — human-readable list of rules that fired (for reporting)
        """
        if not rules:
            return attrs, []

        # Build entity_id → ConfigAttr map for fast lookup
        by_eid: dict[int, ConfigAttr] = {a.entity_id: a for a in attrs}
        # Build variable_name → filled_value for condition evaluation
        filled_by_eid: dict[int, str] = {}
        for attr in attrs:
            if attr.variable_name in filled:
                filled_by_eid[attr.entity_id] = filled[attr.variable_name]

        hidden_eids: set[int] = set()
        messages: list[str] = []

        for rule in rules:
            current_val = filled_by_eid.get(rule.condition_attr_id)
            if current_val is None:
                continue  # condition attr not filled yet — rule doesn't fire
            if current_val.lower() == rule.condition_value.lower():
                target = by_eid.get(rule.target_attr_id)
                if target:
                    if rule.hide:
                        hidden_eids.add(rule.target_attr_id)
                        messages.append(
                            f"*Rule '{rule.rule_name}' hid **{target.display_label}***"
                        )
                    else:
                        hidden_eids.discard(rule.target_attr_id)

        filtered = [a for a in attrs if a.entity_id not in hidden_eids]
        return filtered, messages

    # ── Recommendation rule loader ────────────────────────────────────────────

    def load_recommendation_rules(self, workspace_id: int) -> list[RecommendationRule]:
        """Load declarative recommendation rules (rule_type=10) from PostgreSQL.

        When a condition attribute equals a specific value, the engine
        auto-selects the recommended item_value for the target attribute
        without asking the user. Only declarative rules (condition_function_id=-1)
        are loaded; BML-script rules are skipped.
        """
        rules: list[RecommendationRule] = []
        try:
            with get_pool(get_settings().rdb_dsn).connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, attributes->>'name'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND ontology_type = 'BmConfigRule'
                          AND (attributes->>'rule_type') = '10'
                          AND (attributes->>'condition_function_id')::int = -1
                        """,
                        (workspace_id,),
                    )
                    simple_rules = {row[0]: row[1] for row in cur.fetchall()}
                    if not simple_rules:
                        logger.debug("cpq: no declarative recommendation rules found")
                        return rules

                    cur.execute(
                        """
                        SELECT
                            (attributes->>'bm_config_rule_id')::bigint AS rule_id,
                            (attributes->>'attribute_id')::bigint       AS cond_attr_id,
                            attributes->>'value1'                       AS cond_value
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND ontology_type = 'BmConfigRuleInput'
                        """,
                        (workspace_id,),
                    )
                    inputs: dict[int, tuple[int, str]] = {}
                    for rule_id, cond_attr_id, cond_value in cur.fetchall():
                        if rule_id and cond_attr_id:
                            inputs[int(rule_id)] = (int(cond_attr_id), cond_value or "")

                    # action_type=3 → set/recommend; value1 holds the recommended item_value
                    cur.execute(
                        """
                        SELECT
                            (attributes->>'bm_config_rule_id')::bigint AS rule_id,
                            (attributes->>'attribute_id')::bigint       AS target_attr_id,
                            attributes->>'value1'                       AS recommended_value
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND ontology_type = 'BmConfigRuleAction'
                          AND (attributes->>'action_type') = '3'
                        """,
                        (workspace_id,),
                    )
                    actions: dict[int, tuple[int, str]] = {}
                    for rule_id, target_attr_id, rec_val in cur.fetchall():
                        if rule_id and target_attr_id and rec_val:
                            actions[int(rule_id)] = (int(target_attr_id), rec_val)

                    for rule_entity_id, rule_name in simple_rules.items():
                        inp = inputs.get(rule_entity_id)
                        act = actions.get(rule_entity_id)
                        if inp and act:
                            cond_attr_id, cond_value = inp
                            target_attr_id, rec_val = act
                            rules.append(RecommendationRule(
                                rule_name=rule_name or str(rule_entity_id),
                                condition_attr_id=cond_attr_id,
                                condition_value=cond_value,
                                target_attr_id=target_attr_id,
                                recommended_value=rec_val,
                            ))
        except Exception:
            logger.debug("cpq: recommendation rule load failed", exc_info=True)
        logger.info("cpq: loaded %d recommendation rules", len(rules))
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
        by_eid: dict[int, ConfigAttr] = {a.entity_id: a for a in attrs}
        filled_by_eid: dict[int, str] = {
            a.entity_id: filled[a.variable_name]
            for a in attrs if a.variable_name in filled
        }
        new_fills: dict[str, tuple[str, str]] = {}
        for rule in rules:
            if rule.condition_attr_id not in filled_by_eid:
                continue
            if filled_by_eid[rule.condition_attr_id].lower() != rule.condition_value.lower():
                continue
            target = by_eid.get(rule.target_attr_id)
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
        """Load declarative constraint rules (rule_type=5) from PostgreSQL.

        When a condition attribute equals a specific value, only the listed
        item_values remain valid for the target attribute. Multiple rules for
        the same target are intersected. Only declarative rules are loaded.
        """
        rules: list[ConstraintRule] = []
        try:
            with get_pool(get_settings().rdb_dsn).connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, attributes->>'name'
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND ontology_type = 'BmConfigRule'
                          AND (attributes->>'rule_type') = '5'
                          AND (attributes->>'condition_function_id')::int = -1
                        """,
                        (workspace_id,),
                    )
                    simple_rules = {row[0]: row[1] for row in cur.fetchall()}
                    if not simple_rules:
                        logger.debug("cpq: no declarative constraint rules found")
                        return rules

                    cur.execute(
                        """
                        SELECT
                            (attributes->>'bm_config_rule_id')::bigint AS rule_id,
                            (attributes->>'attribute_id')::bigint       AS cond_attr_id,
                            attributes->>'value1'                       AS cond_value
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND ontology_type = 'BmConfigRuleInput'
                        """,
                        (workspace_id,),
                    )
                    inputs: dict[int, tuple[int, str]] = {}
                    for rule_id, cond_attr_id, cond_value in cur.fetchall():
                        if rule_id and cond_attr_id:
                            inputs[int(rule_id)] = (int(cond_attr_id), cond_value or "")

                    # action_type 4 = include (only these values valid)
                    # action_type 5 = exclude (these values removed)
                    # Multiple actions per rule → multiple allowed values for same target
                    cur.execute(
                        """
                        SELECT
                            (attributes->>'bm_config_rule_id')::bigint AS rule_id,
                            (attributes->>'attribute_id')::bigint       AS target_attr_id,
                            (attributes->>'action_type')::int           AS action_type,
                            attributes->>'value1'                       AS value1
                        FROM aryx_entity
                        WHERE workspace_id = %s
                          AND ontology_type = 'BmConfigRuleAction'
                          AND (attributes->>'action_type')::int IN (4, 5)
                        """,
                        (workspace_id,),
                    )
                    # rule_id → {target_attr_id → [(action_type, value)]}
                    action_groups: dict[int, dict[int, list[tuple[int, str]]]] = {}
                    for rule_id, target_attr_id, action_type, val in cur.fetchall():
                        if rule_id and target_attr_id and val:
                            action_groups.setdefault(
                                int(rule_id), {}
                            ).setdefault(int(target_attr_id), []).append(
                                (int(action_type), val)
                            )

                    for rule_entity_id, rule_name in simple_rules.items():
                        inp = inputs.get(rule_entity_id)
                        rule_actions = action_groups.get(rule_entity_id, {})
                        if not inp or not rule_actions:
                            continue
                        cond_attr_id, cond_value = inp
                        for target_attr_id, av_list in rule_actions.items():
                            # action_type=4 → include these values only
                            allowed = [v for at, v in av_list if at == 4]
                            if allowed:
                                rules.append(ConstraintRule(
                                    rule_name=rule_name or str(rule_entity_id),
                                    condition_attr_id=cond_attr_id,
                                    condition_value=cond_value,
                                    target_attr_id=target_attr_id,
                                    allowed_values=allowed,
                                ))
        except Exception:
            logger.debug("cpq: constraint rule load failed", exc_info=True)
        logger.info("cpq: loaded %d constraint rules", len(rules))
        return rules

    def apply_constraint_rules(
        self,
        attrs: list[ConfigAttr],
        rules: list[ConstraintRule],
        filled: dict[str, str],
    ) -> dict[int, list[str]]:
        """Return {attr_entity_id: [allowed_item_values]} for attrs with active constraints.

        Multiple rules for the same target are intersected (AND semantics) so
        only values permitted by ALL active constraint rules remain valid.
        """
        if not rules:
            return {}
        by_eid: dict[int, ConfigAttr] = {a.entity_id: a for a in attrs}
        filled_by_eid: dict[int, str] = {
            a.entity_id: filled[a.variable_name]
            for a in attrs if a.variable_name in filled
        }
        constrained: dict[int, list[str]] = {}
        for rule in rules:
            if rule.condition_attr_id not in filled_by_eid:
                continue
            if filled_by_eid[rule.condition_attr_id].lower() != rule.condition_value.lower():
                continue
            if rule.target_attr_id in constrained:
                existing = set(constrained[rule.target_attr_id])
                constrained[rule.target_attr_id] = [v for v in rule.allowed_values if v in existing]
            else:
                constrained[rule.target_attr_id] = list(rule.allowed_values)
        if constrained:
            names = [by_eid[eid].variable_name for eid in constrained if eid in by_eid]
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
    ) -> tuple[list[ConfigAttr], dict[str, str], dict[str, str], dict[int, list[str]]]:
        """Run hide → recommend → constrain → auto-fill until state is stable.

        Each pass:
          1. Auto-fill (hints + defaults + first-option, with active constraints)
          2. Apply hiding rules → update visible attrs
          3. Apply recommendation rules → add new auto-fills
          4. Apply constraint rules → update constrained option sets

        Iterates until neither the filled set nor the visible attr set changes.
        Returns (visible_attrs, filled, display_filled, constrained_opts).
        """
        _MAX_LOOPS = 8
        display_filled: dict[str, str] = {}
        constrained_opts: dict[int, list[str]] = {}

        for _ in range(_MAX_LOOPS):
            prev_filled_keys = set(filled.keys())
            prev_visible_ids = {a.entity_id for a in attrs}

            # Apply hiding rules first so auto_fill only fills visible attrs
            attrs, _ = self.apply_hiding_rules(attrs, filled, hiding_rules)

            # Strip values for attrs that hiding rules just removed from view.
            # Without this, hidden attrs bleed into the BOM payload.
            visible_vns = {a.variable_name for a in attrs}
            hidden_keys = [k for k in filled if k not in visible_vns]
            for k in hidden_keys:
                filled.pop(k, None)
                display_filled.pop(k, None)

            filled, display_filled, _ = self.auto_fill(
                attrs, hints, already_filled=filled, constrained_opts=constrained_opts,
            )

            new_fills = self.apply_recommendation_rules(attrs, filled, rec_rules)
            if new_fills:
                filled.update({k: iv for k, (iv, _d) in new_fills.items()})
                display_filled.update({k: d for k, (_iv, d) in new_fills.items()})

            constrained_opts = self.apply_constraint_rules(attrs, con_rules, filled)

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
        by_eid: dict[int, ConfigAttr] = {a.entity_id: a for a in attrs}

        # A show-type hiding rule revealed this attr
        for rule in hiding_rules:
            if rule.target_attr_id != pending_attr.entity_id or rule.hide:
                continue
            cond_attr = by_eid.get(rule.condition_attr_id)
            if cond_attr and cond_attr.variable_name in filled:
                disp_val = display_filled.get(
                    cond_attr.variable_name, filled[cond_attr.variable_name]
                )
                return (
                    f"Since **{cond_attr.display_label}** was set to **{disp_val}**, "
                    f"we now need **{pending_attr.display_label}**."
                )

        # A recommendation rule targeted this attr (but had multiple valid options)
        for rule in rec_rules:
            if rule.target_attr_id != pending_attr.entity_id:
                continue
            cond_attr = by_eid.get(rule.condition_attr_id)
            if cond_attr and cond_attr.variable_name in filled:
                disp_val = display_filled.get(
                    cond_attr.variable_name, filled[cond_attr.variable_name]
                )
                return (
                    f"For the selected **{cond_attr.display_label}** ({disp_val}), "
                    f"please choose a **{pending_attr.display_label}**:"
                )

        return ""

    # ── Auto-fill ─────────────────────────────────────────────────────────────

    def auto_fill(
        self,
        attrs: list[ConfigAttr],
        hints: dict[str, str],
        already_filled: dict[str, str] | None = None,
        constrained_opts: dict[int, list[str]] | None = None,
    ) -> tuple[dict[str, str], dict[str, str], list[ConfigAttr]]:
        """Auto-fill attributes. Never assigns None/null/empty values.

        Priority order (first match wins):
          1. Already filled in a prior turn.
          2. User-stated value matched from NL hints.
          3. Valid default_value from XML (not None/null/0).
          4. First eligible item_value by order_number (respects constrained_opts).

        constrained_opts — {entity_id: [allowed_item_values]} from active
          ConstraintRules. When set, first-option fallback only picks from the
          allowed set; hint/default paths ignore constraints (they were validated
          by the rule that produced the recommendation).

        Returns:
          filled         — {variable_name: item_value} for API payload
          display_filled — {variable_name: display_name} shown to sales rep
          pending        — attrs that still need a human answer
        """
        filled: dict[str, str] = dict(already_filled or {})
        display_filled: dict[str, str] = {}
        pending: list[ConfigAttr] = []

        for attr in attrs:
            vn = attr.variable_name

            if vn in filled:
                # Already answered in a prior turn
                matched_display = next(
                    (o.display_name for o in attr.options
                     if o.item_value == filled[vn]),
                    filled[vn],
                )
                display_filled[vn] = matched_display
                continue

            value: str | None = None
            display: str | None = None

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
                    break

            # 2. Default value
            if not value and _valid(attr.default_value):
                value = attr.default_value
                display = next(
                    (o.display_name for o in attr.options
                     if o.item_value == attr.default_value),
                    attr.default_value,
                )

            # 3. Single-remaining-option auto-fill (NO EAGER EVALUATION).
            # Only auto-select when exactly ONE valid option remains after
            # constraint filtering — that is not a real user choice.
            # Multi-option attrs with no recommendation rule go to pending so
            # the user is prompted (spec §CRITICAL DIRECTIVE 1: STOP AND WAIT).
            is_decision_attr = any(
                dk in vn_flat for dk in _DECISION_REQUIRED_KEYS
            )
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
                # else: 0 or 2+ options → pending (user must choose)

            if value:
                filled[vn] = value
                display_filled[vn] = display or value
            elif attr.options or is_decision_attr:
                # Attrs with a meaningful choice set OR decision-required free-text
                # attrs (region/country/hwversion) go to pending for user input.
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

    # Change-request verbs — user wants to modify a filled attr (Step 6 cascade)
    _CHANGE_VERB_RE = re.compile(
        r"\b(swap|change|switch|replace|update|modify|actually|instead|"
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

            # Direct apply_answer match with a different value
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

        for rule in hiding_rules:
            if rule.condition_attr_id == changed_attr.entity_id:
                dependents.add(rule.target_attr_id)
        for rule in rec_rules:
            if rule.condition_attr_id == changed_attr.entity_id:
                dependents.add(rule.target_attr_id)
        for rule in con_rules:
            if rule.condition_attr_id == changed_attr.entity_id:
                dependents.add(rule.target_attr_id)

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
    ) -> tuple[str, str] | None:
        """Match the user's natural-language answer to a valid option.

        Returns (item_value, display_name) or None if no match found.
        """
        ua = user_answer.strip().lower()

        # Numeric selection: user typed "1", "2", etc. → pick by position in the
        # presented option list (only _presentable options, matching next_question_prompt).
        if ua.isdigit():
            presentable = [o for o in attr.options if _presentable(o.item_value)]
            idx = int(ua) - 1
            if 0 <= idx < len(presentable) and _valid(presentable[idx].item_value):
                return presentable[idx].item_value, presentable[idx].display_name

        # Exact item_value match
        for opt in attr.options:
            if opt.item_value.lower() == ua:
                return opt.item_value, opt.display_name

        # Exact display-name match
        for opt in attr.options:
            if opt.display_name.lower() == ua:
                if _valid(opt.item_value):
                    return opt.item_value, opt.display_name

        # User answer contained in option's display name (user typed a prefix)
        for opt in attr.options:
            if ua in opt.display_name.lower():
                if _valid(opt.item_value):
                    return opt.item_value, opt.display_name

        # Option display name found as a whole WORD in user answer — word-boundary
        # prevents "me" (Middle East code) from matching in "north a*me*rica".
        for opt in attr.options:
            dn_lower = opt.display_name.lower()
            if re.search(r"\b" + re.escape(dn_lower) + r"\b", ua):
                if _valid(opt.item_value):
                    return opt.item_value, opt.display_name

        # Free-text field
        if not attr.options and _valid(user_answer):
            return user_answer.strip(), user_answer.strip()

        return None

    # ── Payload builder ───────────────────────────────────────────────────────

    def _is_html_value(self, val: str) -> bool:
        """True when the value is an HTML/template blob (not a real selection)."""
        s = val.strip()
        return s.startswith("<") and ">" in s

    def build_payload(self, filled: dict[str, str]) -> dict[str, str]:
        """Return the final CPQ BOM API payload {variable_name: item_value}.

        Excludes HTML template values — those are layout/display fields, not
        real configuration inputs for the BOM API.
        """
        return {
            k: v for k, v in filled.items()
            if _valid(v) and not self._is_html_value(v)
        }

    # ── Summary renderer ──────────────────────────────────────────────────────

    def render_filled_summary(
        self,
        display_filled: dict[str, str],
        attrs: list["ConfigAttr"] | None = None,
    ) -> str:
        """Compact human-readable summary of what has been auto-filled.

        Uses display_label (human name) as the key when attrs are supplied,
        falling back to variable_name only when the attr is not found.
        Skips HTML template values (layout/display fields).
        """
        if not display_filled:
            return ""
        label_map: dict[str, str] = (
            {a.variable_name: a.display_label for a in attrs} if attrs else {}
        )
        items = [
            f"- **{label_map.get(var, var)}** → {label}"
            for var, label in display_filled.items()
            if not self._is_html_value(label)
        ]
        if not items:
            return ""
        return "**Configured so far:**\n" + "\n".join(items)
