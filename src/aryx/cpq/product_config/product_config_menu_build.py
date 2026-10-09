"""`load_product_config`'s menu-option build stage (Phase 4, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md): batch-fetches every collected menu
item's PostgreSQL row, then dedups/sorts them per attribute into
`MenuOption` lists. Logic unchanged from the original inline block.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.config import get_settings
from aryx.cpq.engine import MenuOption, _NOISE_ITEM_FRAGMENTS

# CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T4: word-boundary match, not
# bare substring -- "test" previously matched inside "LATEST RELEASE"
# ("la-TEST-release"), silently dropping a real, legal catalog option.
# Same fix shape as T5's region-code substring bug.
_NOISE_ITEM_FRAGMENT_RES = [
    re.compile(r"\b" + re.escape(f) + r"\b") for f in _NOISE_ITEM_FRAGMENTS
]


def _is_noise_option(iv_lo: str, dt_lo: str) -> bool:
    """True for a placeholder option. Default: any of the noise words appears as a word of the value or display name.
    With ``cpq_noise_option_whole_value_enabled``: only when the WHOLE value is a noise word (digits and punctuation
    aside: "Test", "Dummy 2"), so "FPS APX TEST TRIGGER - SW VALIDATION" and
    "TEST RESULTS/RATED AUDIO PRINTOUT LABEL" stay."""
    if getattr(get_settings(), "cpq_noise_option_whole_value_enabled", False) is True:
        return any(re.sub(r"[^a-z]+", " ", text).strip() in _NOISE_ITEM_FRAGMENTS for text in (iv_lo, dt_lo))
    return any(r.search(text) for text in (iv_lo, dt_lo) for r in _NOISE_ITEM_FRAGMENT_RES)


def build_menu_by_attr(
    engine: Any, workspace_id: int, neighbor_map: dict[int, list[int]],
    all_menu_ids: list[int],
) -> dict[int, list["MenuOption"]]:
    # Single batch fetch for all menu items across all attrs
    all_menu_pg = engine._batch_fetch(all_menu_ids, workspace_id) if all_menu_ids else {}

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
                if _is_noise_option(iv_lo, dt_lo):
                    continue
                if iv_lo in seen_item_values:
                    continue
                seen_item_values.add(iv_lo)
                opts.append(MenuOption(item_value=iv, display_name=dt, order=order))
        opts.sort(key=lambda x: x.order)
        menu_by_attr[eid] = opts
    return menu_by_attr
