"""Brief-column decoding for the Oracle workspace store.

Split out of `store/oracle_workspace.py` (Raven Style Compliance Plan,
Phase 2b, 2026-09-03). Zero patch risk — confirmed via grep (the test
file's patches all target `load`/`get_oracle_pool`, never `_parse_brief`).
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _parse_brief(v: Any) -> dict:
    """Return the brief column value as a Python dict.

    oracledb thin may return Oracle 23ai JSON columns as either a Python dict
    (native JSON type) or a plain str (JSON text). Handle both so the API
    response always carries a JSON object, never a raw JSON-encoded string.
    """
    logger.info("oracle brief: raw type=%s", type(v).__name__)
    logger.debug("oracle brief: raw value=%r", v)
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            result = parsed if isinstance(parsed, dict) else {}
            logger.info("oracle brief: str → dict keys=%s", list(result.keys()))
            return result
        except Exception as exc:
            logger.warning("oracle brief: json.loads failed error=%s raw=%r", exc, v)
            return {}
    result = v or {}
    logger.info("oracle brief: native %s keys=%s", type(v).__name__,
                list(result.keys()) if isinstance(result, dict) else "non-dict")
    return result
