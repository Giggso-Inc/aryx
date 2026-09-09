"""Post-ingest validation: prove no source data was lost (zero-loss guarantee).

Generic — works for any tabular/XML-derived ingest, keyed by DATASET name
(the deterministic filename stem recorded in aryx_landed_record.source_dataset)
rather than ontology type names, which can be LLM-chosen and non-reproducible.

Two ground-truth tiers:
- Tier 1 (auto, runs after every confirm): derived from the discovery plans
  actually ingested — the raw XML bytes are NOT available inside
  ingest_confirmed, only the converted CSVs.
- Tier 2 (CLI only): the standalone entry point receives the source XML path
  and cross-checks raw element counts against the extracted rows, surfacing
  cap truncation as a WARNING.

Usage (standalone):
    python -m aryx.pipeline.ingest_validation.ingest_validation <xml-file> <workspace_id>

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), this module
is a thin re-export hub plus the CLI entry point -- the dataclasses live in
`pipeline.ingest_validation_types`, Tier-1 ground-truth derivation lives in
`pipeline.ingest_validation_ground_truth`, and the seven validation checks
live in `pipeline.ingest_validation_checks`. No whitebox test patches any
name in this file directly, so every name is re-exported for backward
compatibility without further caveats.
"""
from __future__ import annotations

from pathlib import Path

from aryx.pipeline.ingest_validation.ingest_validation_checks import (
    _check_projection_parity,
    _dataset_type_map,
    validate_workspace,
)
from aryx.pipeline.ingest_validation.ingest_validation_ground_truth import _parse_csv, ground_truth_from_tabular
from aryx.pipeline.ingest_validation.ingest_validation_types import (
    CheckResult,
    DatasetTruth,
    FkTruth,
    GroundTruth,
    ValidationReport,
)

__all__ = [
    "CheckResult",
    "DatasetTruth",
    "FkTruth",
    "GroundTruth",
    "ValidationReport",
    "ground_truth_from_tabular",
    "validate_workspace",
]


def _raw_xml_counts(xml_bytes: bytes, tags: set[str]) -> dict[str, int]:
    """Tier 2: count raw occurrences of each extracted element tag in the XML."""
    import defusedxml.ElementTree as defused_ET
    root = defused_ET.fromstring(xml_bytes)
    counts = {t: 0 for t in tags}

    def _strip_ns(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    if _strip_ns(root.tag) in counts:
        counts[_strip_ns(root.tag)] += 1
    for elem in root.iter():
        t = _strip_ns(elem.tag)
        if t in counts and elem is not root:
            counts[t] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    """Standalone: re-derive ground truth from an XML file and validate a workspace."""
    import argparse

    from aryx.config import get_settings
    from aryx.pipeline.doc_discovery.doc_discovery import _xml_to_csvs

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml_file", help="Source XML file the workspace was ingested from")
    parser.add_argument("workspace_id", type=int)
    args = parser.parse_args(argv)

    data = Path(args.xml_file).read_bytes()
    stem = Path(args.xml_file).stem
    plans = [{"filename": name, "data": csv_bytes}
             for csv_bytes, name in _xml_to_csvs(data, stem, log_id="validation-cli")]
    gt = ground_truth_from_tabular(plans)
    tags = {t.element_tag for t in gt.datasets.values() if t.element_tag}
    gt.raw_xml_counts = _raw_xml_counts(data, tags)

    settings = get_settings()
    report = validate_workspace(args.workspace_id, gt, settings.effective_dsn(), settings.graph_url)
    print(report.render())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
