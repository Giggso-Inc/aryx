"""ontology_api.py's mutating endpoints must all require write_api_key.

Regression coverage for an inconsistency found by post-merge review:
DELETE /ontology/types/{name} had Depends(write_api_key), but POST
/ontology/config, /types/{name}/approve, /types/{name}/parent, /types,
and /import (all of which mutate state -- set_config can flip
export_runtime settings that gate the /export data-exfiltration surface)
had no such guard and relied solely on the global ApiKeyMiddleware, which
can run in optional/off mode. If that's set for a legitimate reason
elsewhere (e.g. a staging environment), these endpoints became
effectively unauthenticated while DELETE alone stayed hard-gated.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")
FastAPI = fastapi.FastAPI
TestClient = testclient.TestClient


@pytest.fixture
def client() -> TestClient:
    from aryx.api.ontology.ontology_api import ontology_router

    app = FastAPI()
    app.include_router(ontology_router())
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("method,path,json_body", [
    ("post", "/ontology/config", {"enabled": True, "formats": ["turtle"],
                                   "base_uri": "http://x", "include_provenance": False}),
    ("post", "/ontology/types/Widget/approve", None),
    ("post", "/ontology/types/Widget/parent", {"parent": None}),
    ("post", "/ontology/types", {"name": "Widget"}),
    ("post", "/ontology/import", {"content": "", "format": "turtle", "filename": "x.ttl",
                                    "workspace_id": 1}),
])
def test_mutating_endpoint_requires_write_api_key(client: TestClient, method, path, json_body):
    with patch.dict(os.environ, {"ARYX_API_AUTH": "required"}):
        response = getattr(client, method)(path, json=json_body)
    assert response.status_code == 401
