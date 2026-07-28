"""Pins for the push-time CPQ regression suite (benchmarks/cpq_intent).

1. The suite parses and passes offline (same gate the pre-push hook runs).
2. run_regression.py's mirrored heuristics match the real intent_gateway
   regexes — the runner avoids importing the LLM stack, so drift between
   the mirror and the source would silently weaken the gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks" / "cpq_intent"
sys.path.insert(0, str(BENCH))

import run_regression  # noqa: E402

from aryx.cpq import intent_gateway  # noqa: E402


def test_suite_parses_50_50() -> None:
    cases = run_regression.parse_suite()
    assert sum(1 for c in cases if c["id"].startswith("P")) >= 50
    assert sum(1 for c in cases if c["id"].startswith("N")) >= 50


def test_suite_offline_gate_passes() -> None:
    assert run_regression.run_offline(run_regression.parse_suite()) == []


def test_dialogues_parsed_and_pass() -> None:
    dialogues = run_regression.parse_dialogues()
    assert len(dialogues) >= 3
    ids = {d["id"] for d in dialogues}
    assert {"D01", "D02", "D03"} <= ids
    assert run_regression.run_dialogues_offline(dialogues) == []


def test_mirrors_match_gateway_regexes() -> None:
    assert run_regression.SOFT_QUOTE.pattern == intent_gateway._SOFT_QUOTE.pattern
    assert run_regression.OFF_TOPIC.pattern == intent_gateway._OFF_TOPIC_HARD.pattern
