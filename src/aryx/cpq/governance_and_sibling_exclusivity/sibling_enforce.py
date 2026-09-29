"""``enforce_exclusive_sibling_families`` -- the mutating apply pass over
``exclusive_sibling_family_exclusions`` (Phase 4 step 7 extraction from
``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Takes the ``engine`` instance and calls
``engine.exclusive_sibling_family_exclusions`` (not the extracted
function directly) so a per-instance or per-class replacement of the
detector is still honored, exactly as the original ``self.``-call was.
Its only production call site is ``aryx/api/ask_api.py`` (a separate
post-processing step, not part of ``auto_fill``/``evaluate_rules_loop``),
which reaches it through the thin ``CpqEngine`` wrapper unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aryx.cpq.state import ConfigAttr

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.engine import CpqEngine


def enforce_exclusive_sibling_families(
    engine: CpqEngine,
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
    """Apply `exclusive_sibling_family_exclusions`: strip the weakly-
    sourced single-select sibling from `filled` (mutated in place) and
    add its multi-select sibling to `pending` if nothing has already
    filled or asked it. Returns the updated pending list.

    `all_attrs` -- see exclusive_sibling_family_exclusions' docstring;
    pass the full, pre-hiding catalog attr list so the label-stem
    pairing check isn't fooled by a multi-way label collision that
    happens to look like a 2-attr pair only because hiding rules left
    just 2 of the real N visible this turn.

    `product_name`/`workspace_id`/`catalog_prefix` -- passed straight
    through to `exclusive_sibling_family_exclusions` for its
    `_KNOWN_SIBLING_PAIRS` model_policy resolution; see that function's
    own docstring."""
    to_strip, to_ask = engine.exclusive_sibling_family_exclusions(
        attrs, filled, filled_multi, filled_source, all_attrs=all_attrs,
        catalog_confirmed_vns=catalog_confirmed_vns, product_name=product_name,
        workspace_id=workspace_id, catalog_prefix=catalog_prefix,
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
        # select sibling that's present in `attrs`, the visible list --
        # see that function's docstring for the hidden-sibling
        # regression this closes). Truthiness check (not mere key
        # presence) is deliberate here --
        # see test_enforce_still_asks_when_multi_sibling_has_an_empty_
        # placeholder: a governing multi-select sibling this mechanism
        # just decided IS the real answer for this concept must still
        # be asked even if auto_fill left an empty-list placeholder for
        # it, because THIS mechanism's whole point is that nobody has
        # actually confirmed the real concept yet. (A false-positive
        # pairing that wrongly reached this point at all -- e.g. two
        # unrelated attrs coincidentally sharing a display label -- is
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
