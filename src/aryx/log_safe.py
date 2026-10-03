"""Helpers that keep personal data out of log lines.

A log line carries shapes, not values: a length and a short hash for text a
customer typed (enough to tell whether two lines refer to the same message,
not enough to recover it), counts and type names for SQL bind parameters, and a
masked form of cloud identifiers. Use these instead of ``%r`` of the raw value.

Truncating a value is not redaction: the first characters of a message are
usually the part that holds a name, address or phone number.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from collections.abc import Mapping
from typing import Any

_MAX_TYPES = 6
_KEY: bytes | None = None


def _key() -> bytes:
    """Secret for the text digests: ARYX_RAVEN_LOG_HASH_KEY, else random per process.

    With the env var set (same value on every pod) equal texts give equal digests
    across the whole deployment; without it, only within one process. Either way
    the digest cannot be reproduced by hashing guesses outside the deployment.
    """
    global _KEY
    if _KEY is None:
        env = os.environ.get("ARYX_RAVEN_LOG_HASH_KEY", "").strip()
        _KEY = env.encode("utf-8") if env else secrets.token_bytes(32)
    return _KEY


def keyed_digest(text: str, hex_len: int) -> str:
    """Leading ``hex_len`` hex chars of HMAC-SHA256(secret, text)."""
    return hmac.new(_key(), text.encode("utf-8", "replace"), hashlib.sha256).hexdigest()[:hex_len]


def text_ref(text: Any) -> str:
    """Return ``len=<n> sha=<8 hex>`` for a text, or ``-`` when it is empty (never the text).

    The digest is keyed (HMAC with a deployment secret), so short guessable texts
    ("yes", "NA", a number) cannot be recovered by hashing candidates.
    """
    if text is None:
        return "-"
    value = text if isinstance(text, str) else str(text)
    if not value:
        return "-"
    digest = keyed_digest(value, 8)
    return f"len={len(value)} sha={digest}"


def mask_ocid(value: Any) -> str:
    """Mask an OCI identifier, keeping its type prefix and last four characters."""
    text = "" if value is None else str(value)
    if not text:
        return "-"
    head, sep, tail = text.partition("..")
    if sep and tail:
        return f"{head}..***{tail[-4:]}"
    return "***" + text[-4:] if len(text) > 8 else "***"


def _type_names(values: Any) -> str:
    names = sorted({type(v).__name__ for v in values})
    more = "" if len(names) <= _MAX_TYPES else f",+{len(names) - _MAX_TYPES}"
    return ",".join(names[:_MAX_TYPES]) + more


def params_shape(params: Any) -> str:
    """Describe SQL bind parameters as counts and type names, never their values."""
    if params is None:
        return "none"
    if isinstance(params, Mapping):
        return f"named n={len(params)} keys={sorted(map(str, params))[:12]} types={_type_names(params.values())}"
    if isinstance(params, (list, tuple)):
        return f"{type(params).__name__} n={len(params)} types={_type_names(params)}"
    return f"{type(params).__name__}"


def rows_shape(rows: Any) -> str:
    """Describe a batch of rows (or one row) as counts and type names, never their values."""
    if rows is None:
        return "none"
    if isinstance(rows, Mapping):
        return params_shape(rows)
    if isinstance(rows, (list, tuple)) and rows and isinstance(rows[0], (list, tuple, Mapping)):
        return f"rows={len(rows)} first_row: {params_shape(rows[0])}"
    return params_shape(rows)


def ora_code(exc: BaseException) -> str:
    """ORA-/DPY- code from an exception message ('' when none); never the message."""
    m = re.search(r"\b(?:ORA|DPY)-\d{4,5}\b", str(exc))
    return m.group(0) if m else ""
