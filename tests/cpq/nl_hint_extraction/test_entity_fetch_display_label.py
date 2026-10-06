"""_match_family_name also matches a family/model's display_label
(docs/ingestion/CPQ_XML_DISPLAY_NAMES_PLAN_2026-10-05.md): the family
prompt now shows labels, so a reply that echoes the label must still
resolve to the entity's own `name`."""
from __future__ import annotations

import re
from unittest.mock import MagicMock

from aryx.cpq.nl_hint_extraction.entity_fetch import _match_family_name

PREFIX = "ApxnextCnofigdata"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _setup(attrs: dict) -> tuple[MagicMock, MagicMock]:
    engine = MagicMock()
    engine._batch_fetch.side_effect = lambda ids, workspace_id: {1: attrs}
    reader = MagicMock()
    reader.find_entities.side_effect = lambda ontology_type, limit=2000: (
        [{"id": 1, "name": "17691417058"}] if ontology_type == f"{PREFIX}BmCatalog" else []
    )
    return engine, reader


def test_match_family_name_variable_name_shape_still_matches():
    engine, reader = _setup({"name": "aPXNext_BOM", "display_label": "APX™ NEXT"})
    assert _match_family_name(engine, reader, 1, PREFIX, _norm("APX Next")) == "aPXNext_BOM"


def test_match_family_name_display_label_only_match_returns_name():
    engine, reader = _setup({"name": "zz_internal_code", "display_label": "Widget Pro"})
    assert _match_family_name(engine, reader, 1, PREFIX, _norm("Widget Pro")) == "zz_internal_code"


def test_match_family_name_trademark_in_label_ignored():
    engine, reader = _setup({"name": "q1", "display_label": "APX™ NEXT"})
    assert _match_family_name(engine, reader, 1, PREFIX, _norm("apx next")) == "q1"


def test_match_family_name_no_match_returns_none():
    engine, reader = _setup({"name": "aPXNext_BOM", "display_label": "APX™ NEXT"})
    assert _match_family_name(engine, reader, 1, PREFIX, _norm("Mototrbo radios")) is None


def test_match_family_name_missing_display_label_unchanged_behaviour():
    engine, reader = _setup({"name": "aPXN70_BOM"})
    assert _match_family_name(engine, reader, 1, PREFIX, _norm("APX N70")) == "aPXN70_BOM"
