"""Application configuration loaded from the environment (12-factor).

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), the ~90
settings fields are split across 10 themed `BaseSettings` mixins (config_
core/graph/relate/dimension/ingest/fk_detection/resolution/llm/cpq_intent/
documents/ontology/oci) — pydantic v2 merges fields from every base class
into the final class's `model_fields`, so this is behavior-preserving
(verified empirically before splitting: a throwaway 3-mixin `BaseSettings`
composition correctly merged all fields and respected the final class's
own `env_prefix`/`extra` config). `Settings` itself — the only class ever
instantiated — stays here with the `model_config`, the 7 `effective_*`/
`_resolve` backend-resolution methods, and `get_settings()`.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from aryx.config.config_core import CoreSettingsMixin
from aryx.config.config_cpq_intent import CpqIntentSettingsMixin
from aryx.config.config_dimension import DimensionSettingsMixin
from aryx.config.config_documents import DocumentSettingsMixin
from aryx.config.config_fk_detection import FkDetectionSettingsMixin
from aryx.config.config_graph import GraphSettingsMixin
from aryx.config.config_ingest import IngestSettingsMixin
from aryx.config.config_llm import LlmSettingsMixin
from aryx.config.config_oci import OciSettingsMixin
from aryx.config.config_ontology import OntologySettingsMixin
from aryx.config.config_relate import RelateSettingsMixin
from aryx.config.config_resolution import ResolutionSettingsMixin


class Settings(
    CoreSettingsMixin,
    GraphSettingsMixin,
    RelateSettingsMixin,
    DimensionSettingsMixin,
    IngestSettingsMixin,
    FkDetectionSettingsMixin,
    ResolutionSettingsMixin,
    LlmSettingsMixin,
    CpqIntentSettingsMixin,
    DocumentSettingsMixin,
    OntologySettingsMixin,
    OciSettingsMixin,
):
    """Aryx runtime settings sourced from ARYX_-prefixed env variables."""

    # extra="ignore": the .env file is shared with docker-compose services
    # (SMTP, SSO, frontend URLs, ...) — keys that aren't Aryx settings must
    # not fail validation.
    model_config = SettingsConfigDict(env_prefix="ARYX_", env_file=".env",
                                      extra="ignore")

    # ── Backend resolution helpers ────────────────────────────────────────────
    def _resolve(self, per_service: str, phase2_default: str = "local") -> str:
        """Return per_service value if set, else 'oci' if oci_mode, else default."""
        if per_service:
            return per_service
        return "oci" if self.oci_mode else phase2_default

    def effective_parse_backend(self) -> str:
        """Return the resolved parse backend (oci or local)."""
        return self._resolve(self.parse_backend)

    def effective_embed_backend(self) -> str:
        """Return the resolved embedding backend (local, OCI, or Gemini)."""
        return self._resolve(self.embed_backend)

    def effective_llm_cheap_backend(self) -> str:
        """Return the resolved cheap-LLM backend (oci or ollama)."""
        return self._resolve(self.llm_cheap_backend)

    def effective_llm_frontier_backend(self) -> str:
        """Return the resolved frontier-LLM backend (oci or ollama)."""
        return self._resolve(self.llm_frontier_backend)

    def effective_db_backend(self) -> str:
        """Return the resolved database backend (oci or postgres)."""
        return self._resolve(self.db_backend)

    def effective_worker_backend(self) -> str:
        """Return the resolved worker backend (oci_functions or local)."""
        return self._resolve(self.worker_backend)

    def effective_graph_backend(self) -> str:
        """Return the resolved graph backend (oci_graph or falkordb)."""
        if self.graph_backend:
            return self.graph_backend
        return "oci_graph" if self.oci_mode else "falkordb"

    def effective_dsn(self) -> str:
        """Return the canonical DB connection string for the active backend.

        OCI deployments set ARYX_OCI_ADB_DSN but may leave ARYX_RDB_DSN at
        its Postgres default. This method resolves the right DSN so callers
        don't need to branch on the backend themselves.
        """
        if self.effective_db_backend() == "oci":
            if not self.oci_adb_dsn:
                raise RuntimeError(
                    "ARYX_OCI_ADB_DSN must be set when ARYX_DB_BACKEND=oci"
                )
            return self.oci_adb_dsn
        return self.rdb_dsn


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()
