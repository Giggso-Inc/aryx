"""Prefix-tie detection for the per-turn model resolver (item F16).

A *prefix tie* exists when the wording names model A in full and another
sellable model B on a DIFFERENT catalog node has a normalized name that starts
with A's matched text and is longer ("ALPHA100" vs "ALPHA100PLUS"). The
resolver still picks A deterministically; this module only reports the tie so
the ask flow can ask which one was meant. Purely data driven: nothing here
knows any product, model, node or attribute name. Gated by the setting
``cpq_model_prefix_tie_ask_enabled`` (default off: always returns ``()``).
"""
from __future__ import annotations

from typing import Any

from aryx.config import get_settings


def _tie_cpq_models(
    chosen: Any, hint_norm: str, data: Any,
) -> list[str]:
    """cpq-model codes of every sellable model that ties `chosen` by prefix."""
    from aryx.cpq.model_resolution import _norm, _occurs

    if chosen.match != "exact" or chosen.is_upgrade or chosen.soft_deleted or not chosen.node_id:
        return []
    a_names = {_norm(n) for n in (*chosen.display_names, chosen.cpq_model)}
    matched = {n for n in a_names if len(n) == chosen.match_len and _occurs(n, hint_norm)}
    out: list[str] = []
    for cpq, m in sorted(data.models.items()):
        node_id = m["node_id"]
        if cpq == chosen.cpq_model or not node_id or node_id == chosen.node_id:
            continue
        if node_id in data.upgrade_node_ids or cpq in data.upgrade_models:
            continue
        names = {_norm(n) for n in (*m["display"], cpq)}
        if any(_occurs(n, hint_norm) for n in names if len(n) > chosen.match_len):
            continue  # the wording already names the longer model
        for t in matched:
            if any(
                len(n) > len(t) and n.startswith(t) and not n[len(t)].isdigit()
                for n in names
            ):
                out.append(cpq)
                break
    return out


def compute_prefix_tie(
    chosen: Any, hint_norm: str, data: Any, make_candidate: Any,
) -> tuple[Any, ...]:
    """Tied ModelCandidates (built by `make_candidate(cpq, model_facts)`), or
    ``()`` when the flag is off, nothing is chosen, or there is no tie."""
    if chosen is None or not get_settings().cpq_model_prefix_tie_ask_enabled:
        return ()
    from aryx.cpq.model_resolution import _SOFT_DELETED_RE

    tied = []
    for cpq in _tie_cpq_models(chosen, hint_norm, data):
        if _SOFT_DELETED_RE.search(cpq):
            continue
        tied.append(make_candidate(cpq, data.models[cpq]))
    return tuple(tied)
