#!/usr/bin/env python3
"""cpq-regression — replay CPQ_REGRESSION_SUITE.md as a push-time gate.

Exit codes (machine-readable):
  0 — pass
  1 — case / dialogue regression (intent mismatch, expect tokens)
  2 — suite parse / malformed error
  3 — dropped-intent invariant violation in any dialogue replay

Greppable lines:
  CPQ-REG-001 <case>: intent mismatch …
  CPQ-REG-002: parse error …
  CPQ-REG-003 <dialogue>/<turn>: dropped intent […]
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
from run_bench import (  # noqa: E402
    _check_gateway_quarantine_invariants,
    _check_session_guard_snapshot,
    _load_mod,
)

_ROW = re.compile(r"^\|\s*(?P<id>[PN]\d{2})\s*\|")
_DIALOGUE_HEAD = re.compile(r"^###\s+(?P<id>D\d{2})\s*[—\-–]\s*(?P<title>.+)$")
_TURN_ROW = re.compile(r"^\|\s*(?P<turn>\d+)\s*\|")
_CHECKS = frozenset({"quote", "off_topic", "undo", "guided", "none"})

SOFT_QUOTE = re.compile(
    r"\b(order|configure|config|quote|qty|quantity|radios?|"
    r"destination\s+country|hardware\s+version|bom|apx|svx|"
    r"command\s*central|service\s+type)\b", re.IGNORECASE)
OFF_TOPIC = re.compile(
    r"\b(astrolog(?:y|ical)?|horoscope|zodiac|tarot|"
    r"weather|forecast|world\s*cup|tell\s+me\s+a\s+joke|knock[\s-]knock)\b",
    re.IGNORECASE)

EXIT_PASS = 0
EXIT_REGRESSION = 1
EXIT_PARSE = 2
EXIT_DROPPED = 3


def parse_suite(path: Path = SUITE) -> list[dict[str, str]]:
    """Parse the single-turn markdown tables into case dicts."""
    cases: list[dict[str, str]] = []
    for line in path.read_text().splitlines():
        if not _ROW.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            raise ValueError(f"CPQ-REG-002: parse error bad row (need 5 cells): {line!r}")
        cid, question, intent, vn, check = cells
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
    """Parse ## Dialogues section into multi-turn scripts."""
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


def run_offline(cases: list[dict[str, str]]) -> tuple[list[str], int]:
    """Single-turn assertions. Returns (errors, suggested_exit_code)."""
    errors: list[str] = []
    exit_hint = EXIT_PASS

    pos = [c for c in cases if c["id"].startswith("P")]
    neg = [c for c in cases if c["id"].startswith("N")]
    if len(pos) < 50:
        errors.append(f"CPQ-REG-002: parse error suite has {len(pos)} positive cases, need >= 50")
        exit_hint = EXIT_PARSE
    if len(neg) < 50:
        errors.append(f"CPQ-REG-002: parse error suite has {len(neg)} negative cases, need >= 50")
        exit_hint = EXIT_PARSE
    dupes = {c["id"] for c in cases if sum(1 for x in cases if x["id"] == c["id"]) > 1}
    if dupes:
        errors.append(f"CPQ-REG-002: parse error duplicate ids: {sorted(dupes)}")
        exit_hint = EXIT_PARSE

    schema = _load_mod("aryx.cpq.intent_schema", "aryx/cpq/intent_schema.py")
    known = {c.value for c in schema.IntentCategory}
    _load_mod("aryx.cpq.state", "aryx/cpq/state.py")
    # intent_queue is a sibling module; load before session_guard re-exports it.
    _load_mod("aryx.cpq.intent_queue", "aryx/cpq/intent_queue.py")
    guard = _load_mod("aryx.cpq.session_guard", "aryx/cpq/session_guard.py")
    soft_quote, off_topic = SOFT_QUOTE, OFF_TOPIC

    for c in cases:
        cid, q = c["id"], c["question"]
        if c["expected_intent"] not in known:
            errors.append(
                f"CPQ-REG-001 {cid}: intent mismatch unknown intent "
                f"{c['expected_intent']!r}",
            )
            exit_hint = max(exit_hint, EXIT_REGRESSION)
        chk = c["check"]
        if chk not in _CHECKS:
            errors.append(f"CPQ-REG-002: parse error {cid}: unknown check {chk!r}")
            exit_hint = EXIT_PARSE
        elif chk == "quote" and not soft_quote.search(q):
            errors.append(f"CPQ-REG-001 {cid}: intent mismatch soft_quote missed {q!r}")
            exit_hint = max(exit_hint, EXIT_REGRESSION)
        elif chk == "off_topic" and not off_topic.search(q):
            errors.append(f"CPQ-REG-001 {cid}: intent mismatch hard_off_topic missed {q!r}")
            exit_hint = max(exit_hint, EXIT_REGRESSION)
        elif chk == "undo" and not guard.detect_undo(q):
            errors.append(f"CPQ-REG-001 {cid}: intent mismatch detect_undo missed {q!r}")
            exit_hint = max(exit_hint, EXIT_REGRESSION)
        elif chk == "guided" and not guard.detect_guided_mode_accept(q):
            errors.append(f"CPQ-REG-001 {cid}: intent mismatch detect_guided missed {q!r}")
            exit_hint = max(exit_hint, EXIT_REGRESSION)

    q_errs = _check_gateway_quarantine_invariants()
    s_errs = _check_session_guard_snapshot()
    for e in q_errs + s_errs:
        errors.append(f"CPQ-REG-001 invariant: {e}")
        exit_hint = max(exit_hint, EXIT_REGRESSION)
    return errors, exit_hint


