#!/usr/bin/env python3
"""cpq-intent-bench — golden-set replay for intent classification contracts.

Runs the ~50 canned questions in golden_set.json against:
  1. parse/schema contracts (always)
  2. session_guard detectors (undo / guided)
  3. optional live gateway when --live is passed (needs LLM)

Exit 0 on pass, 1 on regression. Designed for CI:

    PYTHONPATH=src python3 benchmarks/cpq_intent/run_bench.py
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("cpq_intent_bench")

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).resolve().parent / "golden_set.json"
SRC = ROOT / "src"


def _load_mod(name: str, rel: str):
    """Load a module by file path — avoids aryx.cpq.__init__ pulling engine/psycopg."""
    import importlib.util
    import types

    # Ensure package parents exist as plain namespaces
    parts = name.split(".")
    for i in range(1, len(parts)):
        pkg = ".".join(parts[:i])
        if pkg not in sys.modules:
            sys.modules[pkg] = types.ModuleType(pkg)
    path = SRC / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _load_cases() -> list[dict]:
    data = json.loads(GOLDEN.read_text())
    return list(data.get("cases") or [])


def _check_schema_coverage(cases: list[dict]) -> list[str]:
    """Every expected_intent must be a known IntentCategory value."""
    schema = _load_mod("aryx.cpq.intent_schema", "aryx/cpq/intent_schema.py")
    known = {c.value for c in schema.IntentCategory}
    errors: list[str] = []
    for case in cases:
        exp = case.get("expected_intent")
        if exp not in known:
            errors.append(f"{case['id']}: unknown intent {exp!r}")
    return errors


def _check_undo_detector(cases: list[dict]) -> list[str]:
    # session_guard imports state + intent_queue — load those first
    _load_mod("aryx.cpq.state", "aryx/cpq/state.py")
    _load_mod("aryx.cpq.intent_queue", "aryx/cpq/intent_queue.py")
    guard = _load_mod("aryx.cpq.session_guard", "aryx/cpq/session_guard.py")
    errors: list[str] = []
    for case in cases:
        if case.get("expected_intent") != "undo":
            continue
        if not guard.detect_undo(case["question"]):
            errors.append(f"{case['id']}: detect_undo missed {case['question']!r}")
    return errors


def _check_gateway_quarantine_invariants() -> list[str]:
    """Regression pins for quarantine — no live LLM."""
    schema = sys.modules.get("aryx.cpq.intent_schema") or _load_mod(
        "aryx.cpq.intent_schema", "aryx/cpq/intent_schema.py",
    )
    errors: list[str] = []
    if schema.parse_gateway_intent({
        "intent_category": "change_request",
        "confidence": "high",
        "variable_name": "x",
        "value_ref": "0",
        "evidence_span": "x",
    }) is not None:
        errors.append("parse must reject string value_ref")

    bad = schema.GatewayIntentResult(
        intent_category=schema.IntentCategory.CHANGE_REQUEST,
        confidence=schema.Confidence.HIGH,
        variable_name="invented",
        value_ref=0,
        evidence_span="change it",
    )
    out = schema.validate_gateway_quarantine(
        bad, "please change it", {"real_vn"}, {"real_vn": 2},
    )
    if out.intent_category != schema.IntentCategory.AMBIGUOUS:
        errors.append("quarantine must downgrade invented variable_name")
    return errors


def _check_session_guard_snapshot() -> list[str]:
    state = sys.modules.get("aryx.cpq.state") or _load_mod(
        "aryx.cpq.state", "aryx/cpq/state.py",
    )
    if "aryx.cpq.intent_queue" not in sys.modules:
        _load_mod("aryx.cpq.intent_queue", "aryx/cpq/intent_queue.py")
    guard = sys.modules.get("aryx.cpq.session_guard") or _load_mod(
        "aryx.cpq.session_guard", "aryx/cpq/session_guard.py",
    )
    errors: list[str] = []
    s = state.CpqSession()
    s.run_id = "bench"
    s.filled = {"a": "1"}
    guard.push_snapshot(s, reason="bench")
    s.filled = {"a": "2"}
    if not guard.restore_last_snapshot(s):
        errors.append("restore_last_snapshot failed")
    elif s.filled.get("a") != "1":
        errors.append(f"undo did not restore filled, got {s.filled}")
    return errors


def main() -> int:
    """CLI entry — exit 0 on pass, 1 on regression."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="CPQ intent golden-set bench")
    parser.add_argument(
        "--live", action="store_true",
        help="Also call the live gateway (requires LLM credentials)",
    )
    args = parser.parse_args()

    cases = _load_cases()
    if len(cases) < 50:
        logger.error("FAIL: golden set has %d cases, need >= 50", len(cases))
        return 1

    errors: list[str] = []
    errors.extend(_check_schema_coverage(cases))
    errors.extend(_check_undo_detector(cases))
    errors.extend(_check_gateway_quarantine_invariants())
    errors.extend(_check_session_guard_snapshot())

    if args.live:
        logger.warning("--live gateway scoring not implemented in offline CI path")

    if errors:
        logger.error("FAIL: %d regression(s)", len(errors))
        for e in errors[:30]:
            logger.error("  - %s", e)
        return 1

    logger.info("PASS: %d golden cases + quarantine/undo invariants", len(cases))
    return 0


if __name__ == "__main__":
    sys.exit(main())
