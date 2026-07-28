"""Summary validator — field-by-field check against session state.

Diffs generated summary text against session.display_filled. On mismatch:
regenerate once; if still wrong, return the raw state table (never a
hallucinated summary).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from aryx.cpq.state import ConfigAttr, CpqSession

logger = logging.getLogger(__name__)


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def fields_missing_from_summary(
    summary: str,
    display_filled: dict[str, str],
    attrs: list[ConfigAttr] | None = None,
) -> list[str]:
    """Return display labels/values from session state not found in summary."""
    text = _normalize(summary)
    if not text:
        return list(display_filled.keys()) or ["(empty summary)"]

    by_vn = {a.variable_name: a for a in (attrs or [])}
    missing: list[str] = []
    for vn, value in display_filled.items():
        if not value or value.lower() in ("(none)", "n/a", "na"):
            continue
        val_n = _normalize(value)
        label = by_vn[vn].display_label if vn in by_vn else vn
        label_n = _normalize(label)
        # Value must appear; label is preferred but not required for multi-line
        # associated-options prose.
        if val_n and val_n not in text:
            # Allow partial: first 4 significant chars of multi-word values
            tokens = [t for t in val_n.split() if len(t) > 2]
            if tokens and all(t in text for t in tokens[:2]):
                continue
            missing.append(f"{label}={value}")
        elif label_n and label_n not in text and val_n not in text:
            missing.append(f"{label} (label absent)")
    return missing


def raw_state_table(
    session: CpqSession,
    attrs: list[ConfigAttr] | None = None,
) -> str:
    """Deterministic fallback summary — never LLM-generated."""
    by_vn = {a.variable_name: a for a in (attrs or [])}
    lines = ["**Configuration (verified state table):**", ""]
    if not session.display_filled and not session.filled_multi:
        lines.append("_No fields filled yet._")
        return "\n".join(lines)
    for vn, disp in sorted(session.display_filled.items()):
        label = by_vn[vn].display_label if vn in by_vn else vn
        src = session.filled_source.get(vn, "")
        src_bit = f" _{src}_" if src else ""
        lines.append(f"- **{label}**: {disp}{src_bit}")
    for vn, vals in sorted(session.filled_multi.items()):
        if vn in session.display_filled:
            continue
        label = by_vn[vn].display_label if vn in by_vn else vn
        lines.append(f"- **{label}**: {', '.join(vals)}")
    return "\n".join(lines)


def validate_or_fallback(
    summary: str,
    session: CpqSession,
    attrs: list[ConfigAttr],
    regenerate: Callable[[], str] | None = None,
) -> tuple[str, bool]:
    """Validate summary against session; regenerate once; else raw table.

    Returns (text, used_raw_table).
    """
    missing = fields_missing_from_summary(summary, session.display_filled, attrs)
    if not missing:
        return summary, False

    logger.info(
        "summary_guard: mismatch run_id=%s missing=%s — regenerating once",
        session.run_id or "-", missing[:5],
    )
    if regenerate is not None:
        try:
            second = regenerate()
            missing2 = fields_missing_from_summary(
                second, session.display_filled, attrs,
            )
            if not missing2:
                return second, False
            logger.warning(
                "summary_guard: regenerate still mismatched run_id=%s missing=%s",
                session.run_id or "-", missing2[:5],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("summary_guard: regenerate failed: %r", exc)

    table = raw_state_table(session, attrs)
    return table, True
