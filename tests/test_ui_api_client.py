"""Tests for the Streamlit UI's thin HTTP client (aryx.ui.api) — CPQ session
threading and the new share_config() call, both previously untested."""
import io
import json
from unittest.mock import MagicMock, patch

from aryx.ui import api


def _fake_urlopen(payload: dict):
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__.return_value = resp
    return resp


def test_ask_sends_session_data_for_cpq_continuity():
    with patch("aryx.ui.api.urllib.request.urlopen",
               return_value=_fake_urlopen({"answer": "ok"})) as mock_open:
        api.ask("configure sl3500", [], session_data={"status": "configuring", "filled": {"a": "1"}})

    sent = json.loads(mock_open.call_args[0][0].data)
    assert sent["session_data"] == {"status": "configuring", "filled": {"a": "1"}}
    assert sent["question"] == "configure sl3500"


def test_ask_defaults_session_data_to_empty_dict():
    with patch("aryx.ui.api.urllib.request.urlopen",
               return_value=_fake_urlopen({"answer": "ok"})) as mock_open:
        api.ask("hello")

    sent = json.loads(mock_open.call_args[0][0].data)
    assert sent["session_data"] == {}


def test_share_config_posts_to_share_config_not_api_prefixed():
    """Streamlit hits the Aryx API directly (no Next.js proxy stripping /api),
    so this must be /share-config — using /api/share-config here would 404."""
    with patch("aryx.ui.api.urllib.request.urlopen",
               return_value=_fake_urlopen({"shared": True})) as mock_open:
        result = api.share_config("conv-123", {"carrier": "Verizon"},
                                  endpoint_url="https://partner.example/ingest",
                                  auth_header_value="Bearer secret")

    request = mock_open.call_args[0][0]
    assert request.full_url == "http://localhost:8088/share-config"
    sent = json.loads(request.data)
    assert sent["conversation_id"] == "conv-123"
    assert sent["config_json"] == {"carrier": "Verizon"}
    assert sent["endpoint_url"] == "https://partner.example/ingest"
    assert sent["auth_header_name"] == "Authorization"
    assert sent["auth_header_value"] == "Bearer secret"
    assert sent["workspace_id"] == api.current_workspace()
    assert result == {"shared": True}
