"""Final BOM gate — constraint re-check + provenance hard-fail.

Before any Step-8 payload is returned to the client:
1. Re-run constraint rules against the filled config.
2. Every {variable_name: item_value} must trace to a catalog option
   (DB-backed ConfigAttr.options from Postgres/FalkorDB load) OR a
   confirmed user/hint source with utterance evidence.
3. On failure: hard-fail with a catch message — never emit the payload.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from aryx.cpq.state import ConfigAttr, CpqSession

logger = logging.getLogger(__name__)

# Sources that count as user-confirmed (may keep free-text / none-like codes).
_USER_LIKE_SOURCES = frozenset({"user", "hint", "cascade"})


def _is_noise_var(variable_name: str) -> bool:
    """True for underscore-prefixed or integration/system-prefixed vars --
    same structural check as CpqEngine._is_noise_var (engine.py), duplicated
    here rather than imported to avoid a bom_gate<->engine import coupling.

    Confirmed live (2026-08-09): a real catalog's `required=True` flag on
    attrs like `_price_book_var_name`/`_BM_USER_CURRENCY`/`_BM_USER_GROUPS`/
    `_BM_USER_LANGUAGE`/`_BM_USER_NUMBER_FORMAT`/`_configOperationContext`
    reflects Oracle CPQ's own account/session-context integration -- these
    are populated by the calling CRM/account layer, never by product
    configuration, and are already excluded from the real BOM payload
    (build_payload's own `_is_noise_var` check) and never asked in
    conversation (auto_fill's own `_is_noise_var` check). Without this same
    exclusion here, `find_missing_required_fields` wrongly reported them as
    "missing required data" and blocked completion on fields Aryx was never
    going to fill by design.
    """
    if variable_name.startswith("_"):
        return True
    head = variable_name.split("_", 1)[0]
    return len(head) >= 2 and head.isalpha() and head.isupper()


@dataclass
class StaleConstraintViolation:
    """A filled attr whose value no longer satisfies the freshly recomputed
    constraint. Auto-clearable — unlike a provenance failure, the engine
    knows exactly what's wrong (this value isn't in `allowed` anymore) but
    can't guess the right replacement, so the caller re-asks rather than
    silently picking one or hard-blocking (docs/
    CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md §4.1 — same "never guess"
    reasoning already established for this class of issue elsewhere)."""

    attr: ConfigAttr
    current_value: str
    allowed: list[str]


@dataclass
class BomGateResult:
    ok: bool
    errors: list[str]
    stale_violations: list[StaleConstraintViolation] = field(default_factory=list)
    catch_message: str = ""


def _value_in_options(attr: ConfigAttr | None, item_value: str) -> bool:
    if attr is None:
        return False
    if not attr.options:
        # Free-text attr: no menu to validate against — require user-like source.
        return False
    return any(o.item_value == item_value for o in attr.options)


def _utterance_mentions(session: CpqSession, display: str, item_value: str) -> bool:
    """True if a recent user utterance contains the display or code."""
    needles = [s for s in (display, item_value) if s]
    if not needles:
        return False
    for utt in session.recent_utterances:
        u = utt.lower()
        if any(n.lower() in u for n in needles if n):
            return True
    return False


def recheck_constraints(
    engine: Any,
    attrs: list[ConfigAttr],
    session: CpqSession,
    con_rules: list,
    bml_eval: Any,
) -> list[StaleConstraintViolation]:
    """Re-run constraint rules; return attrs whose filled value no longer
    satisfies the freshly recomputed allowed set. Raises on an unexpected
    engine error — the caller (`validate_before_payload`) decides how to
    handle that, this function never silently swallows one.

    docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §9 — this
    previously called `engine.apply_constraint_rules(attrs, session.filled,
    con_rules, ...)`, i.e. (attrs, filled, rules), then unpacked the result
    as a 2-tuple. The real signature is `(attrs, rules, filled, bml_eval=None)
    -> dict[int, list[str]]` — a SINGLE dict of {entity_id: [allowed
    item_values]}, no messages of its own. `session.filled` (a dict) landed
    in the `rules` parameter, `for rule in rules:` iterated its keys (plain
    strings), and `rule.target_attr_id` crashed every confirm with an active
    constraint rule. Every other call site in the codebase (ask_api.py,
    engine.py) already uses the correct order and treats the return as a
    plain dict — this was the only outlier.

    docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §11 — once this
    was actually reachable (rather than crash-and-swallowed), live traffic
    showed real, legitimate hits: an independent mechanism
    (`find_rule_inconsistencies`, ask_api.py) already logs this exact same
    class of issue and — per docs/CPQ_RULE_CONSISTENCY_VALIDATION_PLAN.md
    §4.1 — deliberately does NOT hard-fail on it, since the engine can't be
    sure what the correct replacement value is. Returns structured
    violations (not messages) so the caller can auto-clear + re-ask rather
    than hard-block confirm.

    docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §12 — two review
    findings fixed: (1) this used to swallow ANY exception and return `[]`
    ("no violations"), which would fail OPEN — a genuine, unexpected engine
    error looked identical to "config is fine." Now propagates; the caller
    treats an exception as a hard-fail, same fail-closed discipline as
    `check_provenance`. (2) multi-select attrs (`select_type == "multi"`)
    were invisible to this check entirely — it only ever read
    `session.filled`, never `session.filled_multi`. Now checks both.
    """
    if not con_rules:
        return []
    constrained = engine.apply_constraint_rules(
        attrs, con_rules, session.filled, bml_eval=bml_eval, filled_multi=session.filled_multi,
    )
    if not constrained:
        return []
    by_eid = {a.entity_id: a for a in attrs}
    violations: list[StaleConstraintViolation] = []
    for entity_id, allowed in constrained.items():
        attr = by_eid.get(entity_id)
        if attr is None:
            continue
        if attr.select_type == "multi":
            current_multi = session.filled_multi.get(attr.variable_name)
            if not current_multi:
                continue
            invalid = [v for v in current_multi if v not in allowed]
            if invalid:
                violations.append(
                    StaleConstraintViolation(attr, ", ".join(invalid), allowed),
                )
            continue
        current = session.filled.get(attr.variable_name)
        if current is not None and current not in allowed:
            violations.append(StaleConstraintViolation(attr, current, allowed))
    return violations


def find_missing_required_fields(
    attrs: list[ConfigAttr], session: CpqSession,
) -> list[ConfigAttr]:
    """Every currently-visible attribute the catalog itself marks
    `required=True` that has no value at all -- in `session.filled` for a
    single-select/free-text attr, or a non-empty list in
    `session.filled_multi` for a multi-select.

    Confirmed live (2026-08-08): docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.
    md §2c's "only ask decision-attr anchors, skip everything else that
    nothing upstream resolved" behavior is deliberate (its own comment:
    "per your explicit call") -- but nothing anywhere ever checked whether
    one of those silently-skipped attrs was actually `required` before
    declaring the configuration "complete". This is a pure completeness
    check, independent of WHY an attr wasn't filled (§2c's skip, a rule
    that never fired, anything else) -- it never touches or second-guesses
    what §2c itself decides to ask or skip.

    `attrs` is the caller's currently-visible attribute list (post hiding-
    rule filtering) -- a required attr an active hiding rule has removed
    from view is never flagged; the catalog's own rules already say it
    doesn't apply here.

    Noise-shaped integration/system attrs (`_is_noise_var`, e.g. Price
    Book/User Currency/User Groups/User Language/User Number Format/Config
    Operation Context) are excluded even when `required=True` -- these are
    populated by the calling CRM/account layer, never by product
    configuration or by this engine, matching the same exclusion every
    other real-BOM-facing path (auto_fill, build_payload) already applies.
    """
    missing: list[ConfigAttr] = []
    for attr in attrs:
        if not attr.required:
            continue
        vn = attr.variable_name
        if _is_noise_var(vn):
            continue
        if attr.select_type == "multi":
            if session.filled_multi.get(vn):
                continue
        elif session.filled.get(vn):
            continue
        missing.append(attr)
    return missing


def check_provenance(
    attrs: list[ConfigAttr],
    session: CpqSession,
) -> list[str]:
    """Every filled value must be catalog-backed or utterance-backed."""
    by_vn = {a.variable_name: a for a in attrs}
    errors: list[str] = []

    def _ok(attr: ConfigAttr | None, iv: str, source: str, display: str) -> bool:
        # N7: any value that is a real catalog option is always provenanced
        # (DB-backed from load_product_config) — no utterance required.
        if _value_in_options(attr, iv):
            return True
        # Engine-derived free-text (cascade/rule/default/auto) is trusted
        # when the attr has no menu — never an LLM free invention path.
        if source in ("cascade", "rule", "default", "auto"):
            if attr is None or not attr.options:
                return True
            # Menu attr with non-option value from cascade/rule is invalid.
            return False
        # Free-text attr + user/hint — no utterance required (typed answers).
        if attr is not None and not attr.options and source in _USER_LIKE_SOURCES:
            return True
        # User/hint with utterance evidence (covers paraphrased menu labels).
        if source in _USER_LIKE_SOURCES and _utterance_mentions(session, display, iv):
            return True
        return False

    for vn, iv in session.filled.items():
        attr = by_vn.get(vn)
        source = session.filled_source.get(vn, "")
        display = session.display_filled.get(vn, "")
        if not _ok(attr, iv, source, display):
            errors.append(
                f"{vn}={iv!r} source={source!r} failed provenance "
                f"(not a catalog option / no user utterance)"
            )

    for vn, values in session.filled_multi.items():
        attr = by_vn.get(vn)
        source = session.filled_source.get(vn, "user")
        for iv in values:
            display = next(
                (o.display_name for o in (attr.options if attr else [])
                 if o.item_value == iv),
                session.display_filled.get(vn, iv),
            )
            if not _ok(attr, iv, source, display):
                errors.append(
                    f"{vn} multi value {iv!r} failed provenance "
                    f"(not in catalog options / no utterance)"
                )
    return errors


def validate_before_payload(
    engine: Any,
    attrs: list[ConfigAttr],
    session: CpqSession,
    con_rules: list,
    bml_eval: Any,
) -> BomGateResult:
    """Full Step-8 gate. ok=False → never emit payload.

    Two distinct failure classes, deliberately handled differently
    (docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §11):
    - Provenance failures (an invented/hallucinated value with no catalog
      or utterance backing) are a real integrity problem — hard-fail,
      same as always.
    - Stale constraint violations (a real, previously-valid value that a
      later selection has now made invalid) are NOT hard-failed — the
      caller auto-clears and re-asks instead, since the engine knows
      what's wrong but not what the replacement should be.

    An unexpected error DURING the constraint recheck itself (§12) is a
    third case, deliberately treated as a hard fail — same "never guess"
    discipline as a provenance failure, not silently treated as "no
    violations found."

    A fourth case, added 2026-08-08: a currently-visible attr the catalog
    marks `required` with no value at all — confirmed live, this could
    previously reach this gate with no check catching it at all (docs/
    CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md §2c's ask/skip behavior can
    leave a required, non-decision attr silently unfilled). Hard-failed,
    same as provenance — the engine has no value to guess from here either.
    """
    missing_required = find_missing_required_fields(attrs, session)
    if missing_required:
        labels = [
            f"{a.display_label} ({a.variable_name})" for a in missing_required
        ]
        logger.warning(
            "bom_gate: MISSING REQUIRED run_id=%s fields=%s",
            session.run_id or "-", [a.variable_name for a in missing_required],
        )
        catch = (
            "⚠️ **Configuration gate blocked the BOM payload.**\n\n"
            "The following required fields have no value: "
            + ", ".join(f"**{l}**" for l in labels)
            + ".\n\nNo payload was emitted. Provide these fields, or say "
            "**undo** to restore the previous snapshot."
        )
        return BomGateResult(
            ok=False,
            errors=[f"missing required: {a.variable_name}" for a in missing_required],
            catch_message=catch,
        )
    try:
        stale = recheck_constraints(engine, attrs, session, con_rules, bml_eval)
    except Exception as exc:  # noqa: BLE001
        logger.warning("bom_gate: constraint recheck failed: %r", exc)
        catch = (
            "⚠️ **Configuration gate blocked the BOM payload.**\n\n"
            f"Constraint verification failed unexpectedly ({exc}) — "
            "this can't be verified as valid, so nothing was emitted.\n\n"
            "Try **confirm** again, or say **undo** to restore the "
            "previous snapshot."
        )
        return BomGateResult(
            ok=False, errors=[f"constraint recheck error: {exc}"],
            catch_message=catch,
        )
    errors = check_provenance(attrs, session)

    if errors:
        logger.warning(
            "bom_gate: HARD FAIL run_id=%s errors=%s",
            session.run_id or "-", errors[:10],
        )
        catch = (
            "⚠️ **Configuration gate blocked the BOM payload.**\n\n"
            "One or more values could not be verified against the catalog "
            "or your stated answers:\n"
            + "\n".join(f"- {e}" for e in errors[:8])
            + "\n\nNo payload was emitted. Fix the fields above, or say "
            "**undo** to restore the previous snapshot."
        )
        return BomGateResult(ok=False, errors=errors, catch_message=catch)

    if stale:
        logger.info(
            "bom_gate: STALE CONSTRAINT run_id=%s attrs=%s",
            session.run_id or "-", [v.attr.variable_name for v in stale],
        )
        return BomGateResult(ok=False, errors=[], stale_violations=stale)

    logger.info("bom_gate: PASS run_id=%s fields=%d",
                session.run_id or "-", len(session.filled) + len(session.filled_multi))
    return BomGateResult(ok=True, errors=[])
