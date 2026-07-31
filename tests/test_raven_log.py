"""Unit tests for the Aryx raven-log wrapper and /health sample path."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")
FastAPI = fastapi.FastAPI
TestClient = testclient.TestClient


def test_raven_log_emits_schema_v1_json(capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("raven_logger")
    from aryx.raven_log import raven_log

    record = raven_log(
        level="INFO",
        criticality="P4",
        message="unit test emit",
        error_code="",
        context={"test": True},
    )
    assert record["schema_version"] in ("1", "1.0")
    assert record["service"] == "aryx-api"
    assert record["project"] == "aryx"
    assert record["level"] == "INFO"
    assert record["criticality"] == "P4"
    assert record["trace_id"]
    assert record["span_id"]

    out = capsys.readouterr().out.strip().splitlines()[-1]
    parsed = json.loads(out)
    assert parsed["message"] == "unit test emit"


def test_raven_log_requires_error_code_on_error() -> None:
    pytest.importorskip("raven_logger")
    from aryx.raven_log import raven_log

    with pytest.raises(ValueError, match="error_code"):
        raven_log(
            level="ERROR",
            criticality="P2",
            message="boom",
            error_code="",
        )


def test_health_emits_raven_log() -> None:
    pytest.importorskip("raven_logger")
    from aryx.api.graph_api import graph_router

    app = FastAPI()
    app.include_router(graph_router())
    client = TestClient(app)

    with patch("aryx.api.graph_api.raven_log") as mock_log:
        mock_log.return_value = {}
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_log.assert_called_once()
    kwargs = mock_log.call_args.kwargs
    assert kwargs["level"] == "INFO"
    assert kwargs["criticality"] == "P4"
    assert kwargs["message"] == "health check ok"
    assert kwargs["context"] == {"path": "/health"}
