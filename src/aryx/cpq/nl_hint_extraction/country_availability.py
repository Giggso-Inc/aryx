"""Country/product-line compatibility check (Phase 4 step 11 extraction
from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

`check_country_availability` answers the one anchor-gate question that
needs the rule engine rather than text matching: can this catalog's
product-line selector still offer anything at all once the session's
country is applied?

`apply_constraint_rules` -- one of the eight deliberately-deferred
oversized methods still living on `CpqEngine` -- is reached back through
the passed-in `engine` instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.bml import BmlEvaluator
    from aryx.cpq.state import ConfigAttr, ConstraintRule


def check_country_availability(
    engine: Any,
    attrs: list["ConfigAttr"],
    con_rules: list["ConstraintRule"],
    filled: dict[str, str],
    bml_eval: "BmlEvaluator",
    workspace_id: int | None = None,
    catalog_prefix: str = "",
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
    constrained = engine.apply_constraint_rules(
        attrs, con_rules, filled, bml_eval,
        workspace_id=workspace_id, catalog_prefix=catalog_prefix,
    )
    allowed = constrained.get(selector.entity_id)
    if allowed is None:
        return True
    return bool(allowed)
