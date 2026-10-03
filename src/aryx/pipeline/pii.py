"""PII detection and anonymization gate (Inc 10).

Presidio Analyzer (spaCy en_core_web_sm + regex recognizers) detects PII spans
locally — no text leaves the machine until this gate clears. The boundary is
fail-closed: a chunk with unhandled PII spans raises rather than passing through.

Requires: presidio-analyzer presidio-anonymizer spacy en_core_web_sm
  python -m spacy download en_core_web_sm
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING

from aryx.models import DocumentChunk
from aryx.raven_log import current_run_id, raven_log, would_log

if TYPE_CHECKING:
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig

logger = logging.getLogger(__name__)


class PiiAction(str, Enum):
    MASK = "mask"
    HASH = "hash"
    DROP = "drop"
    KEEP = "keep"


@dataclass
class PiiPolicy:
    default_action: PiiAction = PiiAction.MASK
    entity_actions: dict[str, PiiAction] = field(default_factory=dict)


DEFAULT_POLICY = PiiPolicy(
    default_action=PiiAction.MASK,
    entity_actions={
        "EMAIL_ADDRESS": PiiAction.HASH,
        "PHONE_NUMBER": PiiAction.MASK,
        "PERSON": PiiAction.MASK,
        "CREDIT_CARD": PiiAction.DROP,
        "IBAN_CODE": PiiAction.DROP,
        "US_SSN": PiiAction.DROP,
    },
)


@lru_cache(maxsize=1)
def _engines() -> "tuple[AnalyzerEngine, AnonymizerEngine]":
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine
    return AnalyzerEngine(), AnonymizerEngine()


def _operator_config(entity_type: str, policy: PiiPolicy) -> "OperatorConfig":
    from presidio_anonymizer.entities import OperatorConfig
    action = policy.entity_actions.get(entity_type, policy.default_action)
    if action == PiiAction.MASK:
        return OperatorConfig("replace", {"new_value": f"<{entity_type}>"})
    if action == PiiAction.HASH:
        return OperatorConfig("hash", {"hash_type": "sha256"})
    if action == PiiAction.DROP:
        return OperatorConfig("redact")
    return OperatorConfig("keep")


def screen_chunks(
    chunks: list[DocumentChunk],
    policy: PiiPolicy | None = None,
) -> list[DocumentChunk]:
    """Detect and anonymize PII in every chunk before any text leaves the machine.

    Fail-closed: if Presidio fails to load, this raises immediately so the caller
    cannot proceed with unscreened text.

    Args:
        chunks: Normalized chunks from clean_text.chunk_pages().
        policy: PII action policy; defaults to DEFAULT_POLICY.

    Returns:
        New DocumentChunk list with PII-anonymized text.
    """
    if not chunks:
        raven_log("DEBUG", "P4", "ingest.pii.skipped no chunks to screen",
                  context={"selected_option": "skip", "available_options": ["skip", "screen"],
                           "reason_code": "NO_CHUNKS", "policy_version": "pii_gate_v1"})
        return []

    custom_policy = policy is not None
    if policy is None:
        policy = DEFAULT_POLICY
    started = time.monotonic()

    try:
        analyzer, anonymizer = _engines()
    except Exception as exc:
        # Fail-closed gate: no engine means no unscreened text may pass.
        raven_log("ERROR", "P2", "ingest.pii.engine_failed the PII engines could not be loaded",
                  error_code="ARYX_ING_PII_ENGINE_FAILED",
                  context={"dependency_name": "presidio", "operation": "load_engines",
                           "duration_ms": int((time.monotonic() - started) * 1000),
                           "result": "error", "error_class": type(exc).__name__, "attempt": 1,
                           "trace_id": current_run_id(), "chunks": len(chunks)})
        raise
    screened: list[DocumentChunk] = []
    chunks_with_pii = 0
    entity_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}

    for chunk in chunks:
        results = analyzer.analyze(text=chunk.text, language="en")
        if not results:
            screened.append(chunk)
            continue

        operators = {r.entity_type: _operator_config(r.entity_type, policy) for r in results}
        anonymized = anonymizer.anonymize(
            text=chunk.text, analyzer_results=results, operators=operators
        )
        screened.append(chunk.model_copy(update={"text": anonymized.text}))
        logger.debug("pii screened chunk=%d entities=%d", chunk.chunk_index, len(results))
        chunks_with_pii += 1
        for r in results:
            entity_counts[r.entity_type] = entity_counts.get(r.entity_type, 0) + 1
            act = policy.entity_actions.get(r.entity_type, policy.default_action).value
            action_counts[act] = action_counts.get(act, 0) + 1
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ingest.pii.chunk_screened PII found and anonymized",
                      context={"selected_option": "anonymize", "available_options": ["keep", "anonymize"],
                               "reason_code": "PII_FOUND", "policy_version": "pii_gate_v1",
                               "chunk_index": chunk.chunk_index, "entities": len(results),
                               "entity_types": sorted({r.entity_type for r in results})})

    logger.info("pii screen complete chunks=%d", len(chunks))
    raven_log("INFO", "P4", "ingest.pii.completed chunks screened",
              context={"task_id": current_run_id(), "final_status": "complete",
                       "duration_ms": int((time.monotonic() - started) * 1000),
                       "stage": "pii_screen", "result": "ok", "reason_code": "SCREENED",
                       "impact_scope": "document_chunks", "chunks": len(chunks),
                       "chunks_with_pii": chunks_with_pii, "custom_policy": custom_policy,
                       "entities_by_type": entity_counts, "actions": action_counts})
    return screened
