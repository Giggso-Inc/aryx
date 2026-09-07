"""Per-attribute resolution for `CpqEngine.auto_fill` (Phase 4, the
`FillContext`/`FillScope` decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_
2026-09-03.md). `resolve_one_attr` is `auto_fill`'s P1 tier -- the 6-tier
priority cascade its own docstring documents (already filled -> NL hint
-> satisfied recommendation -> XML default_value -> rule-governed
default-or-first -> first-eligible-option-by-order), plus hidden-attr
and multi-select handling woven through. Relocated here wholesale
(mechanical, behavior-preserving -- see the plan doc's "auto_fill_resolve
move" entry) from a nested closure inside `auto_fill` itself; not yet
split further (that is the next step in the plan).

`engine` is the live `CpqEngine` instance (for its own method calls,
`self.` in the original); `ctx` is a `FillContext` (mutable, shared
across every attr in one `auto_fill` call); `scope` is a `FillScope`
(read-only, includes already-bound closures for `is_pointer_default`/
`satisfied_recommendation`/`dt_never_governed_anywhere`, built once by
`auto_fill`'s own P0 setup before this loop starts).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from aryx.cpq import engine as _engine_module
from aryx.cpq import rule_trace
from aryx.cpq.engine import (
    _BLIND_FILL_RISK_ACCEPTED_VNS,
    _DECISION_ANCHOR_VNS,
    _DECISION_REQUIRED_KEYS,
    _KNOWN_MISSING_DATA_TABLES,
    _NEVER_GUESS_SCRIPT_GOVERNED,
    _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS,
    _SELECT_ALL_NARROWED_LEGAL_MULTI_VNS,
    _country_alias_group,
    _no_real_fill_justification,
    _sole_opt_out_option,
    _valid,
    logger,
)

# `_fill_signature` is looked up through the module (not imported by name
# like everything else above) because tests/test_cpq_rule_loop_perf_
# gating_2026_08_19.py monkeypatches `aryx.cpq.engine._fill_signature`
# directly -- a `from ... import _fill_signature` would have captured its
# own frozen reference at import time, silently making that monkeypatch
# a no-op for code running from this module (confirmed live: this was
# the one real regression the auto_fill_resolve move introduced).

if TYPE_CHECKING:
    from aryx.cpq.engine import CpqEngine, FillContext, FillScope
    from aryx.cpq.state import ConfigAttr


def resolve_one_attr(
    engine: "CpqEngine", attr: "ConfigAttr", ctx: "FillContext", scope: "FillScope",
) -> None:
        vn = attr.variable_name
        # §2e (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md): set by
        # _satisfied_recommendation's call sites below when it returns
        # a match, so the trace call downstream can attribute the fill
        # to the specific rule that fired instead of a generic tag.
        fired_rule_name: str | None = None

        if vn in ctx.filled:
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
            if ctx.filled[vn] == "" and ctx.sources.get(vn) == "user":
                ctx.display_filled[vn] = "(none)"
                return
            # Already answered in a prior turn — but a cascade may have
            # narrowed this attr's allowed set since then (single-select
            # counterpart of the multi-select re-validation below, §5/
            # Phase J). If the locked value is no longer allowed, clear
            # it and fall through to re-resolution instead of keeping a
            # stale, now-invalid answer.
            allowed_single = (
                scope.constrained_opts.get(attr.entity_id) if scope.constrained_opts else None
            )
            if allowed_single is not None and ctx.filled[vn] not in allowed_single:
                stale_display = ctx.display_filled.get(vn, ctx.filled[vn])
                ctx.dropped[vn] = [stale_display]
                if ctx.sources.get(vn) == "user":
                    ctx.user_answered_dropped_ids.add(attr.entity_id)
                ctx.filled.pop(vn, None)
                ctx.display_filled.pop(vn, None)
                ctx.sources.pop(vn, None)
            elif ctx.sources.get(vn) == "default_first_available":
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
                #
                # docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md:
                # "every pass" was multiplying evaluate_rules_loop's cost
                # up to 8x per turn -- gate the re-derivation on whether
                # anything relevant has actually changed since it was
                # last (re)derived. Skipped entirely when the caller
                # doesn't opt in (`_default_fill_signatures is None`),
                # identical to every pre-existing call site.
                if ctx.default_fill_signatures is not None:
                    _sig_filled = (
                        ctx.filled if not scope.signature_exclude_vns else
                        {k: v for k, v in ctx.filled.items() if k not in scope.signature_exclude_vns}
                    )
                    _sig_filled_multi = (
                        ctx.filled_multi if not scope.signature_exclude_vns else
                        {k: v for k, v in ctx.filled_multi.items() if k not in scope.signature_exclude_vns}
                    )
                    _cur_sig = _engine_module._fill_signature(
                        _sig_filled, _sig_filled_multi, {a.entity_id for a in scope.attrs},
                    )
                    if ctx.default_fill_signatures.get(vn) == _cur_sig:
                        matched_display = next(
                            (o.display_name for o in attr.options
                             if o.item_value == ctx.filled[vn]),
                            ctx.filled[vn],
                        )
                        ctx.display_filled[vn] = matched_display
                        return
                    ctx.default_fill_signatures[vn] = _cur_sig
                ctx.filled.pop(vn, None)
                ctx.display_filled.pop(vn, None)
                ctx.sources.pop(vn, None)
            else:
                matched_display = next(
                    (o.display_name for o in attr.options
                     if o.item_value == ctx.filled[vn]),
                    ctx.filled[vn],
                )
                ctx.display_filled[vn] = matched_display
                return
        if vn in ctx.filled_multi:
            allowed_now = scope.constrained_opts.get(attr.entity_id) if scope.constrained_opts else None
            if allowed_now is not None:
                if ctx.sources.get(vn) == "default_first_available":
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
                    #
                    # docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md
                    # — same gate as the single-select branch above: only
                    # actually re-derive when something relevant changed
                    # since last time.
                    if ctx.default_fill_signatures is not None:
                        _sig_filled = (
                            ctx.filled if not scope.signature_exclude_vns else
                            {k: v for k, v in ctx.filled.items() if k not in scope.signature_exclude_vns}
                        )
                        _sig_filled_multi = (
                            ctx.filled_multi if not scope.signature_exclude_vns else
                            {k: v for k, v in ctx.filled_multi.items() if k not in scope.signature_exclude_vns}
                        )
                        _cur_sig = _engine_module._fill_signature(
                            _sig_filled, _sig_filled_multi, {a.entity_id for a in scope.attrs},
                        )
                        if ctx.default_fill_signatures.get(vn) == _cur_sig:
                            ctx.display_filled[vn] = ", ".join(
                                next(
                                    (o.display_name for o in attr.options
                                     if o.item_value == v),
                                    v,
                                )
                                for v in ctx.filled_multi[vn]
                            )
                            return
                        ctx.default_fill_signatures[vn] = _cur_sig
                    ctx.filled_multi.pop(vn, None)
                    ctx.sources.pop(vn, None)
                else:
                    allowed_set = set(allowed_now)
                    kept = [v for v in ctx.filled_multi[vn] if v in allowed_set]
                    lost = [v for v in ctx.filled_multi[vn] if v not in allowed_set]
                    if lost:
                        ctx.dropped[vn] = lost
                        ctx.filled_multi[vn] = kept
            if not ctx.filled_multi.get(vn):
                if ctx.sources.get(vn) == "user":
                    # An EMPTY selection the user explicitly confirmed
                    # ("no mounts needed" declining an optional grid) is
                    # a settled answer, not an unresolved attr — keep it
                    # so the question is never re-asked and the payload
                    # simply carries no rows. Only constraint-drops
                    # (non-user sources) fall through to re-resolution.
                    ctx.display_filled[vn] = "(none)"
                    return
                ctx.filled_multi.pop(vn, None)
                ctx.sources.pop(vn, None)
                # Falls through to normal resolution below — the drop may
                # have emptied the selection entirely.
            else:
                ctx.display_filled[vn] = ", ".join(
                    next((o.display_name for o in attr.options if o.item_value == v), v)
                    for v in ctx.filled_multi[vn]
                )
                # Grid-selector re-ask (docs/CPQ_SVX_MOUNTING_TYPE_
                # ARRAY_GRID_MULTI_SELECT_PLAN_2026_08_25.md): live-
                # confirmed the customer naming just ONE of 5-6
                # narrowed mounting-type options permanently settled
                # this attr — the other real, still-valid options were
                # never offered again, even though the real native UI
                # is a grid letting several rows be filled across
                # turns. `vn in grid_selector_vns` is the SAME
                # structural signal (resolve_array_grid_links) that
                # already forces this attr onto `pending` on its FIRST
                # ask (see the is_decision_attr check below) — applying
                # it here too, gated on unpicked options actually
                # remaining and the customer not having declined
                # further picks, is not a new exception, just this
                # existing exception surviving past the first pick.
                if (
                    vn in scope.grid_selector_vns
                    and vn not in (scope.grid_declined_vns or ())
                    and engine.grid_selector_remaining_options(
                        attr, ctx.filled_multi, scope.constrained_opts)
                ):
                    ctx.pending.append(attr)
                return

        if attr.hidden:
            # Never asked, never NL-hint-matched, never blind-first-picked
            # — a hidden attr only ever gets its own XML default_value
            # (BML scripts elsewhere may reference it), or is left out of
            # `filled` entirely if it has none. Never enters `pending`.
            # Pointer-defaults are NOT literals — resolved (or left
            # unfilled) by the post-pass below, never written verbatim.
            if _valid(attr.default_value) and not scope.is_pointer_default(attr):
                ctx.filled[vn] = attr.default_value
                ctx.display_filled[vn] = next(
                    (o.display_name for o in attr.options
                     if o.item_value == attr.default_value),
                    attr.default_value,
                )
                ctx.sources.setdefault(vn, "default")
            return

        value: str | None = None
        display: str | None = None
        source: str = "auto"

        # 1. User hint matching — strip underscores/case, check fragment containment
        vn_flat = vn.lower().replace("_", "")
        for hint_key, hint_val in scope.hints.items():
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
        # 2026-08-18 fix (confirmed live via direct repro): a decision-
        # anchor attr (country/region/hardware version/product --
        # _DECISION_ANCHOR_VNS) whose CUSTOMER-CONFIRMED value was just
        # dropped THIS SAME pass (a few lines above, because a real
        # constraint narrowed it away) must never be silently reasserted
        # to a DIFFERENT value by a recommendation rule here -- that
        # silently overwrites a real customer decision with no re-ask,
        # no warning, and no trace of what happened to their answer.
        # Skipping this branch lets the attr fall through to `pending`
        # instead, so the customer is asked to re-confirm -- same
        # "never silently reguess a real decision" principle
        # `user_answered_dropped_ids` already enforces for the blind-
        # pick paths later in this function, extended here to close the
        # one place it didn't yet cover. Every OTHER attr (not a
        # decision anchor, or not dropped this pass) is unaffected --
        # this is a narrow, targeted exclusion, not a change to how
        # recommendation rules resolve in general.
        if (
            not value and scope.rec_by_target and attr.options
            and not (vn in _DECISION_ANCHOR_VNS and attr.entity_id in ctx.user_answered_dropped_ids)
        ):
            _allowed_for_rec = (
                set(scope.constrained_opts.get(attr.entity_id, []))
                if scope.constrained_opts else None
            )
            _rec_candidate_opts = [
                o for o in attr.options
                if _valid(o.item_value)
                and (_allowed_for_rec is None or o.item_value in _allowed_for_rec)
            ]
            rec_match = scope.satisfied_recommendation(attr, _rec_candidate_opts)
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
            scope.constrained_opts is not None
            and attr.entity_id in scope.constrained_opts
            and attr.default_value not in scope.constrained_opts[attr.entity_id]
        )
        if (
            not value and _valid(attr.default_value)
            and not scope.is_pointer_default(attr)
            and not _default_excluded_by_constraint
            # §2d (docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md): once a
            # layout map is loaded, a bare catalog default_value no
            # longer fills the attribute on its own — falls through to
            # the final ask-branch, which §2c then skips (not asks)
            # since this isn't a decision-anchor or grid selector.
            and scope.display_order is None
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
                and scope.display_order is None):
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
            or engine._is_hardware_version_attr(attr)
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
                and vn not in (scope.skip_always_ask or ())
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
            or ("selectmodel" in vn_flat and vn not in (scope.skip_always_ask or ()))
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
        is_governed = attr.entity_id in scope.governed
        governed_source = "rule" if attr.entity_id in scope.rule_governed else "optional"
        filled_multi_now = False

        # Region-from-country derivation: region is a decision-required
        # key (always ask, D2/§Phase M-adjacent) UNLESS the confirmed
        # country resolves to one of this attr's real options — country
        # itself is untouched, still always asked (D1).
        if not value and "region" in vn_flat and scope.country and attr.options:
            derived = engine.derive_region(scope.country, attr)
            if derived:
                value, display = derived
                source = "country_derived"

        # Base Model region-allow default (see the precompute above) --
        # a real, confirmed per-region ALLOW value from an ingested
        # region-rule-shaped Data Table, not a blind guess. Checked
        # BEFORE the unconditional "basemodel" always-ask anchor above
        # gets to force this to `pending` -- only ever applies when
        # exactly one such value resolved.
        if not value and "basemodel" in vn_flat and scope.bm_region_allow_value and attr.options:
            match = next(
                (o for o in attr.options if o.item_value == scope.bm_region_allow_value),
                None,
            )
            if match:
                value = match.item_value
                display = match.display_name
                source = "region_allow_default"

        if not value and attr.options:
            allowed_for_attr = (
                set(scope.constrained_opts.get(attr.entity_id, []))
                if scope.constrained_opts else None
            )
            if allowed_for_attr is not None:
                # A constraint is a source of truth for VALIDITY, not
                # catalog spelling. If it names a legal value with no
                # literal item_value match in the real catalog (live-
                # confirmed: productSelectionProduct_all's constraint
                # returns 'APX NEXT XE 4G LTE PLUS 5G', which no real
                # option equals), keeping the phantom value in the
                # allowed set is harmless (nothing matches it anyway)
                # but discarding the WHOLE set back to unconstrained
                # over one bad value throws away the legitimate,
                # real-matching values too (live-confirmed regression:
                # Product went from a flip-flopping 1-2 option menu to
                # showing all 325 raw options). Drop only the phantom
                # entries -- keep whichever real values the constraint
                # did correctly narrow to. Falls back to fully
                # unconstrained only if EVERY value was phantom (an
                # empty allowed set would otherwise wrongly zero out
                # valid_opts entirely).
                real_item_values = {o.item_value for o in attr.options}
                narrowed = allowed_for_attr & real_item_values
                allowed_for_attr = narrowed or None
            valid_opts = [
                o for o in attr.options
                if _valid(o.item_value)
                and (allowed_for_attr is None or o.item_value in allowed_for_attr)
            ]
            if (
                len(valid_opts) == 1 and not is_decision_attr
                and attr.entity_id not in ctx.user_answered_dropped_ids
            ):
                # Exactly one choice — auto-fill, no user decision needed.
                #
                # EXCLUDED for is_decision_attr (2026-08-17, live-
                # confirmed): a constraint script can resolve a legal
                # value that has NO literal match in attr.options at
                # all (confirmed live: productSelectionProduct_all's
                # "Restrict APX Next Product Selection based on HW
                # Version" constraint correctly returned 2 legal
                # values, {'APX NEXT ENHANCED', 'APX NEXT XE 4G LTE
                # PLUS 5G'}, but the real catalog menu has no option
                # whose item_value literally equals the second string
                # at all -- only 'APX NEXT XE MULTI'/'APX NEXT XE
                # SINGLE BAND' exist). Intersecting against the real
                # menu then silently drops the phantom entry, leaving
                # "exactly 1" as a false positive from a script/
                # catalog mismatch, not a genuine single-choice
                # situation -- and Product got auto-filled without
                # ever asking. Depends on Tier-2 LLM evaluation timing
                # (whether the constraint script gets a slot before
                # the per-turn cap), so it doesn't reproduce every
                # turn -- non-decision attrs keep the original
                # shortcut; decision-required ones (Country/Region/
                # Hardware Version/Product) never take it, same
                # protection this whole function already gives them
                # everywhere else.
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
                         and vn in (scope.skip_always_ask or ()))
                # A real customer decision that a cascade just cleared
                # deserves to be re-asked, not silently re-guessed — same
                # "never blind-fill a real decision" principle as
                # productSelectionProduct_all above, generalized to any
                # attr whose cascade-dropped value was filled_source
                # "user" (docs/CPQ_SESSION_2_OPEN_ISSUES.md item 4).
                and attr.entity_id not in ctx.user_answered_dropped_ids
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
                        ctx.filled_multi[vn] = [o.item_value for o in valid_opts]
                        ctx.display_filled[vn] = ", ".join(o.display_name for o in valid_opts)
                        ctx.sources.setdefault(vn, governed_source)
                        filled_multi_now = True
                        if governed_source == "rule":
                            rule_trace.record_fire(
                                rule_type="auto_fill", rule_id="auto_fill:rule_governed_multi",
                                attr=vn, outcome=f"set={ctx.filled_multi[vn]}",
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
                        dt_match = engine._resolve_via_data_tables(
                            vn, ctx.filled, valid_opts, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache,
                        )
                        if dt_match:
                            ctx.filled_multi[vn] = [dt_match.item_value]
                            ctx.display_filled[vn] = dt_match.display_name
                            ctx.sources.setdefault(vn, "data_table")
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
                elif governed_source == "optional" and attr.entity_id in scope.conflicted_optional_ids:
                    # This attr shares a real option value with another
                    # "optional"-tier attr — first-by-order would silently
                    # pick a competing value for what's very likely the
                    # same hardware/accessory slot (§ surveillance-package
                    # double-fill). Ask instead of guessing which one wins.
                    pass
                elif vn in (scope.negated_vns or ()):
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
                        scope.satisfied_recommendation(attr, valid_opts)
                        if scope.rec_by_target else None
                    )
                    if rec_match:
                        value, display, fired_rule_name = rec_match
                        source = "rule"
                    elif (
                        dt_match := engine._resolve_via_data_tables(
                            vn, ctx.filled, valid_opts, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache,
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
                        scope.display_order is not None
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
                    elif (
                        _no_real_fill_justification(attr, scope.rec_by_target)
                        and vn not in _BLIND_FILL_RISK_ACCEPTED_VNS
                        and (opt_out_match := _sole_opt_out_option(valid_opts))
                    ):
                        # Nothing justifies picking among the REAL choices
                        # here, but the menu itself declares one option as
                        # the explicit "nothing needed" answer -- filling
                        # that isn't a guess among business alternatives,
                        # it's recognizing a choice the catalog already
                        # made for the customer. See
                        # `_sole_opt_out_option`'s own docstring.
                        value = opt_out_match.item_value
                        display = opt_out_match.display_name
                        source = "opt_out_default"
                    elif (
                        scope.display_order is not None and vn in scope.display_order
                        and not (
                            _no_real_fill_justification(attr, scope.rec_by_target)
                            and vn not in _BLIND_FILL_RISK_ACCEPTED_VNS
                        )
                    ):
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
                    elif scope.display_order is not None:
                        # Layout map loaded, but this attr isn't in its
                        # visible set -- the layout explicitly says never
                        # show it. Falls through with no value set, same
                        # as any other layout-hidden, unresolved attr
                        # (the final ask/skip decision below correctly
                        # skips it, since it's neither a decision attr
                        # nor a grid selector).
                        pass
                    elif not (
                        _no_real_fill_justification(attr, scope.rec_by_target)
                        and vn not in _BLIND_FILL_RISK_ACCEPTED_VNS
                    ):
                        # single/boolean, 2+ options, no default: first by
                        # menu order — well-defined for boolean (only two
                        # states) and safe here because a rule REQUIRES this
                        # attr to be resolved for the cascade to proceed.
                        value = valid_opts[0].item_value
                        display = valid_opts[0].display_name
                        source = governed_source
                    # else: nothing above (rec/data-table/confirmed-
                    # default) justified a value for this specific,
                    # confirmed-no-real-basis attr -- leave unset
                    # rather than guess first-by-order, same principle
                    # as the multi-select guard below.
            # else: 0 or 2+ options, ungoverned → pending (user must choose)
        elif (
            not value and is_governed and not is_decision_attr
            and attr.select_type == "boolean" and scope.display_order is None
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
            return
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
                ctx.filled_multi[vn] = [value]
            else:
                ctx.filled[vn] = value
            ctx.display_filled[vn] = display or value
            ctx.sources.setdefault(vn, source)
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
            and vn not in scope.grid_selector_vns
            and _no_real_fill_justification(attr, scope.rec_by_target)
            and vn not in _BLIND_FILL_RISK_ACCEPTED_VNS
            and (opt_out_match := _sole_opt_out_option(
                [o for o in attr.options if _valid(o.item_value)]
            ))
        ):
            # Same "the menu itself declares a safe opt-out" case as
            # the single-select branch above, just for multi-select's
            # separate fallback (valid_opts isn't reliably in scope
            # here -- see the sibling elif's own comment on that).
            ctx.filled_multi[vn] = [opt_out_match.item_value]
            ctx.display_filled[vn] = opt_out_match.display_name
            ctx.sources.setdefault(vn, "opt_out_default")
            filled_multi_now = True
        elif (
            attr.select_type == "multi" and not attr.required
            and vn not in scope.grid_selector_vns
            and vn in _OPTIONAL_EMPTY_FILL_ACCEPTED_VNS
            and allowed_for_attr is None
        ):
            # Confirmed genuinely optional (Attrsequence: 0 Required
            # rows) with no menu-declared opt-out option for
            # _sole_opt_out_option to find -- "select nothing" is
            # itself the real, valid answer here, distinct from the
            # blind-pick-one-real-option fallback a few lines below.
            # `allowed_for_attr is None` (truly unconstrained) guards
            # this from ever overriding a REAL active constraint's own
            # narrowed set -- a constrained-but-ambiguous case for one
            # of these three attrs must still select-all from the
            # narrowed candidates via the sibling mechanism upstream,
            # never resolve to empty just because the attr's name is
            # in this allowlist (confirmed live: without this guard,
            # this branch wrongly intercepted promoApplicationServices_
            # astro's own constrained-and-ambiguous regression test).
            ctx.filled_multi[vn] = []
            ctx.display_filled[vn] = "(none)"
            ctx.sources.setdefault(vn, "optional_empty")
            filled_multi_now = True
        elif (
            attr.select_type == "multi" and not attr.required
            and vn not in scope.grid_selector_vns
            and not (
                _no_real_fill_justification(attr, scope.rec_by_target)
                and vn not in _BLIND_FILL_RISK_ACCEPTED_VNS
            )
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
            is_unconstrained = attr.entity_id not in (scope.constrained_opts or {})
            current_allowed = (
                set(scope.constrained_opts.get(attr.entity_id, []))
                if scope.constrained_opts else None
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
                scope.satisfied_recommendation(attr, candidate_opts)
                if scope.rec_by_target else None
            )
            default_opt = next(
                (o for o in candidate_opts if o.item_value == attr.default_value),
                None,
            ) if attr.default_value else None
            if rec_match:
                rec_value, rec_display, fired_rule_name = rec_match
                ctx.filled_multi[vn] = [rec_value]
                ctx.display_filled[vn] = rec_display
                ctx.sources.setdefault(vn, "rule")
                # §2e: this multi-select path never traced its fill at
                # all before — a real, separate gap from the
                # single-select trace call above, closed the same way.
                rule_trace.record_fire(
                    rule_type="recommendation", rule_id=fired_rule_name,
                    attr=vn, outcome=f"set={rec_value}",
                )
            elif scope.display_order is not None and not (
                is_unconstrained and candidate_opts
                and (attr.entity_id in scope.rule_governed or vn in scope.dt_governed_vns)
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
                # False): 2026-08-18 explicit override (HITL-confirmed
                # after the "never guess among rule-narrowed options"
                # rationale was re-cited in full) -- select ALL options
                # a real rule has currently narrowed this attr to,
                # instead of leaving it empty. Distinct from the
                # single-select blind-fill override above (which picks
                # ONE first-eligible value): for multi-select the
                # requested behavior is "check every currently-allowed
                # box", not "guess one of them". `candidate_opts` here
                # is already filtered to `current_allowed` (the real
                # constraint's narrowed set) a few lines up, so this
                # never selects an option the active rule has excluded.
                if candidate_opts:
                    ctx.filled_multi[vn] = [o.item_value for o in candidate_opts]
                    ctx.display_filled[vn] = ", ".join(
                        o.display_name for o in candidate_opts)
                    ctx.sources.setdefault(vn, "auto_all_constrained")
                    logger.info(
                        "cpq: multi-select %r constrained to %d option(s) "
                        "with no rule/default resolving a subset -- "
                        "auto-selected all of them instead of leaving "
                        "empty (2026-08-18 override of the prior "
                        "leave-empty default)", vn, len(candidate_opts),
                    )
            elif default_opt:
                ctx.filled_multi[vn] = [default_opt.item_value]
                ctx.display_filled[vn] = default_opt.display_name
                ctx.sources.setdefault(vn, "default")
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
                    engine._resolve_narrowed_legal_values(
                        vn, ctx.filled, scope.workspace_id, scope.catalog_prefix, ctx.dt_cache,
                    )
                    if scope.workspace_id is not None else None
                )
                _narrowed_opts = (
                    [o for o in candidate_opts if o.item_value in _dt_legal]
                    if _dt_legal is not None else candidate_opts
                )
                if _narrowed_opts:
                    if vn in _SELECT_ALL_NARROWED_LEGAL_MULTI_VNS:
                        # Live-confirmed (2026-08-16): native CPQ UI
                        # checks EVERY Whitelist-confirmed-legal option
                        # by default for these specific attrs (real-
                        # world meaning is "which of these does this
                        # unit support", e.g. Frequency Band coverage)
                        # -- picking only _narrowed_opts[0] silently
                        # dropped 2 of 3 real, legal, native-UI-checked
                        # values (modelSelectionFrequencyBandMsl_astro:
                        # only '700/800 MHZ' ever reached the payload,
                        # never 'VHF'/'UHF'). Deliberately a narrow,
                        # named allowlist, NOT a blanket change to this
                        # branch -- carrierSelectionMultiSelect_astro
                        # hits this exact same code path and genuinely
                        # needs the OPPOSITE behavior (native UI leaves
                        # it unresolved/"Invalid selection" rather than
                        # auto-checking every legal carrier), so
                        # defaulting to "select all" here for every
                        # attr would be a regression, not a fix.
                        ctx.filled_multi[vn] = [o.item_value for o in _narrowed_opts]
                        ctx.display_filled[vn] = ", ".join(
                            o.display_name for o in _narrowed_opts)
                        ctx.sources.setdefault(vn, "default_first_available")
                    else:
                        first_opt = _narrowed_opts[0]
                        ctx.filled_multi[vn] = [first_opt.item_value]
                        ctx.display_filled[vn] = first_opt.display_name
                        ctx.sources.setdefault(vn, "default_first_available")
                else:
                    # Real Data Table confirms ZERO legal values for
                    # this exact context (`_dt_legal == []`) -- a
                    # genuine, data-proven answer, not something to
                    # guess past. Same empty outcome as the sibling
                    # `else` below, reached here instead since
                    # `is_unconstrained and candidate_opts` already
                    # matched on the raw (pre-whitelist) option list.
                    ctx.filled_multi[vn] = []
                    ctx.display_filled[vn] = "(none)"
                    ctx.sources.setdefault(vn, "default")
            else:
                ctx.filled_multi[vn] = []
                ctx.display_filled[vn] = "(none)"
                ctx.sources.setdefault(vn, "default")
        elif engine._is_noise_var(vn) and attr.options:
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
                ctx.filled[vn] = fallback.item_value
                ctx.display_filled[vn] = fallback.display_name
                ctx.sources.setdefault(vn, "default")
        elif (
            (attr.options or is_decision_attr
             or engine.should_ask_free_text_attr(attr, scope.validation_rules, scope.bml_eval))
            and not engine._is_noise_var(vn)
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
                vn in (scope.skip_always_ask or ())
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
            if is_decision_attr or vn in scope.grid_selector_vns:
                # Forced-ask anchors (Country/Region/Hardware Version/
                # Product) and grid-linked selectors are never auto-
                # fillable -- always ask regardless of rule governance
                # or data gaps below. Unchanged from before this fix.
                # Checked FIRST, ahead of _dt_governed_vns below, same
                # priority order the pre-existing final `elif` used to
                # enforce before this restructuring.
                ctx.pending.append(attr)
            elif (
                attr.entity_id in scope.missing_data_target_ids
                or attr.source_id in scope.missing_data_target_ids
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
            elif vn in scope.dt_governed_vns and (
                scope.display_order is None or vn in scope.display_order
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
                    set(scope.constrained_opts[attr.entity_id])
                    if scope.constrained_opts and attr.entity_id in scope.constrained_opts
                    else None
                )
                _blind_opts = [
                    o for o in attr.options
                    if _valid(o.item_value)
                    and (_blind_allowed is None or o.item_value in _blind_allowed)
                ]
                if _blind_opts:
                    _blind_first = _blind_opts[0]
                    ctx.filled[vn] = _blind_first.item_value
                    ctx.display_filled[vn] = _blind_first.display_name
                    ctx.sources.setdefault(vn, "blind_pick_governed")
                else:
                    ctx.pending.append(attr)
            elif (
                attr.entity_id in scope.rule_governed
                and attr.select_type != "multi"
                and vn not in _NEVER_GUESS_SCRIPT_GOVERNED
                and attr.entity_id not in ctx.user_answered_dropped_ids
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
                    set(scope.constrained_opts[attr.entity_id])
                    if scope.constrained_opts and attr.entity_id in scope.constrained_opts
                    else None
                )
                _rg_opts = [
                    o for o in attr.options
                    if _valid(o.item_value)
                    and (_rg_allowed is None or o.item_value in _rg_allowed)
                ]
                if _rg_opts:
                    _rg_first = _rg_opts[0]
                    ctx.filled[vn] = _rg_first.item_value
                    ctx.display_filled[vn] = _rg_first.display_name
                    ctx.sources.setdefault(vn, "blind_pick_rule_governed")
                else:
                    ctx.pending.append(attr)
            elif (
                scope.display_order is None
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
                or (vn in scope.display_order and scope.dt_never_governed_anywhere(vn))
            ):
                ctx.pending.append(attr)
