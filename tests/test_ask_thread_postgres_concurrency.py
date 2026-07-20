"""Real-Postgres concurrency coverage for Ask request claiming."""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.types.json import Json


QUERY_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "aryx"
    / "queries"
    / "ask_thread_insert_message.sql"
)
MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "aryx"
    / "store"
    / "migrations"
    / "0033_ask_thread_messages.sql"
)
SQL_FIXTURE_DIR = Path(__file__).resolve().parent / "sql"


def _test_sql(name: str) -> str:
    return (SQL_FIXTURE_DIR / f"{name}.sql").read_text(encoding="utf-8")


def _schema_sql(name: str, schema: str) -> sql.Composed:
    return sql.SQL(_test_sql(name)).format(schema=sql.Identifier(schema))


def _postgres_dsn() -> str:
    dsn = os.getenv("ARYX_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set ARYX_TEST_POSTGRES_DSN to run real-Postgres concurrency tests")
    return dsn


def test_ask_thread_request_id_unique_index_allows_one_concurrent_claim():
    dsn = _postgres_dsn()
    schema = f"ask_thread_concurrency_{uuid.uuid4().hex}"
    thread_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    query = QUERY_PATH.read_text(encoding="utf-8")
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    barrier = threading.Barrier(2)
    claims: list[bool] = []

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(_schema_sql("ask_thread_create_schema", schema))
        cur.execute(_schema_sql("ask_thread_set_search_path", schema))
        cur.execute(_test_sql("ask_thread_concurrency_setup"))
        for statement in migration.split(";"):
            if statement.strip():
                cur.execute(statement)
        cur.execute(_test_sql("ask_thread_insert_thread"), (thread_id,))

    def claim() -> None:
        params = (
            thread_id,
            str(uuid.uuid4()),
            "Same prompt",
            "user",
            thread_id,
            request_id,
            False,
            None,
            None,
            None,
            Json({"request_status": "in_progress"}),
            Json([]),
            Json({}),
        )
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(_schema_sql("ask_thread_set_search_path", schema))
            barrier.wait()
            cur.execute(query, params)
            claims.append(cur.fetchone() is not None)

    workers = [threading.Thread(target=claim), threading.Thread(target=claim)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)

        assert all(not worker.is_alive() for worker in workers)
        assert sorted(claims) == [False, True]
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(_schema_sql("ask_thread_set_search_path", schema))
            cur.execute(
                _test_sql("ask_thread_count_user_request"),
                (thread_id, request_id),
            )
            assert cur.fetchone()[0] == 1
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(_schema_sql("ask_thread_drop_schema", schema))
