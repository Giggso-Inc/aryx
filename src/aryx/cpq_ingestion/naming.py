"""Naming for the raw graph's storage scope — kept separate from the curated graph,
and separate per source file within a job.

Mirrors ``aryx.naming.ws_graph`` (FalkorDB graph name per workspace) but for
the raw layer, which must not share storage with the curated graph: the
curated graph's projection wipes and rebuilds its own scope on every run
(``FalkorStore.clear()`` / ``OracleGraphStore.clear()``), which would
otherwise delete the raw nodes it is meant to sit alongside as a provenance
layer.

Per-file scoping (Raven review finding M1): a job can upload several XML
files to the same workspace. Each raw-graph write does its own
``clear()``-then-rebuild, so without a per-file component in the scope, the
second file's write would clear and overwrite the first file's raw graph —
only the last file in a batch would survive. ``source_key`` (the file's
stem) is folded into both backends' scope derivation below to keep every
file's raw graph independently addressable and safe from a sibling file's
write.
"""
from __future__ import annotations

import re
import zlib

_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9_]")

#: Numeric range reserved per workspace for per-file raw-graph slots on the
#: Oracle backend (see raw_workspace_id). Comfortably above any realistic
#: number of XML files in one ingest job, while small enough that many
#: workspaces' derived ranges fit well under a 64-bit workspace_id column.
_ORACLE_FILE_SLOT_SPACE = 1_000_000


def _sanitize_source_key(source_key: str) -> str:
    """Make a filename stem safe to use as part of a FalkorDB graph name.

    Collapses every character outside ``[A-Za-z0-9_]`` to ``_``, so two
    distinct filenames differing only in punctuation in the same position
    (e.g. ``"config-v1"`` and ``"config_v1"``) sanitize to the same string
    and would collide on this backend — the same "one file's raw graph
    silently overwritten by another's" residual risk already accepted for
    the Oracle backend's hash-based slot (see ``raw_workspace_id``), just
    via character-collapsing instead of a hash collision. Not treated as
    blocking for the same reason: real filenames colliding after this
    normalization are uncommon, and a collision loses a raw-graph
    provenance write, not curated data.
    """
    safe = _UNSAFE_KEY_CHARS.sub("_", source_key)
    return safe or "file"


def raw_ws_graph(workspace_id: int, source_key: str) -> str:
    """FalkorDB graph name for one source file's raw graph within a workspace.

    Args:
        workspace_id: The curated workspace this file's upload belongs to.
        source_key: A per-file identifier, unique within the job — in
            practice the uploaded filename's stem. Two files in the same
            job must not share a source_key, the same assumption the
            existing pipeline already makes elsewhere (e.g. CSV `dataset`
            names derived from filename stems).
    """
    return f"aryx_raw_ws_{int(workspace_id)}_{_sanitize_source_key(source_key)}"


def raw_workspace_id(workspace_id: int, offset: int, source_key: str) -> int:
    """Oracle Graph workspace_id for one source file's raw graph within a workspace.

    ``aryx_graph_vertex``/``aryx_graph_edge`` scope rows by a single numeric
    ``workspace_id`` column (no foreign key to ``aryx_workspace``, no
    raw/curated/per-file discriminator column), so both the curated/raw
    split and the per-file split are folded into one derived integer:
    ``offset + workspace_id * _ORACLE_FILE_SLOT_SPACE + (stable hash of
    source_key mod _ORACLE_FILE_SLOT_SPACE)``.

    The multiplication by the (fixed) file-slot space guarantees two
    *different* workspace_ids' derived ranges never overlap. Within one
    workspace, two files could in principle collide if their hashes land in
    the same slot — with ``_ORACLE_FILE_SLOT_SPACE`` = 1,000,000 that
    probability is negligible for any realistic single-job file count, and
    a collision would only make one file's raw graph get overwritten by
    another's (same failure mode as before this fix, just far less likely),
    never data corruption — an acceptable tradeoff for a rebuildable,
    best-effort provenance layer.
    """
    slot = zlib.crc32(source_key.encode("utf-8")) % _ORACLE_FILE_SLOT_SPACE
    return int(offset) + int(workspace_id) * _ORACLE_FILE_SLOT_SPACE + slot
