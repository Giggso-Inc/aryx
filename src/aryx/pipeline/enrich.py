"""Post-resolution enrichment helpers: type ancestors + relate stage."""
from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import islice

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.models import Relationship
from aryx.relationships import infer_relationship
from aryx.store.entity_store import EntityStore
from aryx.store.ontology_store import OntologyStore

logger = logging.getLogger(__name__)


def _build_type_ancestors(dsn: str, workspace_id: int = 1) -> dict[str, list[str]]:
    """Resolve ancestor chains for every declared type via OntologyStore."""
    ostore = OntologyStore(dsn, workspace_id)
    try:
        types = ostore.list_types()
        out: dict[str, list[str]] = {}
        for t in types:
            if t.parent_type:
                out[t.name] = ostore.ancestors(t.name)
        return out
    except Exception as exc:  # noqa: BLE001 — hierarchy is additive, never block projection
        logger.warning("type ancestors lookup failed; projecting without labels: %s", exc)
        return {}
    finally:
        ostore.close()


def _relate(store: EntityStore, broker: Broker, max_pairs: int) -> int:
    """Infer relationships over candidate entity pairs (frontier tier).

    Cross-type pairs are evaluated first so the max_pairs budget is spent on
    the most informative edges; same-type pairs fill any remaining budget.
    """
    cfg = get_settings()
    relate_workers = cfg.relate_workers
    max_attrs = cfg.relate_max_attrs

    # Only load enough entities to fill max_pairs — fetching all workspace
    # entities is O(n_total) but we only need O(sqrt(max_pairs)) entities.
    # 10× headroom handles multi-type spread without pulling tens of thousands.
    entities = list(islice(store.list_entities(), max_pairs * 10))

    by_type: dict[str, list] = defaultdict(list)
    for e in entities:
        by_type[e[1]].append(e)

    types = list(by_type.keys())
    candidates: list[tuple] = []

    # Cross-type pairs first — round-robin across ALL type combinations so no
    # single pair dominates the budget when there are 3+ entity types.
    # With k types there are k*(k-1)/2 combinations; each gets max_pairs//k*(k-1)/2
    # candidates before moving to the next, then we cycle until budget is full.
    _sentinel = object()
    cross_iters = [
        ((ea, eb) for ea in by_type[types[i]] for eb in by_type[types[j]])
        for i in range(len(types))
        for j in range(i + 1, len(types))
    ]
    active = list(cross_iters)
    while active and len(candidates) < max_pairs:
        still_active = []
        for it in active:
            pair = next(it, _sentinel)
            if pair is not _sentinel:
                candidates.append(pair)
                still_active.append(it)
                if len(candidates) >= max_pairs:
                    break
        active = still_active if len(candidates) < max_pairs else []

    # Fill remaining budget with same-type pairs.
    if len(candidates) < max_pairs:
        for t_entities in by_type.values():
            for i in range(len(t_entities)):
                for j in range(i + 1, len(t_entities)):
                    candidates.append((t_entities[i], t_entities[j]))
                    if len(candidates) >= max_pairs:
                        break
                if len(candidates) >= max_pairs:
                    break
            if len(candidates) >= max_pairs:
                break

    def _trim(attrs: dict) -> dict:
        """Keep _element_type + first max_attrs keys to limit LLM prompt size."""
        out: dict = {}
        if "_element_type" in attrs:
            out["_element_type"] = attrs["_element_type"]
        for k, v in attrs.items():
            if k == "_element_type":
                continue
            out[k] = v
            if len(out) >= max_attrs:
                break
        return out

    def _infer(left: tuple, right: tuple) -> tuple[int, int, str | None, float]:
        name, conf = infer_relationship(_trim(left[2]), _trim(right[2]), broker)
        return left[0], right[0], name, conf

    rels: list[Relationship] = []
    with ThreadPoolExecutor(max_workers=relate_workers) as pool:
        futures = {
            pool.submit(_infer, left, right): (left[0], right[0])
            for left, right in candidates[:max_pairs]
        }
        for fut in as_completed(futures):
            src_id, tgt_id, name, conf = fut.result()
            if name:
                rels.append(Relationship(
                    source_entity_id=src_id, target_entity_id=tgt_id,
                    name=name, confidence=conf))
    store.save_relationships(rels)
    logger.info("_relate evaluated %d pairs, found %d relationships", len(candidates), len(rels))
    return len(rels)
