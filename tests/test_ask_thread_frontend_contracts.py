"""Frontend contract checks for Shay-backed Ask threads."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


PAGE_PATH = Path(__file__).resolve().parents[1] / "apps" / "web" / "app" / "page.tsx"
UUID_V4_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def test_ask_uid_fallback_returns_uuid_v4() -> None:
    page_source = PAGE_PATH.read_text(encoding="utf-8")
    uid_source = page_source[
        page_source.index("function uid()"):
        page_source.index("function askThreadHref")
    ]
    script = (
        "const vm = require('node:vm');"
        f"const value = vm.runInNewContext({json.dumps(uid_source + '; uid()')}, "
        "{ Uint8Array, Math });"
        "process.stdout.write(value);"
    )

    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert UUID_V4_PATTERN.fullmatch(result)
