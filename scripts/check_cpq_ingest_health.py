"""Read-only post-ingest health check for one CPQ workspace.

    python scripts/check_cpq_ingest_health.py --workspace-id 1147 [--catalog-prefix Astro25Configdata]

Prints PASS / WARN / FAIL / SKIP per check and exits 1 when any check FAILs. Reads only
(the CPQ rdb accessors); never writes. See aryx/cpq_ingestion/ingest_health.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aryx.cpq.rdb.rdb import get_cpq_rdb  # noqa: E402
from aryx.cpq_ingestion.ingest_health import FAIL, evaluate_workspace_health, worst_status  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace-id", type=int, required=True)
    parser.add_argument("--catalog-prefix", default="", help="limit function/attribute checks to one catalog")
    args = parser.parse_args()
    checks = evaluate_workspace_health(get_cpq_rdb(), args.workspace_id, args.catalog_prefix)
    for check in checks:
        print(f"{check.status:5s} {check.name:20s} {check.detail}")
    overall = worst_status(checks)
    print(f"\nworkspace {args.workspace_id}: {overall}")
    return 1 if overall == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
