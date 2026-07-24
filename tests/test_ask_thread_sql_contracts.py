"""SQL contract checks for Shay-message-backed Ask threads."""

from __future__ import annotations

import ast
from pathlib import Path


STORE_PATH = Path(__file__).resolve().parents[1] / "src" / "aryx" / "store" / "ask_thread_store.py"
CONTRACT_PATH = STORE_PATH.with_name("ask_thread_contract.py")
QUERY_DIR = Path(__file__).resolve().parents[1] / "src" / "aryx" / "queries"
MIGRATE_PATH = STORE_PATH.with_name("migrate.py")


def _sql(name: str) -> str:
    return (QUERY_DIR / f"{name}.sql").read_text(encoding="utf-8")


def test_ask_thread_insert_message_conflict_preserves_existing_user_prompt():
    sql = _sql("ask_thread_insert_message")

    assert "WHEN gg_messages.message_type = 'user' THEN gg_messages.content" in sql


def _message_insert_param_expressions() -> list[str]:
    tree = ast.parse(CONTRACT_PATH.read_text(encoding="utf-8"))
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "message_insert_params"
    )
    return_node = next(
        node for node in helper.body if isinstance(node, ast.Return)
    )
    assert isinstance(return_node.value, ast.Tuple)
    return [ast.unparse(element) for element in return_node.value.elts]


def test_ask_thread_insert_message_placeholders_match_store_params():
    sql = _sql("ask_thread_insert_message")
    params = _message_insert_param_expressions()

    assert sql.count("%s") == len(params)


def test_ask_thread_insert_message_store_params_follow_sql_column_order():
    assert _message_insert_param_expressions() == [
        "thread_id",
        "message_id",
        "content",
        "message_type",
        "thread_id",
        "request_id",
        "is_ai_processed",
        "ai_provider",
        "ai_model",
        "ai_processing_time",
        "Json(metadata)",
        "Json(citations)",
        "Json(usage)",
    ]


def test_ask_thread_history_only_reads_visible_messages():
    sql = _sql("ask_thread_select_history")

    assert "is_visible = TRUE" in sql


def test_ask_thread_cached_response_only_reads_visible_messages():
    sql = _sql("ask_thread_select_cached_response")

    assert "gg_messages.is_visible = TRUE" in sql


def test_ask_thread_cached_response_excludes_failed_attempts():
    sql = _sql("ask_thread_select_cached_response")

    assert "message_metadata->>'error'" in sql


def test_ask_thread_insert_reclaims_failed_or_expired_request_lease():
    sql = _sql("ask_thread_insert_message")
    normalized_sql = " ".join(sql.split())

    assert "request_status' = 'failed'" in sql
    assert (
        "request_status' = 'in_progress' AND gg_messages.updated_at < NOW() - "
        "INTERVAL '20 minutes'"
    ) in normalized_sql


def test_ask_thread_channel_conflict_target_has_follow_up_unique_index():
    migration = (
        STORE_PATH.parent / "migrations" / "0034_ask_thread_retry_contracts.sql"
    ).read_text(encoding="utf-8")

    assert "ON gg_channels(name, workspace_id)" in migration


def test_ask_thread_channel_index_rejects_duplicates_clearly() -> None:
    migration = (
        STORE_PATH.parent / "migrations" / "0034_ask_thread_retry_contracts.sql"
    ).read_text(encoding="utf-8")

    assert all(
        fragment in migration
        for fragment in (
            "GROUP BY name, workspace_id",
            "HAVING COUNT(*) > 1",
            "RAISE EXCEPTION",
        )
    )


def test_ask_thread_retry_migration_errors_are_required() -> None:
    migration = (
        STORE_PATH.parent / "migrations" / "0034_ask_thread_retry_contracts.sql"
    ).read_text(encoding="utf-8")
    runner = MIGRATE_PATH.read_text(encoding="utf-8")
    required_block = runner[
        runner.index("if required:"):
        runner.index("# An optional/unavailable feature")
    ]

    assert "-- migration: required" in migration and "raise" in required_block


def test_ask_thread_list_messages_exposes_request_id_for_recovery():
    sql = _sql("ask_thread_list_messages")

    assert "request_id::text" in sql
