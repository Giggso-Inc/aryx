"""Layout-file resolution: local directory today, cloud-ready by design.

Mirrors the same shape `src/aryx/broker/secrets.py` already uses for
secrets: a `Protocol`, a no-dependency local default, and room for a
lazy-import cloud backend later without touching any caller.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

_LAYOUT_FILE_SUFFIX = ".txt"


def _normalize(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


class LayoutFileSource(Protocol):
    """Resolves a catalog's native-UI layout export to its raw file text."""

    def get(self, catalog_name: str) -> str | None:
        """Return the layout file's raw text for catalog_name, or None."""
        ...


class LocalDirLayoutFileSource:
    """Reads layout files from a local directory (the no-dependency default).

    Matches `catalog_name` (e.g. "Apx Next", "SVX") against candidate
    filenames as a normalized (lowercased, alnum-only) substring — per the
    stated convention that a catalog's layout export file name contains
    the catalog's own name (e.g. "Config Layout APX Next.txt" for "Apx
    Next"). Only `.txt` files are considered, so this never collides with
    the raw `.xml` catalog exports that sometimes live alongside these
    files. Directory comes from `ARYX_CPQ_LAYOUT_DIR` if set, else the
    directory passed to `__init__`, else the current working directory —
    today's actual file location, with the path already externalized so
    relocating it later is a config change, not a code change.
    """

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(
            os.environ.get("ARYX_CPQ_LAYOUT_DIR") or directory or "."
        )

    def get(self, catalog_name: str) -> str | None:
        if not catalog_name or not self.directory.is_dir():
            return None
        needle = _normalize(catalog_name)
        if not needle:
            return None
        matches = sorted(
            p for p in self.directory.iterdir()
            if p.is_file()
            and p.suffix.lower() == _LAYOUT_FILE_SUFFIX
            and needle in _normalize(p.stem)
        )
        if not matches:
            return None
        if len(matches) > 1:
            logger.info(
                "cpq layout_source: %d candidate layout files matched %r, "
                "using %s", len(matches), catalog_name, matches[0].name,
            )
        try:
            return matches[0].read_text(encoding="utf-8")
        except OSError:
            logger.warning(
                "cpq layout_source: failed to read %s", matches[0], exc_info=True,
            )
            return None
