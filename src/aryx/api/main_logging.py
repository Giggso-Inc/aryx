"""Logging setup for the combined Aryx API app.

Split out of `api/main.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Zero test patches against this module — confirmed via grep.
Executed at import time by `api/main.py`, same as before the split.
"""
from __future__ import annotations

import logging
import os

# Attach a StreamHandler directly to the aryx logger so INFO output always
# reaches stdout regardless of whether uvicorn was started with --log-level.
# Without this, messages propagate to the root logger which uvicorn leaves at
# WARNING by default, silently dropping aryx INFO logs.
# propagate=False prevents double-printing when the caller ALSO configures root.
_log_level = getattr(logging, os.environ.get("ARYX_LOG_LEVEL", "INFO").upper(), logging.INFO)
_aryx_logger = logging.getLogger("aryx")
_aryx_logger.setLevel(_log_level)
if not _aryx_logger.handlers:
    _h = logging.StreamHandler()
    _h.setLevel(_log_level)
    _h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    _aryx_logger.addHandler(_h)
    _aryx_logger.propagate = False

# uvicorn's own access log ("INFO:     127.0.0.1:xxxxx - "GET /health ..."")
# has NO timestamp in its default formatter — every incident triage this
# session needed to correlate an access-log line against a timestamped app
# log line (health-check JSON, cpq_* lines) with no time on the access line
# itself, making it impossible to tell how long a request actually sat
# in-flight from the access log alone. uvicorn.access is a distinct logger
# with its own handler/formatter installed at uvicorn startup — reconfigure
# it here (module import time, so this always runs before the first request)
# rather than depending on a --log-config file being passed to the uvicorn
# CLI invocation in docker-compose.yml's `command:` line.
_access_logger = logging.getLogger("uvicorn.access")
for _h in _access_logger.handlers:
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
