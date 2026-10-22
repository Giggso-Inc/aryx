"""Connection-contract tests for password-protected FalkorDB servers."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault("falkordb", MagicMock())

from aryx.graph.falkor_store import FalkorStore
from aryx.graph.reader import GraphReader


def test_graph_reader_decodes_an_optional_falkor_password() -> None:
    """The reader forwards URL credentials, or None for passwordless servers."""
    database = MagicMock()
    with patch("aryx.graph.reader.FalkorDB", return_value=database) as client:
        GraphReader("redis://:pass%40word@graph.example:6380", "workspace_51")
        GraphReader("redis://graph.example:6380", "workspace_52")

    assert client.call_args_list[0].kwargs == {
        "host": "graph.example", "port": 6380, "password": "pass@word"}
    assert client.call_args_list[1].kwargs == {
        "host": "graph.example", "port": 6380, "password": None}


def test_falkor_store_decodes_an_optional_falkor_password() -> None:
    """The writer uses the same authentication behavior as the reader."""
    database = MagicMock()
    with patch("aryx.graph.falkor_store.FalkorDB", return_value=database) as client:
        FalkorStore("redis://:pass%40word@graph.example:6380", "workspace_51")
        FalkorStore("redis://graph.example:6380", "workspace_52")

    assert client.call_args_list[0].kwargs == {
        "host": "graph.example", "port": 6380, "password": "pass@word"}
    assert client.call_args_list[1].kwargs == {
        "host": "graph.example", "port": 6380, "password": None}
