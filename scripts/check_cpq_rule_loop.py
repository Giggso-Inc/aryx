#!/usr/bin/env python3
"""Validate CPQ hide → recommend → constrain → auto-fill deterministically.

Run with ``PYTHONPATH=src python scripts/check_cpq_rule_loop.py --help``.
The checker reads catalog data and writes only its optional report file.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

from aryx.cpq.bml import BmlEvaluator
from aryx.cpq.engine import CpqEngine
from aryx.cpq.validation.compare import compare_rule_order, compare_states
from aryx.cpq.validation.oracle import DeterministicRuleOracle
from aryx.cpq.validation.production import evaluate_production
from aryx.cpq.validation.report import ScenarioValidation, ValidationReport
from aryx.cpq.validation.runner import evaluate_to_fixed_point
from aryx.cpq.validation.scenarios import generate_scenarios
from aryx.ports import ports

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", type=int, required=True)
    parser.add_argument("--product", required=True, help="Ingested CPQ product/family name")
    parser.add_argument("--max-scenarios", type=int, default=10_000)
    parser.add_argument("--strict-unknown", action="store_true")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    return parser


def build_report(args: argparse.Namespace) -> ValidationReport:
    """Load one catalog and compare every generated scenario without mutation."""
    engine = CpqEngine()
    reader = ports().graph_reader(args.workspace_id)
    attrs, resolved_product = engine.load_product_config(
        reader, args.workspace_id, args.product,
    )
    if not attrs:
        raise ValueError(f"no CPQ attributes found for product {args.product!r}")
    catalog_prefix = attrs[0].catalog_prefix
    hiding_rules = engine.load_hiding_rules(args.workspace_id, catalog_prefix)
    rec_rules, con_rules = engine.load_recommendation_and_constraint_rules(
        args.workspace_id, catalog_prefix,
    )
    scenarios = generate_scenarios(
        attrs, hiding_rules, rec_rules, con_rules, max_scenarios=args.max_scenarios,
    )
    oracle = DeterministicRuleOracle(attrs, hiding_rules, rec_rules, con_rules)
    deterministic_bml = BmlEvaluator({}, use_llm=False)
    all_attributes = {attr.variable_name for attr in attrs}
    validations: list[ScenarioValidation] = []
    for scenario in scenarios:
        expected = evaluate_to_fixed_point(
            oracle, scenario, strict_unknown=args.strict_unknown,
        )
        actual = evaluate_production(
            engine, attrs, scenario, hiding_rules, rec_rules, con_rules,
            deterministic_bml,
        )
        reordered = evaluate_production(
            engine, attrs, scenario, list(reversed(hiding_rules)),
            list(reversed(rec_rules)), list(reversed(con_rules)), deterministic_bml,
        )
        differences = (
            *compare_states(expected, actual, all_attributes=all_attributes),
            *compare_rule_order(actual, reordered),
        )
        validations.append(ScenarioValidation(expected, differences))
    product = resolved_product or args.product
    return ValidationReport(product, args.workspace_id, tuple(validations))


def emit_report(report: ValidationReport, output: Path | None) -> None:
    """Write stable JSON to stdout or the explicitly requested report path."""
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(rendered)
        return
    output.write_text(rendered, encoding="utf-8")
    logger.info("CPQ validation report written to %s", output)


def main(argv: list[str] | None = None) -> int:
    """Run validation and return 0 pass, 1 mismatch, or 2 setup failure."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        report = build_report(args)
        emit_report(report, args.output)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("CPQ validation could not run: %s", exc)
        return 2
    logger.info(
        "CPQ validation: scenarios=%d failed=%d unknown=%d",
        len(report.validations), report.failed, report.unknown,
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
