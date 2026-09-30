"""Match-key inference for raw graph nodes, grouped by tag.

Resolve needs an ``ontology_type`` and ``match_keys`` per record set (see
``resolve_entities.py``/``resolution/run.py``). For CSV sources both are
inferred from column-name heuristics + an LLM fallback in
``doc_discovery_types.py``'s ``_infer_type``. A raw graph node already
carries the ontology_type half of that for free -- ``RawNode.tag`` is the
XML element name, and ``_xml_to_csvs`` already treats a tag the same way
(one distinct XML tag == one entity type), so there is no filename-style
"is this too generic" fallback needed here: the tag *is* the type.

match_keys is the one real gap (see cpq_ingestion/README.md's scope-boundary
section and the resolve/relate bridge scoping notes). This module fills it,
cheapest-first:

1. Heuristic: reuse the exact same domain-agnostic id-like-name /
   key-suffix config (`ARYX_ID_LIKE_COLUMN_NAMES` / `ARYX_FK_KEY_SUFFIXES`)
   `doc_discovery_types.py` already uses for CSV headers, applied to a
   sample node's property keys instead. Zero LLM cost -- covers the common
   case directly (e.g. ``PurchaseOrder Id="PO-1001"`` -> ``Id`` matches
   the id-like-name list exactly).
2. LLM fallback: only when the heuristic finds nothing (e.g. ``LineItem
   Sku="WIDGET-A"`` -- "Sku" matches neither list by default) -- one call
   per distinct tag, not per node, fed the sample node's property keys in
   place of a CSV header row.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from aryx.cpq_ingestion.raw_graph.models import RawNode
from aryx.llm import llm_runtime
from aryx.pipeline.doc_discovery.doc_discovery_types import _id_like_names, _key_suffixes

logger = logging.getLogger(__name__)


def _guess_key_prop(properties: dict[str, Any]) -> str | None:
    """Heuristic-only match key guess from a sample node's property keys.

    Returns ``None`` (not a default first-key guess) when nothing matches,
    so the caller can tell "found one" apart from "nothing to go on" and
    only pay for an LLM call in the latter case.
    """
    if not properties:
        return None
    keys = list(properties.keys())
    id_names = _id_like_names()
    for k in keys:
        if k.lower() in id_names:
            return k
    suffixes = _key_suffixes()
    for k in keys[:6]:
        if any(k.lower().endswith(sfx) for sfx in suffixes):
            return k
    return None


def _llm_guess_key_prop(tag: str, properties: dict[str, Any], context: str,
                        log_id: str | None = None) -> str | None:
    """LLM fallback, one call, fed property keys in place of a CSV sample."""
    if not properties:
        return None
    sys = ("You identify which property uniquely identifies each node of a "
           "given type in a knowledge graph.")
    user = (f"Goal: {context or 'general knowledge graph'}\nNode type: {tag}\n"
            f"Sample properties: {json.dumps(properties)[:600]}\n\n"
            "Which ONE property UNIQUELY IDENTIFIES each node of this type "
            "(the natural key or ID)?\n"
            'Reply ONLY as JSON: {"match_key":"prop_name"}.')
    try:
        txt = llm_runtime.chat("menial", sys, user)[0]
        s, e = txt.find("{"), txt.rfind("}")
        if s == -1 or e <= s:
            raise ValueError("LLM response contained no JSON object")
        d = json.loads(txt[s:e + 1])
        key = (d.get("match_key") or "").strip()
        return key if key in properties else None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "raw_graph infer_match_key did=%s tag=%s LLM inference failed: %s",
            log_id, tag, exc,
        )
        return None


def infer_match_keys_for_tag(tag: str, sample_nodes: list[RawNode], context: str = "",
                             log_id: str | None = None) -> dict[str, Any]:
    """Infer ``{"ontology_type": tag, "match_keys": [...]}`` for one raw-graph tag.

    ``sample_nodes`` need only contain one representative node in the
    common case -- a short list lets the heuristic try a couple of nodes
    before giving up (some nodes in a batch may be missing an optional
    attribute another node of the same tag has).
    """
    sample_properties = next(
        (n.properties for n in sample_nodes if n.properties), {},
    )
    key = _guess_key_prop(sample_properties)
    source = "heuristic"
    if key is None:
        key = _llm_guess_key_prop(tag, sample_properties, context, log_id=log_id)
        source = "llm"
    if key is None:
        key = next(iter(sample_properties), "id")
        source = "default"
    result = {"ontology_type": tag, "match_keys": [key]}
    logger.info(
        "raw_graph infer_match_key did=%s tag=%s otype=%s match_keys=%s source=%s",
        log_id, tag, result["ontology_type"], result["match_keys"], source,
    )
    return result
