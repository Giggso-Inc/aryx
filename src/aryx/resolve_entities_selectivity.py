"""Match-key selectivity check for the entity-resolution funnel.

Split out of `resolve_entities.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03) — the one function in that module with zero `get_settings()`
dependency and no patch exposure of its own (confirmed via grep). See
`resolve_entities.py`'s docstring for why the rest of the module stays put.
"""
from __future__ import annotations

from aryx.models import ResolutionRecord
from aryx.resolution.blocking import normalize


def _key_selectivity(records: list[ResolutionRecord], sample_size: int) -> float:
    """Distinct-value ratio of match text over a bounded sample.

    A cheap, upfront signal for whether the match key has enough identity
    information to produce a meaningful block at all — the same principle
    already applied to FK-detection candidates (dynamic_fk.py) applied one
    layer over: measure selectivity before committing to expensive work,
    not after discovering it was pointless. Head-sampled (``records[:
    sample_size]``), not a spread sample — fine for THIS purpose, where a
    false negative only means paying for a resolve pass that turns out
    unnecessary, not a correctness bug. Do not reuse this for a
    higher-stakes decision (e.g. whether to merge records by exact
    equality) without re-reading ``_full_uniqueness_ratio``'s docstring
    below first (PR review N1, 2026-10-04).
    """
    sample = records[:sample_size]
    if not sample:
        return 1.0
    distinct = len({r.text.strip().lower() for r in sample if r.text})
    return distinct / len(sample)


def _full_uniqueness_ratio(records: list[ResolutionRecord]) -> float:
    """Exact distinct-value ratio over EVERY record — no sampling.

    PR review N1 (2026-10-04): ``_key_selectivity()`` above samples only
    the first ``sample_size`` records — fine for its original purpose (an
    upfront low-selectivity SKIP decision), but force_exact's verification
    (resolve_entities.py) is a different, higher-stakes question: "is it
    safe to merge records by equality on this key." A biased head-sample
    could miss duplicate values concentrated later in the data (e.g. a
    repeated placeholder like "N/A"), wrongly green-lighting a merge that
    actually collapses distinct records into one entity. A full scan is
    "cheap next to resolve" even at 440K+ short strings (the reviewer's
    own framing), so there is no sampling tradeoff worth making for a
    decision this consequential — only called when force_exact is
    actually requested, not on every resolve_run() call.

    Uses the SAME ``normalize()`` that ``run_exact.py``'s ``_resolve_exact``
    actually groups records by (PR review round 7, Medium) — this function
    used to do its own ``.strip().lower()``, which does not collapse
    internal whitespace the way ``normalize()`` does. Two values differing
    only by internal whitespace (e.g. ``"AB  12"`` vs ``"AB 12"``) would
    count as 2 distinct values here, making a key look uniquely verified
    enough to force_exact, while actually merging into ONE group in
    ``_resolve_exact`` — the exact inverse of what this check exists to
    catch.
    """
    if not records:
        return 1.0
    total = len(records)
    distinct = len({normalize(r.text) for r in records if r.text})
    return distinct / total
