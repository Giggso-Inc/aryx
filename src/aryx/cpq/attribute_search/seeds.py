"""Fill an attribute-search match into a CPQ session ("seeds").

A seed is {vn, item_value, display, select_type, kind} for one matched
attribute; kind is "option" (a menu option matched the stated value) or
"boolean" (a yes/no feature).
Values are written the way the engine's own hint matching writes them
(auto_fill_stages/commit_value.py): multi-select into ``filled_multi``,
everything else into ``filled``, with source "hint" -- so the engine's
constraint check (tier0_already_filled) still re-validates the value and
drops it if that product's rules don't allow it.
"""
from __future__ import annotations

from typing import Any


def seed_values(session: Any, seeds: list[dict[str, str]]) -> None:
    """Write each seed into `session` as a hint-sourced value."""
    for seed in seeds:
        vn, code = seed.get("vn") or "", seed.get("item_value") or ""
        if not vn or not code:
            continue
        if seed.get("select_type") == "multi":
            current = session.filled_multi.setdefault(vn, [])
            if code not in current:
                current.append(code)
        else:
            session.filled[vn] = code
        session.display_filled[vn] = seed.get("display") or code
        session.filled_source[vn] = "hint"


def apply_pending_seeds(session: Any, family: str) -> int:
    """Apply the seeds remembered for `family` (case-insensitive), then clear all.

    Returns how many seeds were applied (0 when the family wasn't offered).
    """
    pending = session.attribute_search_seeds or {}
    want = (family or "").casefold()
    seeds = next((v for k, v in pending.items() if k.casefold() == want), [])
    seed_values(session, seeds)
    session.attribute_search_seeds = {}
    return len(seeds)


def trim_ambiguous_seeds(seeds: list[dict[str, str]]) -> list[dict[str, str]]:
    """Drop yes/no feature seeds when more than one feature attribute matched.

    A stated value that matched a real menu option is evidence, so every
    attribute offering it is kept (carrier "ATT" fills both carrier
    attributes). A feature found only by its label is not: "includes a spare"
    matched "Include a Spare?" and two 'Is this a "SPARE radio"' attributes
    on workspace 704, and filling all three would claim more than the customer
    said. Then no feature is filled in and the quote asks as usual.
    """
    features = {s["vn"] for s in seeds if s.get("kind") == "boolean"}
    if len(features) <= 1:
        return list(seeds)
    return [s for s in seeds if s.get("kind") != "boolean"]
