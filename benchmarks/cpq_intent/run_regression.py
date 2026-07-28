#!/usr/bin/env python3
"""cpq-regression — replay CPQ_REGRESSION_SUITE.md as a push-time gate.

Parses the 50+50 markdown suite and enforces, offline (no LLM):

  1. >= 50 positive and >= 50 negative cases present
  2. every expected_intent is a valid IntentCategory enum value
  3. `check` column assertions:
       quote     — intent_gateway.soft_quote_heuristic(question) is True
       off_topic — intent_gateway.hard_off_topic(question) is True
       undo      — session_guard.detect_undo(question) is True
       guided    — session_guard.detect_guided_mode_accept(question) is True
       none      — schema-label validation only
  4. the run_bench.py quarantine/snapshot invariants (shared import)

`--live` additionally replays every case through the gateway (needs Gemini
credentials) and scores expected_intent / expected_vn.

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
    """Parse the markdown tables into case dicts."""
    cases: list[dict[str, str]] = []
    for line in path.read_text().splitlines():
        if not _ROW.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            raise ValueError(f"bad row (need 5 cells): {line!r}")
        cid, question, intent, vn, check = cells
        cases.append({
            "id": cid,
            "question": question,
            "expected_intent": intent,
            "expected_vn": "" if vn == "-" else vn,
            "check": check,
        })
    return cases


def run_offline(cases: list[dict[str, str]]) -> list[str]:
    """All non-LLM assertions. Returns error strings (empty = pass)."""
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
    errors = run_offline(cases)
    if args.live:
        errors.extend(run_live(cases))

    if errors:
        logger.error("FAIL: %d regression(s)", len(errors))
        for e in errors[:40]:
            logger.error("  - %s", e)
        return 1
    logger.info("PASS: %d cases (%d positive, %d negative)%s",
                len(cases),
                sum(1 for c in cases if c["id"].startswith("P")),
                sum(1 for c in cases if c["id"].startswith("N")),
                " + live gateway scoring" if args.live else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
