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
from dataclasses import dataclass
from typing import Any

from aryx.cpq.state import ConfigAttr, CpqSession

logger = logging.getLogger(__name__)

# Sources that count as user-confirmed (may keep free-text / none-like codes).
_USER_LIKE_SOURCES = frozenset({"user", "hint", "cascade"})


@dataclass
class BomGateResult:
    ok: bool
    errors: list[str]
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
) -> list[str]:
    """Re-run constraint rules; return human-readable violation messages."""
    if not con_rules:
        return []
    try:
        _allowed, messages = engine.apply_constraint_rules(
            attrs, session.filled, con_rules, bml_eval=bml_eval,
        )
        # messages is typically list[str] of constraint prompts/violations
        if not messages:
            return []
        if isinstance(messages, list):
            return [str(m) for m in messages if m]
        return [str(messages)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("bom_gate: constraint recheck failed: %r", exc)
        return [f"constraint recheck error: {exc}"]


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
    """Full Step-8 gate. ok=False → never emit payload."""
    errors: list[str] = []
    errors.extend(recheck_constraints(engine, attrs, session, con_rules, bml_eval))
    errors.extend(check_provenance(attrs, session))

    if errors:
        logger.warning(
            "bom_gate: HARD FAIL run_id=%s errors=%s",
            session.run_id or "-", errors[:10],
        )
        catch = (
            "⚠️ **Configuration gate blocked the BOM payload.**\n\n"
            "One or more values could not be verified against the catalog "
            "or your stated answers (or a constraint still fires):\n"
            + "\n".join(f"- {e}" for e in errors[:8])
            + "\n\nNo payload was emitted. Fix the fields above, or say "
            "**undo** to restore the previous snapshot."
        )
        return BomGateResult(ok=False, errors=errors, catch_message=catch)

    logger.info("bom_gate: PASS run_id=%s fields=%d",
                session.run_id or "-", len(session.filled) + len(session.filled_multi))
    return BomGateResult(ok=True, errors=[])
