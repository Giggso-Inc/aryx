"""Per-turn CPQ model resolution: the model a quote is actually for.

Native Oracle CPQ configures at a model catalog node and injects that model
as the ``_bm_model_*`` punch-in context the catalog's rule scripts guard on.
Aryx anchors at the family node, so for a multi-model catalog that context
is never established. This module resolves the model once per turn from real
ingested data (``Basemodeltoconfig``, the ``BmCatalog`` tree,
``Flagsforflashport``; see ``model_resolution_catalog``) with no
product-specific code. When the wording matches several models the top one
is picked deterministically (``rank_candidates``); the customer is never
asked.

The resolution is bound to the current turn via a contextvar by the ask flow
(only when ``cpq_model_resolution_enabled`` is on). Absent a bound turn
(flag off, unit tests, threads that don't copy context) every accessor is a
silent no-op. Ported from aryxent ``cpq/model_resolution.py`` (PR 1).
"""
from __future__ import annotations

import contextvars
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from aryx.cpq.logging_context import install_run_id_logging
from aryx.cpq.model_resolution_catalog import (
    ancestors as _ancestors,
    cached as _cached_catalog,
    catalog_node_count,
    load_catalog,
)
from aryx.cpq.model_resolution_tie import compute_prefix_tie

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)

__all__ = [
    "ModelCandidate", "ModelResolution", "TurnModelContext", "bind_turn",
    "catalog_node_count", "describe", "get_turn", "rank_candidates", "resolve_model",
    "resolve_model_turn_first",
]

# Catalog's own soft-delete / test markers on CPQModel codes ("-remove",
# "-DEL", "_future", "_PO-81514", "-btaDelete-<ts>", "_invalid", "_hide_...").
_SOFT_DELETED_RE = re.compile(r"(-remove|-del|_future|_po-\d|-bta|_invalid|_hide_)", re.I)
_CORE_RE = re.compile(r"^[a-z]+\d+")
_MIN_NAME_LEN = 4


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _occurs(needle: str, hay: str) -> bool:
    """`needle` appears in `hay` and is not immediately followed by a digit —
    so "apx900" never matches inside "apx9000"."""
    start = 0
    while True:
        i = hay.find(needle, start)
        if i < 0:
            return False
        j = i + len(needle)
        if j >= len(hay) or not hay[j].isdigit():
            return True
        start = i + 1


def _match_kind(names: set[str], hint_norm: str) -> tuple[str, int] | None:
    """('exact', n) when a full candidate name appears in the wording,
    ('partial', n) when only its leading letters+digits code does (e.g.
    "apx8000" for "apx8000xe"), else None. `n` is the length of the
    longest matched text — how specifically the wording names this model."""
    normed = {_norm(n) for n in names}
    exact = [len(n) for n in normed if len(n) >= _MIN_NAME_LEN and _occurs(n, hint_norm)]
    if exact:
        return "exact", max(exact)
    partial = []
    for n in normed:
        m = _CORE_RE.match(n)
        if m and len(m.group(0)) >= _MIN_NAME_LEN and _occurs(m.group(0), hint_norm):
            partial.append(len(m.group(0)))
    return ("partial", max(partial)) if partial else None


@dataclass(frozen=True)
class ModelCandidate:
    cpq_model: str
    display_names: frozenset[str]
    node_name: str | None
    node_id: str | None
    base_models: frozenset[str]
    match: str  # "exact" | "partial"
    is_upgrade: bool
    soft_deleted: bool
    match_len: int = 0  # length of the matched name text (specificity)


