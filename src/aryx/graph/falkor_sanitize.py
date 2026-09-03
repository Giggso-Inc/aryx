"""Cypher-safe identifier/property sanitization shared by FalkorStore's writers.

Split out of `graph/falkor_store.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). No test patches `get_settings` (or anything else) on the
falkor_store module, so these pure functions move freely — `test_protege_
parity.py` and `test_doc_discovery.py` import them directly, and continue to
work via `falkor_store.py`'s re-export.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from aryx.config import get_settings
from aryx.display_name import display_name as _dn

logger = logging.getLogger(__name__)

_LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_LABELS = 6  # cap to avoid label-bloat on deep hierarchies

# Any character outside this set (hyphen, colon, space, non-ASCII, ...) is not
# a legal Cypher identifier character.
_UNSAFE_IDENT_CHAR_RE = re.compile(r"[^A-Za-z0-9_]")


def _sanitize_ident(raw: str) -> str:
    """Coerce an arbitrary string into a safe Cypher identifier without losing it.

    XML/CSV source names can legally contain characters Cypher identifiers
    cannot (hyphens, colons from a namespaced attribute, spaces, non-ASCII
    text). Rather than dropping such a property key or label outright — the
    previous behavior, which silently lost that attribute/label whenever a
    source file's naming didn't happen to already be identifier-safe — every
    disallowed character is replaced with '_' and a leading digit is prefixed
    with '_' (identifiers cannot start with a digit). The data survives under
    a stable, if mangled, name instead of vanishing.
    """
    safe = _UNSAFE_IDENT_CHAR_RE.sub("_", raw)
    if not safe or safe[0].isdigit():
        safe = f"_{safe}"
    return safe

# Property names reserved by the projection itself — attribute keys with these
# names must never overwrite the canonical lifted fields.
_RESERVED_PROPS = frozenset({"id", "type", "name", "iri"})

# Key-like attribute names are exempt from value truncation: a truncated
# identifier silently breaks exact-match joins (the graph would store a value
# that equals nothing in the source data). Matches id/guid/uuid/key/code/ref
# suffixes and variable_name-style CPQ keys.
_KEY_PROP_RE = re.compile(
    r"(^|_)(id|guid|uuid|key|code|ref|num|no)$|^variable_name$|_name$", re.IGNORECASE
)

# Sanity bound for exempt key values — a "key" longer than this is almost
# certainly not a key; warn and truncate anyway to protect the graph.
_KEY_SANITY_MAX = 4096

# Properties worth indexing for exact-match lookups. Deliberately narrower
# than the truncation exemption: *_name display fields are searched with
# CONTAINS (no index benefit in FalkorDB), while these are joined on equality.
_INDEX_PROP_RE = re.compile(
    r"(^|_)(id|guid|uuid|key|code)$|^variable_name$", re.IGNORECASE
)


def _lift_props(attributes: dict[str, Any]) -> dict[str, Any]:
    """Build the native-property map for a node from entity attributes.

    Scalars pass through natively so they are individually queryable and
    indexable in Cypher; nested dicts/lists are JSON-stringified per key (or
    skipped, per ARYX_GRAPH_LIFT_NESTED); long strings are truncated to
    ARYX_GRAPH_ATTR_VALUE_CAP except key-like fields, which must stay intact
    for exact-match joins. The RDB keeps the full-fidelity copy.
    """
    settings = get_settings()
    if settings.graph_lift_mode == "off":
        return {}
    cap = settings.graph_attr_value_cap
    out: dict[str, Any] = {}
    for key, val in attributes.items():
        if val is None:
            continue
        if key in _RESERVED_PROPS:
            # Source data legitimately carries its own id/name/type (e.g. the
            # BigMachines-native `id` that rules join on). Those must stay
            # queryable — store them under a src_ prefix instead of letting
            # the projection's canonical fields shadow them.
            key = f"src_{key}"
        if not _LABEL_RE.match(key):
            sanitized = _sanitize_ident(key)
            logger.warning(
                "sanitizing attr %r -> %r: not a safe property name", key, sanitized)
            key = sanitized
        if key in out:
            # Either two distinct source keys sanitized to the same identifier
            # (e.g. "attr-1" and "attr_1"), or a sanitized key collided with an
            # already-safe original key — suffix so one write never silently
            # overwrites the other.
            suffix = 2
            while f"{key}_{suffix}" in out:
                suffix += 1
            key = f"{key}_{suffix}"
        if isinstance(val, bool) or isinstance(val, (int, float)):
            out[key] = val
            continue
        if isinstance(val, (dict, list)):
            if not settings.graph_lift_nested:
                continue
            val = json.dumps(val, default=str)
        elif not isinstance(val, str):
            val = str(val)
        if _KEY_PROP_RE.search(key):
            if len(val) > _KEY_SANITY_MAX:
                logger.warning(
                    "key-like attr %r exceeds sanity bound (%d > %d chars), "
                    "truncating — exact-match joins on it will not work",
                    key, len(val), _KEY_SANITY_MAX)
                val = val[:_KEY_SANITY_MAX]
        elif len(val) > cap:
            val = val[:cap] + "…"
        out[key] = val
    return out


def _safe_labels(labels: list[str] | None) -> list[str]:
    """Filter labels to safe Cypher identifiers and cap depth.

    FalkorDB does not support parameter-bound labels, so the label list is
    spliced into the query string — every entry must be a strict identifier.
    An entry that isn't one is sanitized (disallowed characters replaced with
    '_') rather than dropped, so a source type name with e.g. a hyphen or
    non-ASCII character still gets attached as a label instead of vanishing.
    Sanitization can never reintroduce Cypher-unsafe characters, so this
    remains injection-safe.

    Two distinct raw labels can sanitize to the same identifier (e.g.
    "Product-Type" and "Product:Type" both -> "Product_Type"). That collision
    is suffixed (mirroring _lift_props) rather than silently dropped, so one
    doesn't overwrite the other. An exact repeat of the same raw label is
    still deduped as-is — that's an intentional, lossless dedup.
    """
    out: list[str] = []
    seen_raw: set[str] = set()
    for raw in labels or []:
        if not raw or raw in seen_raw:
            continue
        seen_raw.add(raw)
        label = raw if _LABEL_RE.match(raw) else _sanitize_ident(raw)
        if label != raw:
            logger.warning(
                "sanitizing label %r -> %r (not a Cypher identifier)", raw, label)
        if label in out:
            suffix = 2
            while f"{label}_{suffix}" in out:
                suffix += 1
            logger.warning(
                "label %r sanitized to %r, which collides with an existing "
                "label — suffixing to %r", raw, label, f"{label}_{suffix}")
            label = f"{label}_{suffix}"
        out.append(label)
        if len(out) >= _MAX_LABELS:
            break
    return out


def _display_name(attributes: dict[str, Any]) -> str:
    return _dn(attributes)
