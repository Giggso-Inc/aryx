#!/usr/bin/env python3
"""cpq-regression — replay CPQ_REGRESSION_SUITE.md as a push-time gate.

Parses the 50+50 markdown suite and enforces, offline (no LLM):

  1. >= 50 positive and >= 50 negative cases present
  2. every expected_intent is a valid IntentCategory enum value
  3. `check` column assertions:
       quote     — soft_quote_heuristic mirror
       off_topic — hard_off_topic mirror
       undo      — session_guard.detect_undo
       guided    — session_guard.detect_guided_mode_accept
       none      — schema-label validation only
  4. gateway quarantine / session_guard snapshot invariants
  5. multi-turn Dialogues (D##) — offline handlers with conversational
     invariant (no orphan questions)

`--live` additionally replays every single-turn case through the gateway.

Exit 0 pass, 1 regression. Wire into `make cpq-regression` and the pre-push
hook so every push replays the suite.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger("cpq_regression")

HERE = Path(__file__).resolve().parent
SUITE = HERE / "CPQ_REGRESSION_SUITE.md"

sys.path.insert(0, str(HERE))
from run_bench import (  # noqa: E402 — reuse loader + invariants
    _check_gateway_quarantine_invariants,
    _check_session_guard_snapshot,
    _load_mod,
)

_ROW = re.compile(r"^\|\s*(?P<id>[PN]\d{2})\s*\|")
_DIALOGUE_HEAD = re.compile(r"^###\s+(?P<id>D\d{2})\s*[—\-–]\s*(?P<title>.+)$")
_TURN_ROW = re.compile(r"^\|\s*(?P<turn>\d+)\s*\|")
_CHECKS = frozenset({"quote", "off_topic", "undo", "guided", "none"})

# Mirrors of intent_gateway._SOFT_QUOTE /._OFF_TOPIC_HARD — duplicated so the
# offline gate never imports the LLM/psycopg stack. Pinned byte-for-byte to
# the real ones by tests/test_cpq_regression_suite.py.
SOFT_QUOTE = re.compile(
    r"\b(order|configure|config|quote|qty|quantity|radios?|"
    r"destination\s+country|hardware\s+version|bom|apx|svx|"
    r"command\s*central|service\s+type)\b", re.IGNORECASE)
OFF_TOPIC = re.compile(
    r"\b(astrolog(?:y|ical)?|horoscope|zodiac|tarot|"
    r"weather|forecast|world\s*cup|tell\s+me\s+a\s+joke|knock[\s-]knock)\b",
    re.IGNORECASE)


def parse_suite(path: Path = SUITE) -> list[dict[str, str]]:
    """Parse the single-turn markdown tables into case dicts."""
    cases: list[dict[str, str]] = []
    for line in path.read_text().splitlines():
        if not _ROW.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            raise ValueError(f"bad row (need 5 cells): {line!r}")
        cid, question, intent, vn, check = cells
        # Skip dialogue turn rows (turn | user | expect) which also match
        # a 3-cell-ish shape — only accept P##/N## ids.
        if not re.match(r"^[PN]\d{2}$", cid):
            continue
        cases.append({
            "id": cid,
            "question": question,
            "expected_intent": intent,
            "expected_vn": "" if vn == "-" else vn,
            "check": check,
        })
    return cases


def parse_dialogues(path: Path = SUITE) -> list[dict]:
    """Parse ## Dialogues section into multi-turn scripts.

    Format under ``### D## — title``:

    | turn | user | expect |
    |------|------|--------|
    | 1 | change hardware | pending_clarify;question;not_nudge |
    """
    dialogues: list[dict] = []
    current: dict | None = None
    in_dialogues = False
    for line in path.read_text().splitlines():
        if re.match(r"^##\s+Dialogues\b", line, re.IGNORECASE):
            in_dialogues = True
            continue
        if in_dialogues and re.match(r"^##\s+", line) and not re.match(
            r"^##\s+Dialogues\b", line, re.IGNORECASE,
        ):
            in_dialogues = False
            current = None
            continue
        if not in_dialogues:
            continue
        m = _DIALOGUE_HEAD.match(line.strip())
        if m:
            current = {
                "id": m.group("id"),
                "title": m.group("title").strip(),
                "turns": [],
            }
            dialogues.append(current)
            continue
        if current is None or not _TURN_ROW.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        turn_s, user, expect = cells[0], cells[1], cells[2]
        if turn_s.lower() == "turn" or not turn_s.isdigit():
            continue
        current["turns"].append({
            "turn": int(turn_s),
            "user": user,
            "expect": expect,
        })
    return dialogues


def run_offline(cases: list[dict[str, str]]) -> list[str]:
    """All non-LLM single-turn assertions. Returns error strings (empty = pass)."""
    errors: list[str] = []

    pos = [c for c in cases if c["id"].startswith("P")]
    neg = [c for c in cases if c["id"].startswith("N")]
    if len(pos) < 50:
        errors.append(f"suite has {len(pos)} positive cases, need >= 50")
    if len(neg) < 50:
        errors.append(f"suite has {len(neg)} negative cases, need >= 50")
    dupes = {c["id"] for c in cases if sum(1 for x in cases if x["id"] == c["id"]) > 1}
    if dupes:
        errors.append(f"duplicate ids: {sorted(dupes)}")

    schema = _load_mod("aryx.cpq.intent_schema", "aryx/cpq/intent_schema.py")
    known = {c.value for c in schema.IntentCategory}
    _load_mod("aryx.cpq.state", "aryx/cpq/state.py")
    guard = _load_mod("aryx.cpq.session_guard", "aryx/cpq/session_guard.py")
    soft_quote, off_topic = SOFT_QUOTE, OFF_TOPIC

    for c in cases:
        cid, q = c["id"], c["question"]
        if c["expected_intent"] not in known:
            errors.append(f"{cid}: unknown intent {c['expected_intent']!r}")
        chk = c["check"]
        if chk not in _CHECKS:
            errors.append(f"{cid}: unknown check {chk!r}")
        elif chk == "quote" and not soft_quote.search(q):
            errors.append(f"{cid}: soft_quote_heuristic missed {q!r}")
        elif chk == "off_topic" and not off_topic.search(q):
            errors.append(f"{cid}: hard_off_topic missed {q!r}")
        elif chk == "undo" and not guard.detect_undo(q):
            errors.append(f"{cid}: detect_undo missed {q!r}")
        elif chk == "guided" and not guard.detect_guided_mode_accept(q):
            errors.append(f"{cid}: detect_guided_mode_accept missed {q!r}")

    errors.extend(_check_gateway_quarantine_invariants())
    errors.extend(_check_session_guard_snapshot())
    return errors


def _expect_tokens(expect: str) -> set[str]:
    return {t.strip().lower() for t in expect.split(";") if t.strip()}


def _check_expect(
    expect: str,
    *,
    answer: str,
    session: object,
    guard: object,
    resolved_vn: str | None = None,
) -> list[str]:
    """Validate a dialogue turn's expect tokens against answer + session."""
    errs: list[str] = []
    tokens = _expect_tokens(expect)
    sd = session.to_dict()  # type: ignore[attr-defined]
    answer_l = (answer or "").lower()

    if "pending_clarify" in tokens and not sd.get("pending_clarify_vns"):
        errs.append("expected pending_clarify_vns set")
    if "not_pending_clarify" in tokens and sd.get("pending_clarify_vns"):
        errs.append("expected pending_clarify_vns cleared")
    if "pending_no_value" in tokens and not sd.get("pending_change_no_value_vn"):
        errs.append("expected pending_change_no_value_vn set")
    if "pending_switch" in tokens and not (
        sd.get("pending_switch_product") or sd.get("pending_switch_question")
    ):
        errs.append("expected pending_switch_* set")
    if "question" in tokens and "?" not in (answer or ""):
        errs.append("expected answer to contain a question mark")
    if "not_nudge" in tokens and "didn't quite catch that" in answer_l:
        errs.append("answer is the generic review nudge")
    if "not_misbind" in tokens and resolved_vn is not None:
        errs.append(f"unrelated reply mis-bound to {resolved_vn!r}")
    if "vn=hWVersion_astro" in tokens:
        got = sd.get("pending_change_no_value_vn") or resolved_vn
        if got != "hWVersion_astro":
            errs.append(f"expected hWVersion_astro, got {got!r}")

    # Conversational invariant: config question ⇒ consumable pending
    if "invariant" in tokens or "question" in tokens:
        violations = guard.assert_conversational_invariant(  # type: ignore[attr-defined]
            answer, sd, run_id=sd.get("run_id") or "dialogue", log=False,
        )
        if violations:
            errs.extend(violations)

    return errs


