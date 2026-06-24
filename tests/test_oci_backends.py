"""Tests for OCI backend toggle — parse, embed, and LLM paths.

All tests mock the OCI SDK so no real OCI credentials are needed.
Uses reset_clients() to clear singleton state between tests.
"""
from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _stub_psycopg() -> None:
    """Stub psycopg so connectors/__init__.py import chain doesn't fail locally."""
    if "psycopg" not in sys.modules:
        psycopg = types.ModuleType("psycopg")
        psycopg.connect = MagicMock()
        psycopg.Connection = MagicMock()
        psycopg.Cursor = MagicMock()
        psycopg_sql = types.ModuleType("psycopg.sql")
        psycopg_sql.SQL = MagicMock()
        psycopg_sql.Identifier = MagicMock()
        psycopg.sql = psycopg_sql
        psycopg_types = types.ModuleType("psycopg.types")
        psycopg_types_json = types.ModuleType("psycopg.types.json")
        psycopg_types_json.Json = MagicMock()
        psycopg_types.json = psycopg_types_json
        psycopg.types = psycopg_types
        sys.modules["psycopg"] = psycopg
        sys.modules["psycopg.sql"] = psycopg_sql
        sys.modules["psycopg.types"] = psycopg_types
        sys.modules["psycopg.types.json"] = psycopg_types_json
        psycopg_pool = types.ModuleType("psycopg_pool")
        psycopg_pool.ConnectionPool = MagicMock()
        sys.modules["psycopg_pool"] = psycopg_pool


_stub_psycopg()


def _make_oci_stub() -> types.ModuleType:
    """Build a minimal oci stub so imports succeed without the real SDK."""
    oci = types.ModuleType("oci")

    # ── auth ──────────────────────────────────────────────────────────────────
    auth = types.ModuleType("oci.auth")
    signers = types.ModuleType("oci.auth.signers")
    signers.InstancePrincipalsSecurityTokenSigner = MagicMock(
        side_effect=Exception("not on OCI")
    )
    auth.signers = signers
    oci.auth = auth

    # ── config ────────────────────────────────────────────────────────────────
    cfg = types.ModuleType("oci.config")
    cfg.from_file = MagicMock(return_value={"region": "us-chicago-1"})
    oci.config = cfg

    # ── ai_document ───────────────────────────────────────────────────────────
    ai_doc = types.ModuleType("oci.ai_document")
    ai_doc_models = types.ModuleType("oci.ai_document.models")
    ai_doc_models.DocumentTextDetectionFeature = MagicMock
    ai_doc_models.DocumentTableDetectionFeature = MagicMock
    ai_doc_models.InlineDocumentDetails = MagicMock
    ai_doc_models.AnalyzeDocumentDetails = MagicMock
    ai_doc.models = ai_doc_models
    ai_doc.AIServiceDocumentClient = MagicMock
    oci.ai_document = ai_doc

    # ── generative_ai_inference ───────────────────────────────────────────────
    genai = types.ModuleType("oci.generative_ai_inference")
    genai_models = types.ModuleType("oci.generative_ai_inference.models")
    genai_models.EmbedTextDetails = MagicMock
    genai_models.OnDemandServingMode = MagicMock
    genai_models.GenerateTextDetails = MagicMock
    genai_models.CohereLlmInferenceRequest = MagicMock
    genai.models = genai_models
    genai.GenerativeAiInferenceClient = MagicMock
    oci.generative_ai_inference = genai

    # ── functions ─────────────────────────────────────────────────────────────
    fn_mod = types.ModuleType("oci.functions")
    fn_models = types.ModuleType("oci.functions.models")
    fn_models.CreateApplicationDetails = MagicMock
    fn_models.CreateFunctionDetails = MagicMock
    fn_models.UpdateFunctionDetails = MagicMock
    fn_mod.models = fn_models
    fn_mod.FunctionsManagementClient = MagicMock
    fn_mod.FunctionsInvokeClient = MagicMock
    oci.functions = fn_mod

    # register all sub-modules so `import oci.x` resolves
    for name in [
        "oci.auth", "oci.auth.signers", "oci.config",
        "oci.ai_document", "oci.ai_document.models",
        "oci.generative_ai_inference", "oci.generative_ai_inference.models",
        "oci.functions", "oci.functions.models",
    ]:
        sys.modules[name] = eval(name.replace("oci.", "").replace(".", "_"),  # noqa: S307
                                 {"auth": auth, "auth_signers": signers,
                                  "config": cfg, "ai_document": ai_doc,
                                  "ai_document_models": ai_doc_models,
                                  "generative_ai_inference": genai,
                                  "generative_ai_inference_models": genai_models,
                                  "functions": fn_mod,
                                  "functions_models": fn_models})
    return oci


