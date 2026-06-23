"""Load SQL from .sql files — keeps SQL out of Python (DB-Guard discipline)."""
from __future__ import annotations

from pathlib import Path

_SQL_DIR = Path(__file__).parent
_ORACLE_DIR = _SQL_DIR / "oracle"


def load(name: str) -> str:
    """Return the SQL text for a named query file (without the .sql suffix).

    When ARYX_DB_BACKEND=oci, an Oracle-specific override in queries/oracle/
    is returned if one exists; otherwise falls back to the standard file.

    Args:
        name: Query file stem, e.g. 'insert_run'.

    Returns:
        The file's SQL text, stripped.
    """
    try:
        from aryx.config import get_settings  # lazy — avoids circular at import
        if get_settings().effective_db_backend() == "oci":
            oracle_path = _ORACLE_DIR / f"{name}.sql"
            if oracle_path.exists():
                return oracle_path.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001 — config not available yet at migration time
        pass
    return (_SQL_DIR / f"{name}.sql").read_text(encoding="utf-8").strip()