def run_dialogues_offline(dialogues: list[dict] | None = None) -> list[str]:
    """Replay multi-turn D## scripts offline (no LLM / no ask_api).

    Handlers implement the clarify-memory and switch-confirm contracts that
    the live path uses, so a push-time regression catches amnesia bugs.
    """
    dialogues = dialogues if dialogues is not None else parse_dialogues()
    errors: list[str] = []
    if not dialogues:
        errors.append("no D## dialogues found in suite (need >= 1)")
        return errors

    _load_mod("aryx.cpq.state", "aryx/cpq/state.py")
    state = sys.modules["aryx.cpq.state"]
    guard = _load_mod("aryx.cpq.session_guard", "aryx/cpq/session_guard.py")

    # Catalog stubs for offline clarify resolution
    HW = ("hWVersion_astro", "Hardware Version")
    SK = ("systemKey_astro", "System Key")
    CANDIDATES = [HW, SK]

    for d in dialogues:
        did = d["id"]
        if not d.get("turns"):
            errors.append(f"{did}: no turns defined")
            continue
        session = state.CpqSession(
            product_name="aSTRO25_bom",
            status="awaiting_approval",
            run_id=f"dlg-{did}",
        )
        session.filled = {
            "hWVersion_astro": "APX NEXT (4G LTE Only)",
            "systemKey_astro": "Key A",
        }
        session.display_filled = dict(session.filled)
        session.turn = 0

        for t in d["turns"]:
            session.turn += 1
            user = t["user"]
            expect = t["expect"]
            answer = ""
            resolved_vn: str | None = None

            # ── Offline handler by dialogue id / expect tokens ──────────
            if did == "D01":
                # clarify → resolve Hardware Version → no-value pending
                if not session.pending_clarify_vns and "change hardware" in user.lower():
                    session.pending_clarify_vns = [HW[0], SK[0]]
                    session.pending_clarify_question = user
                    session.pending_clarify_prompt = guard.numbered_attr_pick_prompt(
                        CANDIDATES,
                    )
                    session.pending_clarify_asked_turn = session.turn
                    session.pending_clarify_misses = 0
                    answer = session.pending_clarify_prompt
                elif session.pending_clarify_vns:
                    resolved_vn = guard.match_clarify_reply_offline(
                        user, CANDIDATES,
                    )
                    if resolved_vn:
                        session.pending_clarify_vns = []
                        session.pending_clarify_question = ""
                        session.pending_clarify_prompt = ""
                        session.pending_clarify_asked_turn = 0
                        session.pending_clarify_misses = 0
                        session.pending_change_no_value_vn = resolved_vn
                        label = dict(CANDIDATES).get(resolved_vn, resolved_vn)
                        answer = (
                            f"Which value would you like for **{label}**?\n\n"
                            f"1. APX NEXT (4G LTE Only)\n"
                            f"2. APX NEXT (4G LTE+5G)"
                        )
                    else:
                        session.pending_clarify_misses += 1
                        answer = (
                            "I still need to know which attribute you meant.\n\n"
                            + (session.pending_clarify_prompt
                               or guard.numbered_attr_pick_prompt(CANDIDATES))
                        )
                else:
                    answer = (
                        "I didn't quite catch that. Here is the current "
                        "configuration."
                    )

            elif did == "D02":
                # Unrelated reply after clarify must NOT mis-bind
                if "change hardware" in user.lower() and not session.pending_clarify_vns:
                    session.pending_clarify_vns = [HW[0], SK[0]]
                    session.pending_clarify_question = user
                    session.pending_clarify_prompt = guard.numbered_attr_pick_prompt(
                        CANDIDATES,
                    )
                    session.pending_clarify_asked_turn = session.turn
                    session.pending_clarify_misses = 0
                    answer = session.pending_clarify_prompt
                elif session.pending_clarify_vns:
                    resolved_vn = guard.match_clarify_reply_offline(
                        user, CANDIDATES,
                    )
                    if resolved_vn:
                        # Mis-bind — leave resolved_vn set so not_misbind fails
                        answer = f"bound to {resolved_vn}"
                    else:
                        session.pending_clarify_misses += 1
                        answer = (
                            "I still need to know which attribute you meant.\n\n"
                            + (session.pending_clarify_prompt
                               or guard.numbered_attr_pick_prompt(CANDIDATES))
                        )
                        resolved_vn = None
                else:
                    answer = "OK."

            elif did == "D03":
                # N3 catalog-switch: asking switch confirm must set pending_switch
                if session.pending_switch_product and re.search(
                    r"\b(yes|continue|confirm)\b", user, re.I,
                ):
                    session.product_name = session.pending_switch_product
                    session.pending_switch_product = ""
                    session.pending_switch_question = ""
                    # Consumable pending so follow-up is not an orphan question
                    session.pending_anchor = "product"
                    answer = (
                        f"Switched to **{session.product_name}**. "
                        "Which product would you like to configure next?"
                    )
                elif re.search(
                    r"switch|software\s*solutions|catalog|continue with",
                    user, re.I,
                ):
                    session.pending_switch_product = "softwareSolutions_BOM"
                    session.pending_switch_question = user
                    answer = (
                        "Switch to softwareSolutions_BOM and discard the "
                        "current configuration? (yes/no)"
                    )
                else:
                    answer = "OK."

            else:
                errors.append(f"{did}: no offline handler registered")
                break

            # Always enforce conversational invariant across dialogue turns
            inv = guard.assert_conversational_invariant(
                answer, session.to_dict(),
                run_id=session.run_id, log=False,
            )
            turn_errs = _check_expect(
                expect, answer=answer, session=session, guard=guard,
                resolved_vn=resolved_vn if "not_misbind" in _expect_tokens(expect)
                else None,
            )
            for e in inv:
                # Only fail the dialogue if expect asked for invariant or
                # the answer is a config question (always required).
                if guard.answer_is_config_question(answer):
                    turn_errs.append(e)
            for e in turn_errs:
                errors.append(f"{did}.t{t['turn']}: {e}")

    return errors