# ---------------------------------------------------------------------------
# Config / resolution helpers
# ---------------------------------------------------------------------------

class TestBackendResolution(unittest.TestCase):
    """effective_*_backend() resolution order."""

    def _settings(self, **env: str):
        from aryx.config import Settings
        return Settings(_env_file=None, **env)

    def test_all_local_by_default(self) -> None:
        s = self._settings()
        assert s.effective_parse_backend() == "local"
        assert s.effective_embed_backend() == "local"
        assert s.effective_llm_cheap_backend() == "local"
        assert s.effective_llm_frontier_backend() == "local"
        assert s.effective_db_backend() == "local"
        assert s.effective_worker_backend() == "local"
        assert s.effective_graph_backend() == "falkordb"

    def test_oci_mode_flips_all_to_oci(self) -> None:
        s = self._settings(oci_mode=True)
        assert s.effective_parse_backend() == "oci"
        assert s.effective_embed_backend() == "oci"
        assert s.effective_llm_cheap_backend() == "oci"
        assert s.effective_llm_frontier_backend() == "oci"
        assert s.effective_db_backend() == "oci"
        assert s.effective_worker_backend() == "oci"

    def test_per_service_overrides_oci_mode(self) -> None:
        s = self._settings(oci_mode=True, embed_backend="local")
        assert s.effective_parse_backend() == "oci"
        assert s.effective_embed_backend() == "local"   # override wins
        assert s.effective_llm_cheap_backend() == "oci"

    def test_explicit_oci_without_oci_mode(self) -> None:
        s = self._settings(parse_backend="oci")
        assert s.effective_parse_backend() == "oci"
        assert s.effective_embed_backend() == "local"   # others stay local

    def test_graph_backend_defaults_to_falkordb(self) -> None:
        s = self._settings(oci_mode=True)
        # graph has its own phase2_default; oci_mode overrides it
        assert s.effective_graph_backend() == "oci"

    def test_graph_backend_falkordb_without_oci_mode(self) -> None:
        s = self._settings()
        assert s.effective_graph_backend() == "falkordb"


# ---------------------------------------------------------------------------
# OCI Document connector
# ---------------------------------------------------------------------------

class TestOciDocConnector(unittest.TestCase):
    """OciDocConnector behaviour without real OCI credentials."""

    def setUp(self) -> None:
        from aryx.oci_client import reset_clients
        reset_clients()

    def test_raises_without_compartment_id(self) -> None:
        from aryx.config import Settings, get_settings
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        with patch.object(cfg_mod, "get_settings",
                          return_value=Settings(_env_file=None,
                                                parse_backend="oci",
                                                oci_compartment_id="")):
            from aryx.connectors.oci_doc import OciDocConnector
            conn = OciDocConnector(Path("/tmp/dummy.pdf"))
            # compartment_id missing → RuntimeError before any API call
            with self.assertRaises(RuntimeError, msg="ARYX_OCI_COMPARTMENT_ID"):
                list(conn.extract_pages())

    def test_raises_on_oversized_file(self) -> None:
        import tempfile, os
        from aryx.connectors.oci_doc import OciDocConnector, _OCI_INLINE_MAX_BYTES
        from aryx.config import Settings
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        # Write a file larger than the inline limit
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
            f.write(b"x" * (_OCI_INLINE_MAX_BYTES + 1))
            big_path = Path(f.name)
        try:
            with patch.object(cfg_mod, "get_settings",
                              return_value=Settings(_env_file=None,
                                                    parse_backend="oci",
                                                    oci_compartment_id="ocid1.test")):
                conn = OciDocConnector(big_path)
                with self.assertRaises(ValueError, msg="inline limit"):
                    list(conn.extract_pages())
        finally:
            os.unlink(big_path)


