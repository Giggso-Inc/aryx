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
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption
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
    # "country" matches ultimateDestinationCountry, CRM_BILL_COUNTRY, dest_country, etc.
    ("country", r"\b(us|usa|united states|u\.s\.)\b", "US"),
    ("country", r"\b(uk|united kingdom|great britain)\b", "UK"),
    ("country", r"\bgermany\b", "DE"),
    ("country", r"\bfrance\b", "FR"),
    ("region", r"\b(north america|na)\b", "NA"),
    ("region", r"\bemea\b", "EMEA"),
    ("region", r"\bapac\b", "APAC"),
    # Product name hints
    ("product", r"\bapx\s*next\b", "APX Next"),
    ("product", r"\bapx\s+n\d+\b", "APX Next"),
    ("product", r"\bsl\s*3500\b", "SL3500e"),
]

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

        Returns {attr_key_fragment: item_value} where item_value is the
        raw API code to match against options.
        """
        q = question.lower()
        hints: dict[str, str] = {}
        for key, pattern, value in _HINT_PATTERNS:
            if re.search(pattern, q, re.IGNORECASE):
                hints[key] = value
        return hints

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

        # Step 3 — for each attr, get menu items from FalkorDB + PostgreSQL
        menu_by_attr: dict[int, list[MenuOption]] = {}
        for ent in attr_ents[:150]:  # cap to prevent timeout on large configs
            eid = ent["id"]
            try:
                neighbors = reader.neighbors(eid)
                menu_ids = [
                    n["id"] for n in neighbors
                    if "menuitem" in (n.get("type") or "").lower().replace("_", "")
                ]
                if menu_ids:
                    menu_pg = self._batch_fetch(menu_ids, workspace_id)
                    opts: list[MenuOption] = []
                    for mid in menu_ids:
                        ma = menu_pg.get(mid, {})
                        # Always use item_value (API code), item_text for display
                        iv = str(ma.get("item_value") or "").strip()
                        dt = str(ma.get("item_text") or ma.get("name") or iv).strip()
                        order = int(ma.get("order_number") or ma.get("order") or 999)
                        if iv:
                            opts.append(MenuOption(
                                item_value=iv, display_name=dt, order=order,
                            ))
                    opts.sort(key=lambda x: x.order)
                    menu_by_attr[eid] = opts
            except Exception:
                logger.debug("cpq: menu item fetch failed for attr %d", eid, exc_info=True)

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

    # ── Auto-fill ─────────────────────────────────────────────────────────────

    def auto_fill(
        self,
        attrs: list[ConfigAttr],
        hints: dict[str, str],
        already_filled: dict[str, str] | None = None,
    ) -> tuple[dict[str, str], dict[str, str], list[ConfigAttr]]:
        """Auto-fill attributes. Never assigns None/null/empty values.

        Priority order (first match wins):
          1. Already filled in a prior turn.
          2. User-stated value matched from NL hints.
          3. Valid default_value from XML (not None/null/0).
          4. First eligible item_value by order_number.

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
                    # Priority: exact item_value match → word-boundary display match
                    for opt in attr.options:
                        if opt.item_value.lower() == hv_lower:
                            value = opt.item_value
                            display = opt.display_name
                            break
                    if not value:
                        for opt in attr.options:
                            # Word-boundary match in display name (prevents "us" matching "Austria")
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

            # 3. First eligible option (no None/null/empty)
            if not value:
                for opt in attr.options:
                    if _valid(opt.item_value):
                        value = opt.item_value
                        display = opt.display_name
                        break

            if value:
                filled[vn] = value
                display_filled[vn] = display or value
            else:
                pending.append(attr)

        return filled, display_filled, pending

    # ── Next question ─────────────────────────────────────────────────────────

    def next_question_prompt(self, attr: ConfigAttr) -> str:
        """Build the question text shown to the sales rep for one pending attr."""
        lines = [f"**{attr.display_label}**"]
        if attr.options:
            lines.append("Choose one of the following:")
            for opt in attr.options:
                if _valid(opt.item_value):
                    lines.append(f"  • {opt.display_name}")
        else:
            lines.append("Please provide a value.")
        return "\n".join(lines)

    def apply_answer(
        self,
        attr: ConfigAttr,
        user_answer: str,
    ) -> tuple[str, str] | None:
        """Match the user's natural-language answer to a valid option.

        Returns (item_value, display_name) or None if no match found.
        """
        ua = user_answer.strip().lower()

        # Exact item_value match
        for opt in attr.options:
            if opt.item_value.lower() == ua:
                return opt.item_value, opt.display_name

        # Display-name substring match
        for opt in attr.options:
            if ua in opt.display_name.lower() or opt.display_name.lower() in ua:
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

    def render_filled_summary(self, display_filled: dict[str, str]) -> str:
        """Compact human-readable summary of what has been auto-filled.

        Skips HTML template values (layout/display fields, not real config).
        """
        if not display_filled:
            return ""
        lines = ["Here's what I've configured so far:"]
        for var, label in display_filled.items():
            if not self._is_html_value(label):
                lines.append(f"  ✓ **{var}** → {label}")
        return "\n".join(lines) if len(lines) > 1 else ""
