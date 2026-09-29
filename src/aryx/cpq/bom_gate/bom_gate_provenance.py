"""Provenance check: every filled value must be catalog-backed or utterance-backed.

Split out of `cpq/bom_gate.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). `check_provenance` is directly imported by
`tests/test_cpq_negative_harden.py` (bare-name import, not patched) —
confirmed via grep.
"""
from __future__ import annotations

from aryx.cpq.bom_gate.bom_gate_noise import _is_noise_var, _SYNTHETIC_ENGINE_VARS
from aryx.cpq.state import ConfigAttr, CpqSession

# Sources that count as user-confirmed (may keep free-text / none-like codes).
_USER_LIKE_SOURCES = frozenset({"user", "hint", "cascade"})


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
        # CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T7: a customer's own
        # deliberate clear (empty string, source="user") on an OPTIONAL
        # attr is a legitimate, already-established outcome elsewhere in
        # the engine — auto_fill_stages/tier0_already_filled.py's own
        # "not attr.required" branch already accepts it (displayed as
        # "(none)", marked done) — this check never got the matching
        # carve-out, so the exact same value it just accepted upstream
        # was still hard-blocked here at confirm. A required attr's
        # empty clear is intentionally NOT covered — tier0's own sibling
        # branch pops it back to pending instead of accepting it, so an
        # empty required value reaching here is a genuine gap, not a
        # deliberate clear.
        if iv == "" and source == "user" and attr is not None and not attr.required:
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
        if _is_noise_var(vn) or vn in _SYNTHETIC_ENGINE_VARS:
            continue
        attr = by_vn.get(vn)
        source = session.filled_source.get(vn, "")
        display = session.display_filled.get(vn, "")
        if not _ok(attr, iv, source, display):
            errors.append(
                f"{vn}={iv!r} source={source!r} failed provenance "
                f"(not a catalog option / no user utterance)"
            )

    for vn, values in session.filled_multi.items():
        if _is_noise_var(vn) or vn in _SYNTHETIC_ENGINE_VARS:
            continue
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
