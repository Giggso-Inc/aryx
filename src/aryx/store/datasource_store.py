"""CRUD for datasource registry + secret audit log (Slice 2).

Secrets are Fernet-encrypted in datasource_secrets and stored as opaque
ciphertext here; this module never logs or returns plaintext. Every
decrypt-for-use path writes an aryx_secret_audit row so we have a full
trail of who used which secret when.

As of the Raven Style Compliance Plan's Phase 2b (2026-09-03), split into
`datasource_store_crud.py` (`_DatasourceCrudMixin`), mixed into
`DatasourceStore` here. Zero whitebox test patches exist anywhere against
`aryx.store.datasource_store.*` (confirmed via grep), so the split was
purely mechanical. `secret_of`/`open_url` stay here.
"""
from __future__ import annotations

import logging

from aryx import datasource_secrets
from aryx.queries import load
from aryx.store.datasource_store_crud import _DatasourceCrudMixin
from aryx.store.pool import get_pool

__all__ = ["DatasourceStore", "open_url"]

logger = logging.getLogger(__name__)


class DatasourceStore(_DatasourceCrudMixin):
    """Registry of named datasources per workspace, with encrypted secrets."""

    def __init__(self, dsn: str) -> None:
        self._pool = get_pool(dsn)

    def secret_of(self, datasource_id: int, workspace_id: int, actor: str) -> str:
        """Decrypt and return the secret; logs an audit row before returning."""
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(load("select_datasource_by_id"),
                        {"id": int(datasource_id), "workspace_id": int(workspace_id)})
            row = cur.fetchone()
            if not row:
                raise ValueError(f"datasource {datasource_id} not found")
            cur.execute(load("insert_secret_audit"), {
                "datasource_id": int(datasource_id),
                "action": "decrypt", "actor": actor})
        return datasource_secrets.decrypt(row[5] or "")


def open_url(kind: str, config: dict, secret: str) -> str:
    """Build a SQLAlchemy URL from datasource config + decrypted secret."""
    drivers = {
        "postgresql": "postgresql+psycopg", "postgres": "postgresql+psycopg",
        "mysql": "mysql+pymysql", "mariadb": "mysql+pymysql",
        "oracle": "oracle+oracledb", "sqlite": "sqlite",
    }
    if kind == "sqlite":
        return f"sqlite:///{config.get('database', '')}"
    driver = drivers.get(kind)
    if not driver:
        raise ValueError(f"unsupported datasource kind: {kind}")
    user = config.get("user", "")
    auth = f"{user}:{secret}@" if user else ""
    port = f":{config['port']}" if config.get("port") else ""
    return (f"{driver}://{auth}{config.get('host', '')}{port}"
            f"/{config.get('database', '')}")
