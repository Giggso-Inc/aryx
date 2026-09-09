"""Trace-directory resolution for the rule trace.

Split out of `cpq/rule_trace.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Only `get_settings` matters here, resolved fresh via a local
import each call — `tests/test_cpq_rule_trace.py` patches
`aryx.config.get_settings` directly (not a per-module rebind), so this
stays correct regardless of which module the function lives in. `_store`/
`_get_or_open`/`sweep_orphans` stay in the hub instead: the same test
file does `monkeypatch.setattr(rule_trace, "_store", ...)`, which only
rebinds the hub module's own attribute — a function resolving `_store()`
from a different module's namespace would miss that patch (caught via a
test failure, not by grep, since `_store` itself isn't a `patch()` string
literal).
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _trace_dir() -> Path | None:
    """Return the configured trace directory, or None if the current
    get_settings() doesn't look like a real Settings instance (e.g. a test
    broadly mocking get_settings() for something unrelated) -- never
    silently write a garbage path built from a mock's repr."""
    from aryx.config import get_settings
    raw = get_settings().cpq_rule_trace_dir
    if not isinstance(raw, str) or not raw:
        logger.warning("rule_trace: cpq_rule_trace_dir is not a real path (%r) -- skipping local file write", raw)
        return None
    d = Path(raw)
    d.mkdir(parents=True, exist_ok=True)
    return d