def _expect_tokens(expect: str) -> set[str]:
    """Lowercase token keys only; preserve case for values after '='."""
    out: set[str] = set()
    for raw in expect.split(";"):
        t = raw.strip()
        if not t:
            continue
        if "=" in t:
            k, v = t.split("=", 1)
            out.add(f"{k.strip().lower()}={v.strip()}")
        else:
            out.add(t.lower())
    return out


def _check_expect(
    expect: str,
    *,
    answer: str,
    session: object,
    guard: object,
    resolved_vn: str | None = None,
    active_vn: str | None = None,
    handled: list[str] | None = None,
) -> list[str]:
    errs: list[str] = []
    tokens = _expect_tokens(expect)
    sd = session.to_dict()  # type: ignore[attr-defined]
    answer_l = (answer or "").lower()
    q = list(sd.get("pending_intent_queue") or [])

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
    if "pending_queue" in tokens and not q:
        errs.append("expected pending_intent_queue non-empty")
    if "queue_empty" in tokens and q:
        errs.append(f"expected pending_intent_queue empty, got {q}")
    for t in tokens:
        if t.startswith("queue_len="):
            want = int(t.split("=", 1)[1])
            if len(q) != want:
                errs.append(f"expected queue_len={want}, got {len(q)}")
    if "overflow" in tokens and "can only track" not in answer_l and "⚠️" not in answer:
        errs.append("expected overflow notice in answer")
    if "question" in tokens and "?" not in (answer or ""):
        errs.append("expected answer to contain a question mark")
    if "not_nudge" in tokens and "didn't quite catch that" in answer_l:
        errs.append("answer is the generic review nudge")
    if "not_misbind" in tokens and resolved_vn is not None:
        errs.append(f"unrelated reply mis-bound to {resolved_vn!r}")
    if "ask_next" in tokens and "ask about" not in answer_l and "i'll ask" not in answer_l:
        errs.append("expected 'I'll ask about each next' style note")
    if "vn=hWVersion_astro" in tokens:
        got = sd.get("pending_change_no_value_vn") or active_vn or resolved_vn
        if got != "hWVersion_astro":
            errs.append(f"expected hWVersion_astro, got {got!r}")
    for t in tokens:
        if t.startswith("vn=") and t != "vn=hWVersion_astro":
            want = t.split("=", 1)[1]
            got = sd.get("pending_change_no_value_vn") or active_vn or resolved_vn
            if got != want:
                errs.append(f"expected vn={want}, got {got!r}")
        if t.startswith("active="):
            want = t.split("=", 1)[1]
            got = (
                sd.get("pending_change_no_value_vn")
                or active_vn
                or (q[0] if q else None)
            )
            if got != want:
                errs.append(f"expected active={want}, got {got!r}")
        if t.startswith("handled="):
            want_set = set(t.split("=", 1)[1].split(","))
            got_set = set(handled or [])
            if not want_set.issubset(got_set):
                errs.append(f"expected handled ⊇ {want_set}, got {got_set}")
        # filled=vn:Value — display_filled / filled must hold Value for vn
        if t.startswith("filled="):
            body = t.split("=", 1)[1]
            if ":" not in body:
                errs.append(f"malformed filled token {t!r} (want filled=vn:Value)")
            else:
                fvn, fval = body.split(":", 1)
                got_disp = (sd.get("display_filled") or {}).get(fvn)
                got_fill = (sd.get("filled") or {}).get(fvn)
                if got_disp != fval and got_fill != fval:
                    errs.append(
                        f"expected filled/display {fvn}={fval!r}, "
                        f"got filled={got_fill!r} display={got_disp!r}"
                    )

    if "invariant" in tokens or "question" in tokens:
        violations = guard.assert_conversational_invariant(  # type: ignore[attr-defined]
            answer, sd, run_id=sd.get("run_id") or "dialogue", log=False,
        )
        if violations:
            errs.extend(violations)
    return errs


