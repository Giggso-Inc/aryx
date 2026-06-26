"""Load SQL from .sql files — keeps SQL out of Python (DB-Guard discipline)."""
from __future__ import annotations

from pathlib import Path

_SQL_DIR = Path(__file__).parent
_ORACLE_DIR = _SQL_DIR / "oracle"

# Per-(name, backend) cache — avoids filesystem reads on every DB call.
# Backend is fixed for the process lifetime; the two-key scheme keeps
# correctness if tests switch backends between calls.
_cache: dict[tuple[str, str], str] = {}


def _backend() -> str:
    from aryx.config import get_settings  # lazy — avoids circular at import
    return get_settings().effective_db_backend()


def load(name: str) -> str:
    """Return the SQL text for a named query file (without the .sql suffix).

    When ARYX_DB_BACKEND=oci, an Oracle-specific override in queries/oracle/
    is returned if one exists; otherwise falls back to the standard file.
    Result is cached per (name, backend) so each file is read at most once.

    Args:
        name: Query file stem, e.g. 'insert_run'.

    Returns:
        The file's SQL text, stripped.
    """
    backend = _backend()
    key = (name, backend)
    if key in _cache:
        return _cache[key]
    if backend == "oci":
        oracle_path = _ORACLE_DIR / f"{name}.sql"
        if oracle_path.exists():
            sql = oracle_path.read_text(encoding="utf-8").strip()
            _cache[key] = sql
            return sql
    sql = (_SQL_DIR / f"{name}.sql").read_text(encoding="utf-8").strip()
    _cache[key] = sql
    return sql
