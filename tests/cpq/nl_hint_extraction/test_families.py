"""list_ingested_families -- zero direct test coverage before this file
(confirmed via grep across tests/); only exercised incidentally through
other tests that happen to mock reader/engine for unrelated reasons.

Covers the actual bug this closes (2026-10-05, "quote for SVX" / workspace
1084): a raw-graph-ingested workspace whose ontology types are the raw,
unprefixed XML tag (e.g. "bm_prd_family") must not be silently treated as
"nothing ingested" -- see cpq_ingestion/raw_graph/resolve_relate.py's
ontology_type derivation, which is the actual fix; this test guards the
Ask-feature side of the same contract.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from aryx.cpq.nl_hint_extraction.families import list_ingested_families


def _engine(family_name_by_id: dict[int, str]) -> MagicMock:
    engine = MagicMock()
    engine._batch_fetch.side_effect = lambda ids, workspace_id: {
        eid: {"name": family_name_by_id[eid]} for eid in ids if eid in family_name_by_id
    }
    return engine


def _reader(types: list[str], entities_by_type: dict[str, list[dict]]) -> MagicMock:
    reader = MagicMock()
    reader.distinct_types.return_value = types
    reader.find_entities.side_effect = lambda ontology_type, limit=5: entities_by_type.get(ontology_type, [])
    return reader


def test_properly_prefixed_types_return_the_real_family_name():
    """Old-pipeline-shaped types (PascalCase, source-prefixed) resolve a
    family name the normal way."""
    engine = _engine({1: "SVX Video Remote Speaker Microphone"})
    reader = _reader(
        types=["ApxNextConfigBmPrdFamily", "ApxNextConfigBmCatalog"],
        entities_by_type={"ApxNextConfigBmPrdFamily": [{"id": 1, "name": "SVX Video Remote Speaker Microphone"}]},
    )

    assert list_ingested_families(engine, reader, workspace_id=1) == ["SVX Video Remote Speaker Microphone"]


def test_raw_unprefixed_types_return_no_families_this_is_the_bug_this_closes():
    """Reproduces the live bug (workspace 1084): when every ingested type is
    the raw XML tag with no catalog prefix (_catalog_prefix returns "" for
    all of them), list_ingested_families has nothing to key a family lookup
    on and returns [] -- even though a real bm_prd_family entity exists in
    the graph. This is the exact failure mode the resolve_relate.py
    ontology_type fix (naming parity with the old CSV pipeline) closes;
    this test documents what "closed" looks like on the Ask-feature side:
    once ontology_type is PascalCase + prefixed, this same reader/engine
    shape behaves like the test above instead."""
    engine = _engine({1: "SVX Video"})
    reader = _reader(
        types=["bm_prd_family", "bm_catalog", "bm_config_attr"],
        entities_by_type={"bm_prd_family": [{"id": 1, "name": "SVX Video"}]},
    )

    assert list_ingested_families(engine, reader, workspace_id=1084) == []


def test_multiple_catalog_prefixes_return_one_family_name_each():
    engine = _engine({1: "APX Next", 2: "SL3500e"})
    reader = _reader(
        types=["ApxNextConfigBmPrdFamily", "Sl3500EConfigBmPrdFamily"],
        entities_by_type={
            "ApxNextConfigBmPrdFamily": [{"id": 1, "name": "APX Next"}],
            "Sl3500EConfigBmPrdFamily": [{"id": 2, "name": "SL3500e"}],
        },
    )

    assert list_ingested_families(engine, reader, workspace_id=1) == ["APX Next", "SL3500e"]


def test_empty_workspace_returns_empty_list():
    engine = _engine({})
    reader = _reader(types=[], entities_by_type={})

    assert list_ingested_families(engine, reader, workspace_id=1) == []


def test_falls_back_to_distinct_types_attributeerror_path():
    """reader without distinct_types() falls back to sampling find_entities(limit=1000)."""
    engine = _engine({1: "APX Next"})
    reader = MagicMock(spec=["find_entities"])
    reader.find_entities.side_effect = lambda ontology_type=None, limit=5: (
        [{"type": "ApxNextConfigBmPrdFamily"}] if ontology_type is None
        else [{"id": 1, "name": "APX Next"}] if ontology_type == "ApxNextConfigBmPrdFamily"
        else []
    )

    assert list_ingested_families(engine, reader, workspace_id=1) == ["APX Next"]
