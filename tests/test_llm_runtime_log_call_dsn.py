"""llm_runtime._log_call()'s DSN resolution.

Regression coverage for a real bug found by post-merge review: _log_call
read os.environ.get("ARYX_RDB_DSN", "") directly, bypassing get_settings().
On an OCI deployment where ops sets ARYX_OCI_ADB_DSN/ARYX_DB_USER/
ARYX_DB_PASSWORD per convention and never sets ARYX_RDB_DSN, dsn was
always "" and the function returned immediately every call -- every LLM
call silently lost its aryx_llm_call audit/usage record.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.llm import llm_runtime


def test_log_call_uses_effective_dsn_not_raw_env_var():
    with patch("aryx.llm.llm_runtime.get_settings") as mock_settings, \
         patch("aryx.llm.llm_runtime.get_pool") as mock_get_pool, \
         patch("aryx.llm.llm_runtime.load", side_effect=lambda name: name):
        mock_settings.return_value.effective_dsn.return_value = "oracle-dsn-value"
        pool = MagicMock()
        mock_get_pool.return_value = pool

        llm_runtime._log_call("answer", "some-model", 10, 20, 500, "", workspace_id=3)

    mock_get_pool.assert_called_once_with("oracle-dsn-value")
    pool.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value.execute.assert_called_once()


def test_log_call_is_noop_when_effective_dsn_empty():
    with patch("aryx.llm.llm_runtime.get_settings") as mock_settings, \
         patch("aryx.llm.llm_runtime.get_pool") as mock_get_pool:
        mock_settings.return_value.effective_dsn.return_value = ""

        llm_runtime._log_call("answer", "some-model", 10, 20, 500, "")

    mock_get_pool.assert_not_called()


def test_log_call_is_noop_when_effective_dsn_raises():
    """e.g. ARYX_OCI_ADB_DSN unset on an oci-backend deployment -- stay
    best-effort, never let audit logging break the actual LLM call."""
    with patch("aryx.llm.llm_runtime.get_settings") as mock_settings, \
         patch("aryx.llm.llm_runtime.get_pool") as mock_get_pool:
        mock_settings.return_value.effective_dsn.side_effect = RuntimeError("boom")

        llm_runtime._log_call("answer", "some-model", 10, 20, 500, "")

    mock_get_pool.assert_not_called()
