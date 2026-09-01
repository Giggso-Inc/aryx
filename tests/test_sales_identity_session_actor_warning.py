"""sales_streamlit.identity.resolve_actor_id's anonymous-mode warning.

Regression coverage for a finding from post-merge review: the anonymous
session-actor fallback (ARYX_SALES_ALLOW_SESSION_ACTOR=1) identifies an
actor solely by a bearer token in the URL, which is opt-in and intended
for local dev, but has no code-level restriction preventing it from
being enabled in a shared deployment. No full fix exists at this layer
(the review's own suggestion was a comment/guard) -- this adds a loud,
once-per-process warning so the risk is visible in logs rather than silent.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import sales_streamlit.identity as identity_mod
from sales_streamlit.identity import resolve_actor_id


def test_session_actor_mode_logs_warning_once(caplog):
    identity_mod._warned_session_actor_mode = False
    with patch.dict("os.environ", {"ARYX_SALES_ALLOW_SESSION_ACTOR": "1"}, clear=False):
        with caplog.at_level(logging.WARNING, logger="sales_streamlit.identity"):
            resolve_actor_id({}, {}, query_params={})
            resolve_actor_id({}, {}, query_params={})

    warnings = [r for r in caplog.records if "shared/production" in r.message]
    assert len(warnings) == 1  # only the first call logs it


def test_session_actor_mode_still_returns_actor_id():
    identity_mod._warned_session_actor_mode = True  # skip the log noise
    with patch.dict("os.environ", {"ARYX_SALES_ALLOW_SESSION_ACTOR": "1"}, clear=False):
        session_state: dict = {}
        actor_id = resolve_actor_id({}, session_state, query_params={})
    assert actor_id.startswith("session:")
    assert session_state["_aryx_sales_actor_id"] == actor_id


def test_trusted_header_path_never_warns(caplog):
    identity_mod._warned_session_actor_mode = False
    with caplog.at_level(logging.WARNING, logger="sales_streamlit.identity"):
        actor_id = resolve_actor_id({"X-Forwarded-Email": "person@example.com"}, {})
    assert actor_id.startswith("sso:")
    assert not caplog.records
