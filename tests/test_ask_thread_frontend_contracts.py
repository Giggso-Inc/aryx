"""Frontend contract checks for Shay-backed Ask threads."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


PAGE_PATH = Path(__file__).resolve().parents[1] / "apps" / "web" / "app" / "page.tsx"
HISTORY_DRAWER_PATH = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "web"
    / "components"
    / "ask"
    / "AskHistoryDrawer.tsx"
)
SEARCH_INPUT_PATH = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "web"
    / "components"
    / "ask"
    / "AskSearchInput.tsx"
)
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


def test_ask_page_search_filters_loaded_message_content() -> None:
    page_source = PAGE_PATH.read_text(encoding="utf-8")

    assert 'ariaLabel="Search this conversation"' in page_source
    assert "WorkspacePeek" not in page_source
    assert 'aria-label="Ask controls"' in page_source
    assert 'rounded-2xl border border-navy-100 bg-white p-3 shadow-soft' in page_source
    assert 'h-10 min-w-0 flex-1 max-w-96 rounded-xl' in page_source
    assert "h-[52px]" not in page_source
    assert "turn.content.toLocaleLowerCase().includes(normalizedMessageSearch)" in page_source
    assert "No messages match" in page_source


def test_ask_history_search_filters_thread_titles() -> None:
    drawer_source = HISTORY_DRAWER_PATH.read_text(encoding="utf-8")
    input_source = SEARCH_INPUT_PATH.read_text(encoding="utf-8")

    assert 'ariaLabel="Search ask history"' in drawer_source
    assert "thread.title.toLocaleLowerCase().includes(normalizedQuery)" in drawer_source
    assert "No threads match" in drawer_source
    assert "aria-live=\"polite\"" in input_source