# ---------------------------------------------------------------------------
# OCI GenAI JSON provider
# ---------------------------------------------------------------------------

class TestOciGenaiJson(unittest.TestCase):
    """oci_genai_json() — JSON parse guard and happy path."""

    def setUp(self) -> None:
        from aryx.oci_client import reset_clients
        reset_clients()
        # inject oci stub
        self._oci = _make_oci_stub()
        sys.modules["oci"] = self._oci

    def tearDown(self) -> None:
        from aryx.oci_client import reset_clients
        reset_clients()

    def _make_spec(self) -> object:
        from aryx.broker.specs import ModelSpec
        return ModelSpec(name="cohere.command-r-plus", provider="oci",
                         tier="frontier", endpoint="")

    def test_raises_on_non_json_response(self) -> None:
        from aryx.llm_providers import oci_genai_json
        from aryx.config import Settings
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        # OCI client returns HTML/plain text instead of JSON
        mock_client = MagicMock()
        mock_client.generate_text.return_value.data.inference_response \
            .generated_texts = [MagicMock(text="Sorry, service unavailable")]

        with patch("aryx.oci_client.get_genai_client", return_value=mock_client), \
             patch.object(cfg_mod, "get_settings",
                          return_value=Settings(_env_file=None,
                                                oci_compartment_id="ocid1.test")):
            with self.assertRaises(RuntimeError, msg="non-JSON"):
                oci_genai_json(self._make_spec(), "system prompt", "user prompt")

    def test_strips_code_fences_and_parses(self) -> None:
        from aryx.llm_providers import oci_genai_json
        from aryx.config import Settings
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        payload = json.dumps({"result": "ok"})
        mock_response_text = f"```json\n{payload}\n```"
        mock_client = MagicMock()
        mock_client.generate_text.return_value.data.inference_response \
            .generated_texts = [MagicMock(text=mock_response_text)]

        with patch("aryx.oci_client.get_genai_client", return_value=mock_client), \
             patch.object(cfg_mod, "get_settings",
                          return_value=Settings(_env_file=None,
                                                oci_compartment_id="ocid1.test")):
            data, in_tok, out_tok = oci_genai_json(
                self._make_spec(), "system", "user"
            )
        assert data == {"result": "ok"}
        assert in_tok > 0
        assert out_tok > 0

    def test_token_estimate_positive(self) -> None:
        from aryx.llm_providers import oci_genai_json
        from aryx.config import Settings
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        mock_client = MagicMock()
        mock_client.generate_text.return_value.data.inference_response \
            .generated_texts = [MagicMock(text='{"x": 1}')]

        with patch("aryx.oci_client.get_genai_client", return_value=mock_client), \
             patch.object(cfg_mod, "get_settings",
                          return_value=Settings(_env_file=None,
                                                oci_compartment_id="ocid1.test")):
            _, in_tok, out_tok = oci_genai_json(
                self._make_spec(), "a" * 400, "b" * 400
            )
        assert in_tok > 0, "token estimate must be positive"


# ---------------------------------------------------------------------------
# Embed routing
# ---------------------------------------------------------------------------