def run_dialogues_offline(
    dialogues: list[dict] | None = None,
) -> tuple[list[str], int]:
    """Replay multi-turn D## scripts offline. Returns (errors, exit_hint)."""
    dialogues = dialogues if dialogues is not None else parse_dialogues()
    errors: list[str] = []
    exit_hint = EXIT_PASS
    if not dialogues:
        return (
            ["CPQ-REG-002: parse error no D## dialogues found in suite (need >= 1)"],
            EXIT_PARSE,
        )

    state = _load_mod("aryx.cpq.state", "aryx/cpq/state.py")
    _load_mod("aryx.cpq.intent_queue", "aryx/cpq/intent_queue.py")
    guard = _load_mod("aryx.cpq.session_guard", "aryx/cpq/session_guard.py")
    guard.reset_intent_dropped_count()  # type: ignore[attr-defined]

    # Catalog stubs
    HW = ("hWVersion_astro", "Hardware Version")
    SK = ("systemKey_astro", "System Key")
    SVC = ("serviceType_astro", "Primary Service Type")
    ACT = ("activationDelay_astro", "Activation Delay")
    CANDIDATES = [HW, SK]
    MULTI_ABC = [HW, SVC, ACT]
    CAP = int(getattr(state, "INTENT_QUEUE_CAP", 10))

    def _labels(vns: list[str], catalog: list[tuple[str, str]]) -> str:
        m = dict(catalog)
        return ", ".join(f"**{m.get(v, v)}**" for v in vns)

    for d in dialogues:
        did = d["id"]
        if not d.get("turns"):
            errors.append(f"CPQ-REG-002: parse error {did}: no turns defined")
            exit_hint = EXIT_PARSE
            continue

        session = state.CpqSession(
            product_name="aSTRO25_bom",
            status="awaiting_approval",
            run_id=f"dlg-{did}",
        )
        session.filled = {
            "hWVersion_astro": "APX NEXT (4G LTE Only)",
            "systemKey_astro": "Key A",
            "serviceType_astro": "Advantage",
            "activationDelay_astro": "30 Days",
        }
        # Extra filled attrs for overflow case
        for i in range(1, 15):
            session.filled[f"extraAttr{i}_astro"] = f"val{i}"
        session.display_filled = dict(session.filled)
        session.turn = 0
        handled: list[str] = []
        active_vn: str | None = None

        for t in d["turns"]:
            session.turn += 1
            user = t["user"]
            expect = t["expect"]
            answer = ""
            resolved_vn: str | None = None
            detected: list[str] = []

            if did == "D01":
                if not session.pending_clarify_vns and "change hardware" in user.lower():
                    session.pending_clarify_vns = [HW[0], SK[0]]
                    session.pending_clarify_question = user
                    session.pending_clarify_prompt = guard.numbered_attr_pick_prompt(
                        CANDIDATES,
                    )
                    session.pending_clarify_asked_turn = session.turn
                    answer = session.pending_clarify_prompt
                elif session.pending_clarify_vns:
                    resolved_vn = guard.match_clarify_reply_offline(user, CANDIDATES)
                    if resolved_vn:
                        session.pending_clarify_vns = []
                        session.pending_clarify_question = ""
                        session.pending_clarify_prompt = ""
                        session.pending_change_no_value_vn = resolved_vn
                        active_vn = resolved_vn
                        label = dict(CANDIDATES).get(resolved_vn, resolved_vn)
                        answer = (
                            f"Which value would you like for **{label}**?\n\n"
                            f"1. APX NEXT (4G LTE Only)\n2. APX NEXT (4G LTE+5G)"
                        )
                    else:
                        session.pending_clarify_misses += 1
                        answer = (
                            "I still need to know which attribute you meant.\n\n"
                            + (session.pending_clarify_prompt
                               or guard.numbered_attr_pick_prompt(CANDIDATES))
                        )
                else:
                    answer = "I didn't quite catch that."

            elif did == "D02":
                if "change hardware" in user.lower() and not session.pending_clarify_vns:
                    session.pending_clarify_vns = [HW[0], SK[0]]
                    session.pending_clarify_question = user
                    session.pending_clarify_prompt = guard.numbered_attr_pick_prompt(
                        CANDIDATES,
                    )
                    answer = session.pending_clarify_prompt
                elif session.pending_clarify_vns:
                    resolved_vn = guard.match_clarify_reply_offline(user, CANDIDATES)
                    if resolved_vn:
                        answer = f"bound to {resolved_vn}"
                    else:
                        session.pending_clarify_misses += 1
                        answer = (
                            "I still need to know which attribute you meant.\n\n"
                            + session.pending_clarify_prompt
                        )
                        resolved_vn = None
                else:
                    answer = "OK."

            elif did == "D03":
                if session.pending_switch_product and re.search(
                    r"\b(yes|continue|confirm)\b", user, re.I,
                ):
                    session.product_name = session.pending_switch_product
                    session.pending_switch_product = ""
                    session.pending_switch_question = ""
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

            elif did == "D04":
                # change A, B and C → sequential asks via intent queue
                catalog = MULTI_ABC
                if re.search(r"change\s+hardware", user, re.I) and not (
                    session.pending_change_no_value_vn or handled
                ):
                    detected = [HW[0], SVC[0], ACT[0]]
                    active_vn = detected[0]
                    # Enqueue all but active (mirrors _build_no_value_response)
                    overflow = guard.enqueue_intent_targets(
                        session, detected[1:], cap=CAP,
                    )
                    guard.clear_queue_vn(session, active_vn)
                    session.pending_change_no_value_vn = active_vn
                    answer = (
                        f"Which value would you like for "
                        f"**{dict(catalog)[active_vn]}**?\n\n1. opt"
                    )
                    if session.pending_intent_queue:
                        answer += (
                            f"\n\n*(I'll ask about each next: "
                            f"{_labels(session.pending_intent_queue, catalog)}.)*"
                        )
                    if overflow:
                        answer += "\n\n" + guard.format_queue_overflow_notice(overflow)
                elif session.pending_change_no_value_vn or session.pending_intent_queue:
                    prev = session.pending_change_no_value_vn
                    if prev:
                        handled.append(prev)
                        guard.clear_queue_vn(session, prev)
                    session.pending_change_no_value_vn = ""
                    if session.pending_intent_queue:
                        active_vn = guard.pop_intent_queue_head(session)
                        session.pending_change_no_value_vn = active_vn
                        answer = (
                            f"Updated previous. Which value would you like for "
                            f"**{dict(catalog).get(active_vn, active_vn)}**?"
                        )
                        if session.pending_intent_queue:
                            answer += (
                                f"\n\n*(I'll ask about each next: "
                                f"{_labels(session.pending_intent_queue, catalog)}.)*"
                            )
                    else:
                        active_vn = None
                        answer = "Configuration complete for **aSTRO25_bom**."
                else:
                    answer = "OK."

            elif did == "D05":
                # set A to X and change B → A applied, B asked
                catalog = MULTI_ABC
                if re.search(r"set\s+hardware|hardware.*to|and change", user, re.I):
                    handled.append(HW[0])
                    detected = [HW[0], SVC[0]]
                    guard.enqueue_intent_targets(session, [SVC[0]], cap=CAP)
                    active_vn = SVC[0]
                    session.pending_change_no_value_vn = SVC[0]
                    answer = (
                        f"Updated **Hardware Version** → **APX NEXT (4G LTE+5G)**. "
                        f"I'll ask about each next (**Primary Service Type**).\n\n"
                        f"Which value would you like for **Primary Service Type**?"
                    )
                elif session.pending_change_no_value_vn:
                    handled.append(session.pending_change_no_value_vn)
                    guard.clear_queue_vn(session, session.pending_change_no_value_vn)
                    session.pending_change_no_value_vn = ""
                    active_vn = None
                    answer = "Configuration complete for **aSTRO25_bom**."
                else:
                    answer = "OK."

            elif did == "D06":
                # 11+ secondary targets → cap 10 queue + overflow message
                if re.search(r"change\s+all|change\s+these|11", user, re.I) or (
                    "change" in user.lower() and "extra" in user.lower()
                ):
                    targets = [HW[0]] + [f"extraAttr{i}_astro" for i in range(1, 12)]
                    detected = list(targets)
                    active_vn = targets[0]
                    overflow = guard.enqueue_intent_targets(
                        session, targets[1:], cap=CAP,
                    )
                    guard.clear_queue_vn(session, active_vn)
                    session.pending_change_no_value_vn = active_vn
                    answer = (
                        f"Which value would you like for **Hardware Version**?"
                    )
                    if session.pending_intent_queue:
                        answer += (
                            f"\n\n*(I'll ask about each next — "
                            f"{len(session.pending_intent_queue)} more.)*"
                        )
                    # Keep overflow on session for conservation audit, then
                    # surface notice (audit runs below before next turn).
                    if overflow or session.pending_intent_overflow:
                        ov = list(session.pending_intent_overflow) or overflow
                        answer += "\n\n" + guard.format_queue_overflow_notice(ov)
                else:
                    answer = "OK."

            elif did == "D07":
                # Reversed-cue replacement (PROMPT 6): pending value ask
                # then "instead of Standard, prefer Premium" → Premium.
                TIER = "priceTier_astro"
                repl = _load_mod(
                    "aryx.cpq.replacement_clause",
                    "aryx/cpq/replacement_clause.py",
                )
                if re.search(r"change\s+price\s+tier", user, re.I) and not (
                    session.pending_change_no_value_vn
                ):
                    session.filled[TIER] = "Standard"
                    session.display_filled[TIER] = "Standard"
                    session.pending_change_no_value_vn = TIER
                    active_vn = TIER
                    answer = (
                        "Which value would you like for **Price Tier**?\n\n"
                        "1. Standard\n2. Premium"
                    )
                elif session.pending_change_no_value_vn == TIER:
                    wanted, rejected = repl.extract_replacement_clause(user)
                    apply_val = wanted or user
                    if rejected and rejected.lower() in (apply_val or "").lower():
                        answer = (
                            f"I couldn't match a clear replacement "
                            f"(wanted still contains rejected {rejected!r})."
                        )
                    else:
                        apply_norm = (apply_val or "").strip()
                        for token in ("Premium", "Standard"):
                            if re.search(
                                rf"(?<!\w){re.escape(token)}(?!\w)",
                                apply_norm, re.I,
                            ):
                                apply_norm = token
                                break
                        session.filled[TIER] = apply_norm
                        session.display_filled[TIER] = apply_norm
                        handled.append(TIER)
                        session.pending_change_no_value_vn = ""
                        active_vn = None
                        answer = (
                            f"Updated **Price Tier** → **{apply_norm}**."
                        )
                        if rejected and apply_norm.lower() == rejected.lower():
                            errors.append(
                                f"CPQ-REG-001 {did}/t{t['turn']}: applied "
                                f"rejected value {rejected!r}"
                            )
                            exit_hint = max(exit_hint, EXIT_REGRESSION)
                else:
                    answer = "OK."

            else:
                errors.append(f"CPQ-REG-002: parse error {did}: no offline handler")
                exit_hint = EXIT_PARSE
                break

            # Intent conservation audit for multi-target dialogues
            if detected:
                audit = guard.audit_intent_conservation(  # type: ignore[attr-defined]
                    user, detected, handled, session,
                    clarified_vns=(
                        {session.pending_change_no_value_vn}
                        if session.pending_change_no_value_vn else set()
                    ) | set(session.pending_clarify_vns or []),
                    run_id=session.run_id, turn=session.turn, log=False,
                )
                if not audit.ok:
                    exit_hint = EXIT_DROPPED
                    errors.append(
                        f"CPQ-REG-003 {did}/t{t['turn']}: dropped intent "
                        f"{audit.dropped}",
                    )
                    notice = guard.format_dropped_intent_notice(audit.dropped)
                    if notice:
                        answer = answer + "\n\n" + notice

            inv = guard.assert_conversational_invariant(
                answer, session.to_dict(),
                run_id=session.run_id, log=False,
            )
            turn_errs = _check_expect(
                expect, answer=answer, session=session, guard=guard,
                resolved_vn=(
                    resolved_vn if "not_misbind" in _expect_tokens(expect)
                    else None
                ),
                active_vn=active_vn,
                handled=handled,
            )
            for e in inv:
                if guard.answer_is_config_question(answer):
                    turn_errs.append(e)
            for e in turn_errs:
                errors.append(f"CPQ-REG-001 {did}.t{t['turn']}: {e}")
                exit_hint = max(exit_hint, EXIT_REGRESSION)

    return errors, exit_hint


