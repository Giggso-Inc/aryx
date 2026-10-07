"""Diagnostic only: the not-applicable guard says, once per turn, which models it resolved from the customer's wording
(or that it resolved none and is therefore a no-op)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from aryx.cpq.auto_fill_stages import tier0_not_applicable_guard as guard

RESOLVE = "aryx.cpq.data_table.data_table_resolver.resolve_product_cpq_models_from_hint"


def _run(models, cache=None, debug=True, hint="I want a quote for APX N30 for US", workspace_id=1267):
    out = []
    ctx = SimpleNamespace(dt_cache=cache)
    scope = SimpleNamespace(workspace_id=workspace_id, catalog_prefix="Astro25Configdata", product_anchor_hint=hint)
    with patch.object(guard, "would_log", return_value=debug), \
            patch.object(guard, "raven_log", side_effect=lambda *a, **k: out.append(k["context"])), \
            patch(RESOLVE, return_value=models) as resolve:
        guard._log_device_once(ctx, scope)
    return out, resolve


def test_a_resolved_device_is_logged_with_its_models():
    (line,), _ = _run(("APXN30", "APXN30_BOM"))
    assert (line["reason_code"], line["model_count"], line["models"]) == (
        "GUARD_DEVICE_RESOLVED", 2, ["APXN30", "APXN30_BOM"])
    assert line["hint"].startswith("I want a quote")


def test_an_unresolved_device_is_named_as_a_no_op():
    (line,), _ = _run(())
    assert line["reason_code"] == "GUARD_DEVICE_UNRESOLVED_NO_OP" and line["model_count"] == 0


def test_it_is_logged_once_per_turn_with_a_cache_and_resolved_once():
    cache = {}
    out1, _ = _run(("APXN30",), cache=cache)
    out2, resolve2 = _run(("APXN30",), cache=cache)
    assert len(out1) == 1 and out2 == [] and resolve2.call_count == 0


def test_with_debug_off_nothing_is_resolved_or_logged():
    out, resolve = _run(("APXN30",), debug=False)
    assert out == [] and resolve.call_count == 0


def test_no_hint_or_no_workspace_is_unresolved_without_calling_the_resolver():
    for kwargs in ({"hint": ""}, {"workspace_id": None}):
        (line,), resolve = _run(("APXN30",), **kwargs)
        assert line["reason_code"] == "GUARD_DEVICE_UNRESOLVED_NO_OP" and resolve.call_count == 0


def test_a_failing_resolver_never_breaks_the_fill():
    ctx = SimpleNamespace(dt_cache=None)
    scope = SimpleNamespace(workspace_id=1, catalog_prefix="", product_anchor_hint="x")
    with patch.object(guard, "would_log", return_value=True), patch(RESOLVE, side_effect=RuntimeError("boom")):
        guard._log_device_once(ctx, scope)          # no exception