class TestEmbedRouting(unittest.TestCase):
    """Broker.embed() routes to OCI or Ollama based on backend setting."""

    def test_local_mode_calls_ollama_path(self) -> None:
        from aryx.broker import Broker
        from aryx.broker.registry import Registry
        from aryx.broker.governor import TokenGovernor
        from aryx.config import Settings
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        broker = Broker(Registry(), TokenGovernor({}),
                        embed_config={"model": "nomic", "endpoint": "http://ollama:11434"})

        with patch.object(cfg_mod, "get_settings",
                          return_value=Settings(_env_file=None)):
            with patch.object(broker, "_ollama_embed",
                               return_value=[[0.1, 0.2]]) as mock_ollama:
                broker.embed(["hello"])
                mock_ollama.assert_called_once_with(["hello"])

    def test_oci_mode_calls_oci_embed_path(self) -> None:
        sys.modules["oci"] = _make_oci_stub()
        from aryx.broker import Broker
        from aryx.broker.registry import Registry
        from aryx.broker.governor import TokenGovernor
        from aryx.config import Settings
        import aryx.config as cfg_mod
        from aryx.oci_client import reset_clients
        reset_clients()
        cfg_mod.get_settings.cache_clear()

        broker = Broker(Registry(), TokenGovernor({}))

        with patch.object(cfg_mod, "get_settings",
                          return_value=Settings(_env_file=None,
                                                embed_backend="oci",
                                                oci_compartment_id="ocid1.test")):
            with patch.object(broker, "_oci_embed",
                               return_value=[[0.5] * 1024]) as mock_oci:
                broker.embed(["hello"])
                mock_oci.assert_called_once()


# ---------------------------------------------------------------------------
# G1 fix — complete_text() OCI short-circuit
# ---------------------------------------------------------------------------

class TestCompleteTextOciPath(unittest.TestCase):
    """complete_text() must short-circuit to OCI when backend=oci."""

    def setUp(self) -> None:
        sys.modules["oci"] = _make_oci_stub()
        from aryx.oci_client import reset_clients
        reset_clients()

    def tearDown(self) -> None:
        from aryx.oci_client import reset_clients
        reset_clients()

    def test_complete_text_uses_oci_when_backend_oci(self) -> None:
        from aryx.llm import complete_text
        from aryx.broker import Broker
        from aryx.broker.registry import Registry
        from aryx.broker.governor import TokenGovernor
        from aryx.config import Settings
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        # Empty registry — broker.choose() would raise LookupError without fix
        broker = Broker(Registry(), TokenGovernor({}))

        mock_client = MagicMock()
        mock_client.generate_text.return_value.data.inference_response \
            .generated_texts = [MagicMock(text='"hello from OCI"')]

        with patch("aryx.oci_client.get_genai_client", return_value=mock_client), \
             patch.object(cfg_mod, "get_settings",
                          return_value=Settings(_env_file=None,
                                                llm_cheap_backend="oci",
                                                oci_compartment_id="ocid1.test")):
            text, in_tok, out_tok = complete_text(broker, "cheap", "system", "user")

        assert isinstance(text, str)
        assert in_tok > 0
        mock_client.generate_text.assert_called_once()

    def test_complete_text_local_mode_uses_broker(self) -> None:
        """Local mode must still call broker.choose(), not OCI."""
        from aryx.llm import complete_text
        from aryx.broker import Broker
        from aryx.broker.registry import Registry
        from aryx.broker.governor import TokenGovernor
        from aryx.config import Settings
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        broker = Broker(Registry(), TokenGovernor({}))

        with patch.object(cfg_mod, "get_settings",
                          return_value=Settings(_env_file=None)):
            # No local models → LookupError — proves broker.choose() was called
            with self.assertRaises(LookupError):
                complete_text(broker, "cheap", "system", "user")


# ---------------------------------------------------------------------------
# G2 fix — _connector_for() extension guard for OCI
# ---------------------------------------------------------------------------