def run_live(cases: list[dict[str, str]]) -> list[str]:
    """Replay every case through the real gateway (needs credentials)."""
    from aryx.cpq import intent_gateway  # deferred: pulls llm stack
    from aryx.cpq.state import CpqSession

    errors: list[str] = []
    for c in cases:
        session = CpqSession()
        try:
            decision = intent_gateway.classify_intent(
                c["question"], session, bundles=[], workspace_id=1,
            )
        except Exception as exc:  # noqa: BLE001 — live env issues are findings
            errors.append(f"{c['id']}: gateway raised {exc!r}")
            continue
        got = decision.result.intent_category.value if decision.result else "ambiguous"
        if got != c["expected_intent"]:
            errors.append(
                f"{c['id']}: expected {c['expected_intent']}, got {got} "
                f"(action={decision.action})",
            )
        if c["expected_vn"] and decision.result and (
                decision.result.variable_name != c["expected_vn"]):
            errors.append(
                f"{c['id']}: expected vn {c['expected_vn']}, "
                f"got {decision.result.variable_name!r}",
            )
    return errors


def main() -> int:
    """CLI entry — exit 0 on pass, 1 on regression."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="CPQ regression suite gate")
    parser.add_argument("--live", action="store_true",
                        help="also score cases via the live gateway")
    args = parser.parse_args()

    cases = parse_suite()
    dialogues = parse_dialogues()
    errors = run_offline(cases)
    errors.extend(run_dialogues_offline(dialogues))
    if args.live:
        errors.extend(run_live(cases))

    if errors:
        logger.error("FAIL: %d regression(s)", len(errors))
        for e in errors[:40]:
            logger.error("  - %s", e)
        return 1
    logger.info(
        "PASS: %d cases (%d positive, %d negative) + %d dialogue(s)%s",
        len(cases),
        sum(1 for c in cases if c["id"].startswith("P")),
        sum(1 for c in cases if c["id"].startswith("N")),
        len(dialogues),
        " + live gateway scoring" if args.live else "",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
