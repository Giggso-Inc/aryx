"""Regression test for the 2026-09-16 fix: fn_handler.py's _MAX_ENCODED_B64_
BYTES guard went stale against file_ingest_api.py's _MAX_FILE after PR #326
raised the latter to 500 MB, silently rejecting valid 400-500 MB files on
the OCI-Functions path that the direct-upload path already accepted.

Asserts the RELATIONSHIP dynamically (fn_handler's decoded ceiling must
cover file_ingest_api's current _MAX_FILE with real margin) rather than
hardcoding both sides as literals -- a hardcoded assertion is exactly what
let this go stale silently the first time.
"""
from __future__ import annotations

from aryx.api.file_ingest.file_ingest_limits import _MAX_FILE
from aryx.worker.fn_handler import _MAX_ENCODED_B64_BYTES


def test_fn_handler_decoded_ceiling_covers_current_max_file_with_margin():
    # Base64 inflates size by 4/3 -- a full _MAX_FILE raw upload must
    # decode-fit under fn_handler's encoded cap, with real headroom (not
    # just barely passing), so a future _MAX_FILE raise doesn't silently
    # break this path again the way the 250 MB -> 500 MB raise did.
    decoded_ceiling = _MAX_ENCODED_B64_BYTES * 3 // 4
    assert decoded_ceiling > _MAX_FILE, (
        f"fn_handler's decoded ceiling ({decoded_ceiling} bytes) no longer "
        f"covers file_ingest_api._MAX_FILE ({_MAX_FILE} bytes) -- a file "
        "the direct-upload path accepts would be wrongly rejected on the "
        "OCI-Functions path. Raise _MAX_ENCODED_B64_BYTES to match."
    )
    margin_bytes = decoded_ceiling - _MAX_FILE
    assert margin_bytes >= 0.15 * _MAX_FILE, (
        "fn_handler's margin over the current _MAX_FILE has shrunk below "
        "15% -- re-check the headroom, not just whether it technically fits."
    )


def test_max_encoded_b64_bytes_accepts_exactly_max_file_when_encoded():
    """A real _MAX_FILE-sized raw file, base64-encoded, must fit under the
    cap -- the literal scenario this guard exists to allow."""
    import base64

    raw = b"x" * _MAX_FILE
    encoded_len = len(base64.b64encode(raw))
    assert encoded_len <= _MAX_ENCODED_B64_BYTES