class TestConnectorForOciExtensionGuard(unittest.TestCase):
    """_connector_for() must not route data files (.csv/.json) to OCI."""

    def test_csv_uses_local_connector_even_in_oci_mode(self) -> None:
        from aryx.connectors.doc_router import _connector_for
        from aryx.config import Settings
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        with patch.object(cfg_mod, "get_settings",
                          return_value=Settings(_env_file=None,
                                                parse_backend="oci")):
            # .csv is not in _EXT_MAP — should raise ValueError (unsupported),
            # NOT route to OCI Doc Understanding
            with self.assertRaises(ValueError, msg="unsupported document type"):
                _connector_for(Path("data.csv"))

    def test_json_uses_local_connector_even_in_oci_mode(self) -> None:
        from aryx.connectors.doc_router import _connector_for
        from aryx.config import Settings
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        with patch.object(cfg_mod, "get_settings",
                          return_value=Settings(_env_file=None,
                                                parse_backend="oci")):
            with self.assertRaises(ValueError, msg="unsupported document type"):
                _connector_for(Path("records.json"))

    def test_pdf_routes_to_oci_in_oci_mode(self) -> None:
        from aryx.connectors.doc_router import _connector_for
        from aryx.connectors.oci_doc import OciDocConnector
        from aryx.config import Settings
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        with patch.object(cfg_mod, "get_settings",
                          return_value=Settings(_env_file=None,
                                                parse_backend="oci")):
            conn = _connector_for(Path("report.pdf"))
        assert isinstance(conn, OciDocConnector)

    def test_pdf_routes_to_pdf_connector_in_local_mode(self) -> None:
        from aryx.connectors.doc_router import _connector_for
        from aryx.connectors.pdf import PdfConnector
        from aryx.config import Settings
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        with patch.object(cfg_mod, "get_settings",
                          return_value=Settings(_env_file=None)):
            conn = _connector_for(Path("report.pdf"))
        assert isinstance(conn, PdfConnector)


# ---------------------------------------------------------------------------
# oci_broker() factory
# ---------------------------------------------------------------------------

class TestOciBroker(unittest.TestCase):
    """oci_broker() must return a Broker seeded with OCI GenAI Cohere models."""

    def _settings(self, **kw):
        from aryx.config import Settings
        return Settings(_env_file=None, **kw)

    def test_returns_broker_instance(self) -> None:
        from aryx.broker import Broker, oci_broker
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()
        with patch.object(cfg_mod, "get_settings",
                          return_value=self._settings(oci_mode=True)):
            b = oci_broker()
        assert isinstance(b, Broker)

    def test_has_cheap_and_frontier_models(self) -> None:
        from aryx.broker import oci_broker
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()
        with patch.object(cfg_mod, "get_settings",
                          return_value=self._settings(oci_mode=True)):
            b = oci_broker()
        tiers = {m.tier for m in b.models()}
        assert "cheap" in tiers
        assert "frontier" in tiers

    def test_all_models_have_oci_provider(self) -> None:
        from aryx.broker import oci_broker
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()
        with patch.object(cfg_mod, "get_settings",
                          return_value=self._settings(oci_mode=True)):
            b = oci_broker()
        assert all(m.provider == "oci" for m in b.models())

    def test_default_cheap_model_is_command_r(self) -> None:
        from aryx.broker import oci_broker
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()
        with patch.object(cfg_mod, "get_settings",
                          return_value=self._settings(oci_mode=True)):
            b = oci_broker()
        cheap = next(m for m in b.models() if m.tier == "cheap")
        assert "command-r" in cheap.name

    def test_model_override_is_respected(self) -> None:
        from aryx.broker import oci_broker
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()
        with patch.object(cfg_mod, "get_settings",
                          return_value=self._settings(
                              oci_mode=True,
                              llm_cheap_model_override="cohere.custom-cheap",
                          )):
            b = oci_broker()
        cheap = next(m for m in b.models() if m.tier == "cheap")
        assert cheap.name == "cohere.custom-cheap"

    def test_no_ollama_models_in_oci_broker(self) -> None:
        from aryx.broker import oci_broker
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()
        with patch.object(cfg_mod, "get_settings",
                          return_value=self._settings(oci_mode=True)):
            b = oci_broker()
        assert not any(m.provider == "ollama" for m in b.models())


# ---------------------------------------------------------------------------
# JobStore.sweep_stale()
# ---------------------------------------------------------------------------