def run_live(cases: list[dict[str, str]]) -> list[str]:
    from aryx.cpq import intent_gateway
    from aryx.cpq.state import CpqSession

    errors: list[str] = []
    for c in cases:
        session = CpqSession()
        try:
            decision = intent_gateway.classify_intent(
                c["question"], session, bundles=[], workspace_id=1,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"CPQ-REG-001 {c['id']}: gateway raised {exc!r}")
            continue
        got = decision.result.intent_category.value if decision.result else "ambiguous"
        if got != c["expected_intent"]:
            errors.append(
                f"CPQ-REG-001 {c['id']}: intent mismatch expected "
                f"{c['expected_intent']}, got {got}",
            )
        if c["expected_vn"] and decision.result and (
                decision.result.variable_name != c["expected_vn"]):
            errors.append(
                f"CPQ-REG-001 {c['id']}: intent mismatch expected vn "
                f"{c['expected_vn']}, got {decision.result.variable_name!r}",
            )
    return errors


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="CPQ regression suite gate")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    try:
        cases = parse_suite()
        dialogues = parse_dialogues()
    except Exception as exc:  # noqa: BLE001
        logger.error("CPQ-REG-002: parse error %s", exc)
        return EXIT_PARSE

    errors, code = run_offline(cases)
    d_errs, d_code = run_dialogues_offline(dialogues)
    errors.extend(d_errs)
    code = max(code, d_code)

    if args.live:
        live_errs = run_live(cases)
        errors.extend(live_errs)
        if live_errs:
            code = max(code, EXIT_REGRESSION)

    if errors:
        logger.error(
            "FAIL: %d regression(s) [exit=%d: %s]",
            len(errors), code,
            {0: "pass", 1: "case/dialogue regression", 2: "parse/malformed",
             3: "dropped-intent"}.get(code, "unknown"),
        )
        for e in errors[:40]:
            logger.error("  - %s", e)
        return code if code else EXIT_REGRESSION

    logger.info(
        "PASS: %d cases (%d positive, %d negative) + %d dialogue(s)%s",
        len(cases),
        sum(1 for c in cases if c["id"].startswith("P")),
        sum(1 for c in cases if c["id"].startswith("N")),
        len(dialogues),
        " + live gateway scoring" if args.live else "",
    )
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
