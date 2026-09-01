"""McpTokenStore.issue()'s Oracle no-RETURNING follow-up-select path.

Regression coverage for a real bug found by post-merge review:
insert_mcp_token.sql had no Oracle override, so the generic translator's
RETURNING mechanism typed every out-var as oracledb.STRING with no
outconverter -- created_at/expires_at (TIMESTAMPTZ) and workspace_id
(NUMBER) would come back as raw Oracle-formatted strings instead of
native types in the POST /admin/mcp/tokens response.

Stubs aryx.mcp.auth to sidestep this environment's unrelated Python 3.10
vs 3.11+ `from datetime import UTC` import chain issue (aryx.mcp.auth
needs 3.11+; this repo's Docker image runs 3.13).
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch


def _stub_mcp_auth() -> None:
    if "aryx.mcp" in sys.modules and "aryx.mcp.auth" in sys.modules:
        return
    pkg = types.ModuleType("aryx.mcp")
    pkg.__path__ = []
    auth = types.ModuleType("aryx.mcp.auth")
    auth.SALES_CPQ_PURPOSE = "sales_cpq"
    auth.SALES_CPQ_TOOLS = frozenset({"sales_chat_send"})
    auth.McpPrincipal = object
    sys.modules["aryx.mcp"] = pkg
    sys.modules["aryx.mcp.auth"] = auth


_stub_mcp_auth()

from aryx.store.mcp_token_store import McpTokenStore  # noqa: E402


def _make_store():
    store = McpTokenStore.__new__(McpTokenStore)
    store._pool = MagicMock()
    cur = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    store._pool.connection.return_value = conn
    return store, cur


def test_issue_postgres_single_call_with_returning():
    store, cur = _make_store()
    cur.fetchone.return_value = (1, "my-token", "aryx_abcd1234", "2026-01-01", "general", "", None, None, None)
    with patch("aryx.store.mcp_token_store.get_settings") as mock_cfg, \
         patch("aryx.store.mcp_token_store.load", side_effect=lambda name: name):
        mock_cfg.return_value.effective_db_backend.return_value = "local"
        store.issue("my-token")

    query_names = [c.args[0] for c in cur.execute.call_args_list]
    assert query_names == ["insert_mcp_token"]


def test_issue_oracle_does_insert_then_follow_up_select_by_prefix():
    store, cur = _make_store()
    cur.fetchone.return_value = (1, "my-token", "aryx_abcd1234", "2026-01-01", "general", "", None, None, None)
    with patch("aryx.store.mcp_token_store.get_settings") as mock_cfg, \
         patch("aryx.store.mcp_token_store.load", side_effect=lambda name: name):
        mock_cfg.return_value.effective_db_backend.return_value = "oci"
        store.issue("my-token")

    query_names = [c.args[0] for c in cur.execute.call_args_list]
    assert query_names == ["insert_mcp_token", "select_mcp_token_by_prefix"]
    # The follow-up select must use the same prefix that was inserted.
    insert_params = cur.execute.call_args_list[0].args[1]
    select_params = cur.execute.call_args_list[1].args[1]
    assert select_params == (insert_params[2],)  # prefix is the 3rd insert param
