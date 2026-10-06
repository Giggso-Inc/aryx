#!/usr/bin/env python3
"""
Raven — Auto-Signoff (Sprint A4.4) post-commit hook.

Reads the files changed in HEAD, enqueues one signoff per file with
signer = committer for the local-to-Hub sync queue. Idempotent via the
Hub-side UNIQUE (file_id, commit_sha).

Also triggers PR description update via pr-attribute.py.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ATTRIBUTIONS_PATH = Path(".raven/state/attributions.json")
SYNCED_PATH = Path(".raven/state/attributions-synced.json")


def _load_queue():
    spec = importlib.util.spec_from_file_location(
        "_q", Path(__file__).resolve().parent / "contribute-queue.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def head_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return ""


def changed_files() -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "HEAD"],
            stderr=subprocess.DEVNULL,
        )
        return [ln.strip() for ln in out.decode().splitlines() if ln.strip()
                and not ln.startswith("docs/contribute/")]
    except Exception:
        return []


def signer() -> str:
    try:
        return subprocess.check_output(
            ["git", "log", "-1", "--pretty=%ae"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return os.environ.get("GIT_AUTHOR_EMAIL", "unknown")


def commit_message() -> str:
    try:
        return subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B"], stderr=subprocess.DEVNULL
        ).decode(errors="replace").strip()
    except Exception:
        return ""


def commit_committed_at() -> str:
    try:
        return subprocess.check_output(
            ["git", "log", "-1", "--pretty=%cI"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return ""


def enqueue_signoffs(project_id: str) -> int:
    q = _load_queue()
    sha = head_sha()
    if not sha:
        return 0
    files = changed_files()
    if not files:
        return 0
    s = signer()
    for f in files:
        q.enqueue("signoffs", project_id,
                  {"file_path": f, "commit_sha": sha, "signer_email": s})
    return len(files)


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_synced(keys: set[str]) -> None:
    try:
        SYNCED_PATH.parent.mkdir(parents=True, exist_ok=True)
        SYNCED_PATH.write_text(json.dumps(sorted(keys)), encoding="utf-8")
    except Exception:
        pass


def _span_key(file_path: str, span: dict) -> str:
    return f"{file_path}|{span.get('start')}|{span.get('end')}|{span.get('ts', '')}"


def _line_count(path: Path) -> int | None:
    """Mirrors contribute-precommit.py's line_count() — contribute_files.
    total_lines has no other source; the Hub has no way to see the file
    itself. None (not 0) when unreadable, so the Hub knows to leave any
    already-stored value alone rather than treat 'unknown' as 'empty'."""
    try:
        return sum(1 for _ in path.open("rb")) if path.exists() else None
    except Exception:
        return None


def enqueue_attributions(project_id: str) -> int:
    """Push newly-written attribution spans for this commit's files to the
    sync queue — the counterpart to enqueue_signoffs() that never existed:
    contribute-precommit.py computes spans and writes them to
    .raven/state/attributions.json, but only to local disk. raven-async.py
    has always known how to drain and POST an "attributions" kind; nothing
    ever produced one.

    Restricted to files this commit's changed_files() actually touched —
    attributions.json accumulates every file ever attributed, and resending
    a file's whole history on every later, unrelated commit would create
    duplicate contribute_attributions rows server-side (unlike signoffs,
    which are protected by a UNIQUE(file_id, commit_sha)). A local
    attributions-synced.json key set is the dedupe instead: each span is
    enqueued exactly once, the first time it's seen on a commit touching
    that file.

    model_id itself is never sent — there is still no agent-side catalog
    mapping a model name to the Hub's numeric contribute_models.model_id.
    Instead (D-60), the model name is split into model_family/model_name and
    sent as strings; the Hub resolves or creates the contribute_models row
    server-side (_ensure_model, get-or-create — same shape as
    _ensure_commit/_ensure_file) and fills in the real model_id itself. A
    human-only span (no "model" on the span) sends neither field, and
    model_id stays None there, same as always.
    """
    q = _load_queue()
    sha = head_sha()
    if not sha:
        return 0
    files = changed_files()
    if not files:
        return 0
    attr_map = _load_json(ATTRIBUTIONS_PATH, {})
    if not attr_map:
        return 0
    synced = set(_load_json(SYNCED_PATH, []))
    author = signer()
    message = commit_message()
    committed_at = commit_committed_at()
    n = 0
    for f in files:
        spans = attr_map.get(f, [])
        if not spans:
            continue
        total_lines = _line_count(Path(f))
        for span in spans:
            start, end = span.get("start"), span.get("end")
            if not isinstance(start, int) or not isinstance(end, int):
                continue  # malformed span — never send a payload that fails schema
            key = _span_key(f, span)
            if key in synced:
                continue
            payload = {
                "file_path": f,
                "commit_sha": sha,
                "commit_author_email": author,
                "commit_message": message,
                "start_line": start,
                "end_line": end,
                "human_email": span.get("human") or author,
                "skill": span.get("skill", ""),
                "session_id": span.get("session_id", ""),
                "reason": span.get("reason", ""),
                # D-269: forward the gap marker honestly — the Hub must
                # never count a gap as AI (regardless of model/model_family
                # below) or as confirmed human.
                "is_gap": bool(span.get("is_gap")),
            }
            if committed_at:
                payload["commit_committed_at"] = committed_at
            if span.get("card_id"):
                payload["card_id"] = span["card_id"]
            if total_lines is not None:
                payload["total_lines"] = total_lines
            model = span.get("model") or ""
            if model:
                # "claude-opus-5" -> family "claude", name kept full so two
                # different models under the same family are never conflated.
                payload["model_family"] = model.split("-", 1)[0]
                payload["model_name"] = model
            q.enqueue("attributions", project_id, payload)
            synced.add(key)
            n += 1
    if n:
        _save_synced(synced)
    return n


def trigger_pr_update() -> None:
    script = Path(__file__).resolve().parent / "pr-attribute.py"
    if not script.exists():
        return
    try:
        subprocess.Popen(
            [sys.executable, str(script)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


PROJECT_ID_CACHE = Path(".raven/state/project-id.json")


def _git_remote_url() -> str:
    try:
        return subprocess.check_output(
            ["git", "remote", "get-url", "origin"], stderr=subprocess.DEVNULL
        ).decode(errors="replace").strip()
    except Exception:
        return ""


def _git_root_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-list", "--max-parents=0", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
        return out.splitlines()[0] if out else ""
    except Exception:
        return ""


def _resolve_project_id() -> str:
    """Stable per-repo identity, independent of local checkout path.

    The old fallback — hashlib.sha1(str(Path.cwd())) — produced a DIFFERENT
    hash depending on invocation context: confirmed live, this repo has two
    different contribute_projects rows from it. Two causes stack: this
    repo's path contains an emoji that different processes decode
    differently (cp1252 vs utf-8), and Path.cwd() itself can vary by
    trailing slash / drive-letter casing across contexts. A git remote URL
    has neither problem — every clone of the same repo reports the
    identical string regardless of local path or encoding.
    """
    import hashlib
    remote = _git_remote_url()
    if remote:
        return hashlib.sha1(remote.encode()).hexdigest()[:32]
    root_commit = _git_root_commit()
    if root_commit:
        return hashlib.sha1(root_commit.encode()).hexdigest()[:32]
    # Last resort — not a git repo at all, no better anchor available.
    return hashlib.sha1(str(Path.cwd()).encode()).hexdigest()[:32]


def project_id() -> str:
    pid = os.environ.get("RAVEN_PROJECT_ID", "")
    if pid:
        return pid
    cached = _load_json(PROJECT_ID_CACHE, {})
    if cached.get("project_id"):
        return cached["project_id"]
    resolved = _resolve_project_id()
    try:
        PROJECT_ID_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PROJECT_ID_CACHE.write_text(json.dumps({"project_id": resolved}), encoding="utf-8")
    except Exception:
        pass
    return resolved


def main() -> int:
    try:
        pid = project_id()
        n = enqueue_signoffs(pid)
        n += enqueue_attributions(pid)
        if n:
            trigger_pr_update()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