@dataclass(frozen=True)
class ModelResolution:
    chosen: ModelCandidate | None
    alternatives: tuple[ModelCandidate, ...]
    deciding_step: str
    source: str  # "hint" | "unresolved"
    scope_node_ids: frozenset[str]
    # Sellable models on other nodes whose name extends the chosen model's
    # matched text (see model_resolution_tie); () unless the flag is on.
    prefix_tie: tuple[ModelCandidate, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.chosen is not None


def rank_candidates(
    cands: list[ModelCandidate],
) -> tuple[ModelCandidate | None, tuple[ModelCandidate, ...], str]:
    """Deterministic top-model pick — never asks. Steps, in order: drop
    soft-deleted/test variants → prefer a new radio over an upgrade →
    prefer the most specific (longest) name the wording matched → prefer
    an exact name match → most real base models → alphabetical. A step
    never narrows to an empty set. Returns (chosen, alternatives, name of
    the last step that narrowed the pool).

    Longest-match comes before exact-vs-partial because a shorter model
    name is often contained in a longer one: "APX 1500 Enhanced" contains
    "APX 1500", and "Enhanced APX 6500" is named more specifically by
    ENHANCEDAPX6500/LI (partial, 15 chars) than by APX6500/LI (exact,
    7 chars)."""
    if not cands:
        return None, (), "no_match"
    pool = list(cands)
    step = "single_match"

    def narrow(keep, name: str) -> None:
        nonlocal pool, step
        kept = [c for c in pool if keep(c)]
        if kept and len(kept) < len(pool):
            pool, step = kept, name

    if len(pool) > 1:
        narrow(lambda c: not c.soft_deleted, "drop_soft_deleted")
    if len(pool) > 1:
        narrow(lambda c: not c.is_upgrade, "prefer_new_radio")
    if len(pool) > 1:
        longest = max(c.match_len for c in pool)
        narrow(lambda c: c.match_len == longest, "longest_name_match")
    if len(pool) > 1:
        narrow(lambda c: c.match == "exact", "prefer_exact_name")
    if len(pool) > 1:
        top = max(len(c.base_models) for c in pool)
        narrow(lambda c: len(c.base_models) == top, "most_base_models")
    if len(pool) > 1:
        pool = sorted(pool, key=lambda c: c.cpq_model)
        step = "alphabetical"
    chosen = pool[0]
    return chosen, tuple(c for c in cands if c is not chosen), step


def resolve_model(
    hint_text: str, workspace_id: int, catalog_prefix: str, rdb: Any | None = None,
) -> ModelResolution:
    """Resolve the model the customer's wording refers to. Never raises for
    data problems — an unresolvable wording returns source='unresolved'."""
    data = load_catalog(workspace_id, catalog_prefix, rdb)
    hint_norm = _norm(hint_text)
    def build(cpq: str, m: dict, kind: str = "partial", match_len: int = 0) -> ModelCandidate:
        node_id = m["node_id"]
        return ModelCandidate(
            cpq_model=cpq,
            display_names=frozenset(m["display"]),
            node_name=data.nodes_by_id[node_id][0] if node_id else None,
            node_id=node_id,
            base_models=frozenset(m["base_models"]),
            match=kind,
            is_upgrade=cpq in data.upgrade_models or (node_id in data.upgrade_node_ids),
            soft_deleted=bool(_SOFT_DELETED_RE.search(cpq)),
            match_len=match_len,
        )

    cands: list[ModelCandidate] = []
    for cpq, m in data.models.items():
        matched = _match_kind(m["display"] | {cpq}, hint_norm)
        if matched is None:
            continue
        cands.append(build(cpq, m, matched[0], matched[1]))
    chosen, alternatives, step = rank_candidates(sorted(cands, key=lambda c: c.cpq_model))
    scope = frozenset(_ancestors(chosen.node_id, data.nodes_by_id)) if chosen else frozenset()
    return ModelResolution(
        chosen=chosen, alternatives=alternatives, deciding_step=step,
        source="hint" if chosen else "unresolved", scope_node_ids=scope,
        prefix_tie=compute_prefix_tie(chosen, hint_norm, data, build),
    )


def resolve_model_turn_first(
    turn_text: str, anchor_text: str, workspace_id: int, catalog_prefix: str,
    rdb: Any | None = None,
) -> ModelResolution:
    """Resolve from the CURRENT turn's wording first; only when that names no
    model fall back to ``anchor_text + turn_text``. Rule: what the customer
    says now beats what they said earlier, so "make it APX 8000" after an
    "APX 6000" anchor resolves to 8000 instead of an anchor-driven tie. The
    in-pool tie-break stays ``rank_candidates`` (alphabetical last)."""
    res = resolve_model(turn_text, workspace_id, catalog_prefix, rdb)
    if res.resolved or not (anchor_text or "").strip():
        return res
    return resolve_model(f"{anchor_text} {turn_text}", workspace_id, catalog_prefix, rdb)


# ---- Turn binding ----

@dataclass
class TurnModelContext:
    resolution: ModelResolution
    workspace_id: int
    catalog_prefix: str
    _logged: set[tuple] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    # per-turn results of pure, input-keyed lookups (see data_table_bridge.candidates); dies with the turn
    memo: dict[tuple, object] = field(default_factory=dict)

    def first_time(self, key: tuple) -> bool:
        """True the first time `key` is seen this turn — dedupes diagnostics
        emitted from hot paths (e.g. _cpq_model_candidates runs ~300x/turn)."""
        with self._lock:
            if key in self._logged:
                return False
            self._logged.add(key)
            return True

    def rule_scope(self, rule_name: str) -> str:
        """'in_scope' | 'out_of_scope' | 'ambiguous' | 'unknown' for a fired
        rule, by name. Rule objects carry only their name (not their native
        id), and names aren't unique — a name owning nodes both inside and
        outside the model's scope is 'ambiguous'. A ref_id that isn't a
        catalog node is family-level and counts as in scope."""
        if not self.resolution.resolved:
            return "unknown"
        data = _cached_catalog(self.workspace_id, self.catalog_prefix)
        if data is None:
            return "unknown"
        owners = data.rule_nodes_by_name.get((rule_name or "").strip().lower())
        if not owners:
            return "unknown"
        scope = self.resolution.scope_node_ids
        inside = {o for o in owners if o in scope or o not in data.nodes_by_id}
        if inside == owners:
            return "in_scope"
        return "ambiguous" if inside else "out_of_scope"


_turn_var: contextvars.ContextVar[TurnModelContext | None] = contextvars.ContextVar(
    "cpq_turn_model_context", default=None,
)


def bind_turn(ctx: TurnModelContext | None) -> None:
    """Bind (or clear, with None) this turn's model context."""
    _turn_var.set(ctx)


def get_turn() -> TurnModelContext | None:
    """The bound turn context, or None when unbound."""
    return _turn_var.get()


def describe(res: ModelResolution) -> str:
    """One-line, log-friendly summary of a resolution."""
    if not res.resolved:
        return "unresolved"
    c = res.chosen
    alts = ", ".join(f"{a.cpq_model}({a.match}:{a.match_len}{',upgrade' if a.is_upgrade else ''}"
                     f"{',deleted' if a.soft_deleted else ''})" for a in res.alternatives)
    return (
        f"chosen={c.cpq_model!r} node={c.node_name!r}({c.node_id}) "
        f"match={c.match}:{c.match_len} "
        f"base_models={len(c.base_models)} deciding_step={res.deciding_step} "
        f"scope_nodes={sorted(res.scope_node_ids)} alternatives=[{alts}]"
    )