class TestSweepStaleJobs(unittest.TestCase):
    """sweep_stale() must UPDATE stale rows and return the affected count."""

    def _make_store_with_mock_pool(self, rowcount: int = 0):
        """Return a JobStore whose pool is fully mocked."""
        from aryx.store.job_store import JobStore

        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.rowcount = rowcount

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur

        mock_pool = MagicMock()
        mock_pool.connection.return_value = mock_conn

        store = JobStore.__new__(JobStore)
        store._pool = mock_pool
        return store, mock_cur

    def test_returns_zero_when_no_stale_jobs(self) -> None:
        store, _ = self._make_store_with_mock_pool(rowcount=0)
        assert store.sweep_stale(10) == 0

    def test_returns_count_of_swept_jobs(self) -> None:
        store, _ = self._make_store_with_mock_pool(rowcount=3)
        assert store.sweep_stale(10) == 3

    def test_executes_with_timeout_parameter(self) -> None:
        store, mock_cur = self._make_store_with_mock_pool(rowcount=1)
        store.sweep_stale(15)
        call_args = mock_cur.execute.call_args
        # Second positional arg is the params tuple — must contain the timeout value
        params = call_args[0][1]
        assert params == (15,)

    def test_logs_warning_when_rows_swept(self) -> None:
        import logging
        store, _ = self._make_store_with_mock_pool(rowcount=2)
        with self.assertLogs("aryx.store.job_store", level=logging.WARNING):
            store.sweep_stale(10)

    def test_no_log_when_zero_rows(self) -> None:
        import logging as _logging
        store, _ = self._make_store_with_mock_pool(rowcount=0)
        # assertLogs raises AssertionError if no logs emitted — that's the pass condition
        with self.assertRaises(AssertionError):
            with self.assertLogs("aryx.store.job_store", level=_logging.WARNING):
                store.sweep_stale(10)


# ---------------------------------------------------------------------------
# OCI Functions provisioner
# ---------------------------------------------------------------------------

