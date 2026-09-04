"""
Pure helper functions used by app/core/config.py's Settings class.

Extracted from app/core/config.py during Phase 5a file-size compliance
work. These are plain, side-effect-free string/env parsing helpers with
no dependency on the Settings class or the settings singleton, so moving
them here carries none of the risk that splitting the Settings class
itself would carry (see the stated exception in app/core/config.py for
why the class stays in one file).
"""

import os
import json
import base64


def _decode_base64_env_or_passthrough(name: str, default: str = "") -> str:
    """Return a UTF-8 decoded base64 env value, or the raw value when it is plain text."""
    value = os.getenv(name, default)
    if not value:
        return value

    normalized = value.strip()
    padded = normalized + ("=" * (-len(normalized) % 4))
    try:
        decoded_bytes = base64.b64decode(padded, validate=True)
        decoded = decoded_bytes.decode("utf-8")
    except Exception:
        return value

    round_trip = base64.b64encode(decoded.encode("utf-8")).decode("utf-8").rstrip("=")
    if round_trip == normalized.rstrip("="):
        return decoded
    return value


def _parse_env_list(name: str, default: str) -> list[str]:
    """Parse a list env var from either JSON-array or comma-separated syntax."""
    raw_value = os.environ.get(name, default)
    if not raw_value:
        return []

    try:
        parsed = json.loads(raw_value)
    except (json.JSONDecodeError, TypeError, ValueError):
        parsed = None

    if isinstance(parsed, list):
        return [str(item).strip().rstrip("/") for item in parsed if str(item).strip()]

    return [item.strip().rstrip("/") for item in raw_value.split(",") if item.strip()]


def _normalize_url(value: str, default: str = "") -> str:
    """Trim whitespace and trailing slashes from URL-like settings."""
    candidate = (value or default).strip()
    return candidate.rstrip("/") if candidate else ""


def _append_path(base: str, path: str) -> str:
    """Join a normalized base URL with a fixed leading-slash path."""
    root = _normalize_url(base)
    return f"{root}{path}" if root else path
