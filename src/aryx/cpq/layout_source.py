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

# Generic words the "Config Layout <CatalogName>.txt" naming convention
# itself contributes to every filename in this directory -- not specific
# to any one catalog. Stripping them lets a real ingested `catalog_prefix`
# (which carries none of this boilerplate) line up with the filename's
# actual catalog-identifying core.
_LAYOUT_FILENAME_BOILERPLATE: tuple[str, ...] = ("config", "layout")


def _normalize(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _strip_boilerplate(text: str) -> str:
    for word in _LAYOUT_FILENAME_BOILERPLATE:
        text = text.replace(word, "")
    return text


def _fuzzy_matches(needle: str, haystack: str) -> bool:
    """True when `needle` (a normalized catalog_prefix) and `haystack` (a
    normalized layout filename stem) share enough of a real match to be
    the same catalog -- checked both directions, and again after
    stripping the filename-naming-convention's own boilerplate words.

    Confirmed live (2026-08-08): a real ingested catalog_prefix is
    whatever `aryx.pipeline.doc_discovery._stem_type` derived from the
    SOURCE XML's own filename (e.g. "ApxnextCnofigdata" from "APXNext_
    CnofigData.xml", typo included) -- a completely different naming
    scheme than the human-authored layout export's own filename ("Config
    Layout APX Next.txt"). Neither is a raw substring of the other, so a
    plain `needle in haystack` (or its reverse) never matches, even
    though both plainly refer to the same catalog -- only stripping the
    filename's own "config"/"layout" boilerplate surfaces the real shared
    core ("apxnext") both sides agree on.
    """
    if needle in haystack or haystack in needle:
        return True
    stripped = _strip_boilerplate(haystack)
    return bool(stripped) and (stripped in needle or needle in stripped)


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

    Confirmed live (2026-08-08): callers pass the real ingested
    `catalog_prefix` (e.g. "APXNEXT_BOM"), which carries a real, recurring
    Oracle CPQ variant-suffix ("_BOM" -- Bill Of Materials) a human-authored
    layout export filename never repeats ("Config Layout APX Next.txt").
    A plain substring check never matches the real ingested catalog_prefix
    ("ApxnextCnofigdata", filename-derived, see `_fuzzy_matches`'s own
    docstring) against a human-authored layout filename ("Config Layout
    APX Next.txt") -- the file existed, `ARYX_CPQ_LAYOUT_DIR` was set
    correctly, and `load_layout_display_order` was already wired into
    every real call site, yet the layout signal silently never applied
    for this exact, real-world catalog_prefix.
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
            and _fuzzy_matches(needle, _normalize(p.stem))
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