class TestOciFunctionsProvisioner(unittest.TestCase):
    """provision_ingest_function() must create or update the OCI Function."""

    def setUp(self) -> None:
        sys.modules["oci"] = _make_oci_stub()
        from aryx.oci_client import reset_clients
        reset_clients()

    def tearDown(self) -> None:
        from aryx.oci_client import reset_clients
        reset_clients()

    def _settings(self, **kw):
        from aryx.config import Settings
        return Settings(
            _env_file=None,
            oci_mode=True,
            oci_compartment_id="ocid1.compartment.oc1..test",
            oci_region="us-chicago-1",
            oci_adb_dsn="tcps://adb.test.oraclecloud.com:1522/test_high",
            db_user="aryx_user",
            db_password="secret123",
            **kw,
        )

    def _make_mgmt_mock(self, has_app: bool = False, has_fn: bool = False) -> MagicMock:
        mock_mgmt = MagicMock()

        existing_app = MagicMock()
        existing_app.id = "ocid1.fnapp.oc1..existing"
        mock_mgmt.list_applications.return_value.data = [existing_app] if has_app else []

        created_app = MagicMock()
        created_app.id = "ocid1.fnapp.oc1..created"
        mock_mgmt.create_application.return_value.data = created_app

        existing_fn = MagicMock()
        existing_fn.id = "ocid1.fnfunc.oc1..existing"
        mock_mgmt.list_functions.return_value.data = [existing_fn] if has_fn else []

        created_fn = MagicMock()
        created_fn.id = "ocid1.fnfunc.oc1..created"
        mock_mgmt.create_function.return_value.data = created_fn

        return mock_mgmt

    def test_creates_app_and_function_when_neither_exists(self) -> None:
        from aryx.worker.oci_functions_provisioner import provision_ingest_function
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        mock_mgmt = self._make_mgmt_mock(has_app=False, has_fn=False)
        with (
            patch.object(cfg_mod, "get_settings", return_value=self._settings()),
            patch("aryx.oci_client.get_fn_mgmt_client", return_value=mock_mgmt),
            patch.dict("os.environ", {}, clear=False),
        ):
            fn_id = provision_ingest_function(
                subnet_id="ocid1.subnet.oc1..test",
                image_uri="us-chicago-1.ocir.io/ns/aryx/aryx-ingest-fn:latest",
            )

        assert fn_id == "ocid1.fnfunc.oc1..created"
        mock_mgmt.create_application.assert_called_once()
        mock_mgmt.create_function.assert_called_once()

    def test_skips_app_creation_when_app_exists(self) -> None:
        from aryx.worker.oci_functions_provisioner import provision_ingest_function
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        mock_mgmt = self._make_mgmt_mock(has_app=True, has_fn=False)
        with (
            patch.object(cfg_mod, "get_settings", return_value=self._settings()),
            patch("aryx.oci_client.get_fn_mgmt_client", return_value=mock_mgmt),
            patch.dict("os.environ", {}, clear=False),
        ):
            fn_id = provision_ingest_function(
                subnet_id="ocid1.subnet.oc1..test",
                image_uri="us-chicago-1.ocir.io/ns/aryx/aryx-ingest-fn:latest",
            )

        mock_mgmt.create_application.assert_not_called()
        assert fn_id == "ocid1.fnfunc.oc1..created"

    def test_updates_function_when_fn_exists(self) -> None:
        from aryx.worker.oci_functions_provisioner import provision_ingest_function
        import aryx.config as cfg_mod
        cfg_mod.get_settings.cache_clear()

        mock_mgmt = self._make_mgmt_mock(has_app=True, has_fn=True)
        with (
            patch.object(cfg_mod, "get_settings", return_value=self._settings()),
            patch("aryx.oci_client.get_fn_mgmt_client", return_value=mock_mgmt),
            patch.dict("os.environ", {}, clear=False),
        ):
            fn_id = provision_ingest_function(
                subnet_id="ocid1.subnet.oc1..test",
                image_uri="us-chicago-1.ocir.io/ns/aryx/aryx-ingest-fn:latest",
            )

        assert fn_id == "ocid1.fnfunc.oc1..existing"
        mock_mgmt.update_function.assert_called_once()
        mock_mgmt.create_function.assert_not_called()

    def test_build_fn_config_contains_required_keys(self) -> None:
        from aryx.worker.oci_functions_provisioner import _build_fn_config

        cfg = _build_fn_config(self._settings())

        required = {
            "ARYX_DB_BACKEND", "ARYX_OCI_ADB_DSN", "ARYX_RDB_DSN",
            "ARYX_DB_USER", "ARYX_DB_PASSWORD", "ARYX_OCI_MODE",
            "ARYX_OCI_REGION", "ARYX_OCI_COMPARTMENT_ID",
            "ARYX_EMBED_BACKEND", "ARYX_LLM_CHEAP_BACKEND", "ARYX_LLM_FRONTIER_BACKEND",
            "ARYX_PARSE_BACKEND", "ARYX_GRAPH_BACKEND",
        }
        missing = required - cfg.keys()
        assert not missing, f"fn config missing keys: {missing}"

    def test_build_fn_config_excludes_empty_values(self) -> None:
        from aryx.worker.oci_functions_provisioner import _build_fn_config
        cfg = _build_fn_config(self._settings())
        assert all(v for v in cfg.values()), "config contains empty values"

    def test_build_fn_config_model_override_included_when_set(self) -> None:
        from aryx.worker.oci_functions_provisioner import _build_fn_config
        cfg = _build_fn_config(self._settings(llm_cheap_model_override="cohere.custom"))
        assert cfg.get("ARYX_LLM_CHEAP_MODEL_OVERRIDE") == "cohere.custom"

    def test_build_fn_config_model_override_absent_when_empty(self) -> None:
        from aryx.worker.oci_functions_provisioner import _build_fn_config
        cfg = _build_fn_config(self._settings())
        assert "ARYX_LLM_CHEAP_MODEL_OVERRIDE" not in cfg


if __name__ == "__main__":
    unittest.main()
