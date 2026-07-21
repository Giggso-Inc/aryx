"""Re-embed existing aryx_chunk rows under Gemini (one-off migration, Phase 2
of docs/LLM_GEMINI_MIGRATION_PLAN.md).

Existing rows keep their old model_id (e.g. nomic-embed-text) untouched —
aryx_chunk_embedding's UNIQUE (chunk_id, model_id) constraint means writing
under a NEW model_id inserts alongside the old rows rather than overwriting
them, so this is safe to run before fully cutting over. Re-runnable: ON
CONFLICT DO NOTHING skips chunks already embedded under the target model.

IMPORTANT — do not run this until:
  1. ARYX_LLM_API_KEY holds a real Gemini key and ARYX_EMBED_BACKEND=gemini
     has been live-verified on at least one fresh document (Phase 2 test
     plan, docs/LLM_GEMINI_MIGRATION_PLAN.md §3.4/§4).
  2. You are ready to also DELETE the old model_id's rows afterward —
     ChunkStore.check_embed_compat() does `SELECT DISTINCT model_id, dim
     ... LIMIT 1`, which becomes non-deterministic once two model_ids
     coexist across different chunks. This script does NOT delete the old
     rows itself (kept as a manual, deliberate step — see bottom of file).

Usage:
    PYTHONPATH=src python3 scripts/reembed_gemini.py [--batch-size 50] [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import sys

from aryx.broker import default_broker
from aryx.config import get_settings
from aryx.models import ChunkEmbedding
from aryx.store.chunk_store import ChunkStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("reembed_gemini")


def _fetch_unembedded_chunks(pool, model_id: str, batch_size: int):
    """Yield (chunk_id, text) batches not yet embedded under model_id."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id, c.text
                FROM aryx_chunk c
                WHERE NOT EXISTS (
                    SELECT 1 FROM aryx_chunk_embedding ce
                    WHERE ce.chunk_id = c.id AND ce.model_id = %s
                )
                ORDER BY c.id
                """,
                (model_id,),
            )
            rows = cur.fetchall()
    for i in range(0, len(rows), batch_size):
        yield rows[i:i + batch_size]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true",
                        help="Count chunks that would be embedded; write nothing.")
    args = parser.parse_args()

    settings = get_settings()
    if settings.effective_embed_backend() != "gemini":
        logger.error(
            "ARYX_EMBED_BACKEND is %r, not 'gemini' — refusing to run "
            "(this script only makes sense once the backend is actually switched)",
            settings.effective_embed_backend(),
        )
        return 1

    broker = default_broker()
    store = ChunkStore(settings.effective_dsn())
    model_id = settings.embed_model_override or "gemini-embedding-001"

    total = 0
    for batch in _fetch_unembedded_chunks(store._pool, model_id, args.batch_size):
        chunk_ids = [r[0] for r in batch]
        texts = [r[1] for r in batch]
        if args.dry_run:
            total += len(batch)
            logger.info("dry-run: would embed %d chunks (ids %s..%s)",
                       len(batch), chunk_ids[0], chunk_ids[-1])
            continue

        vectors = broker.embed(texts)
        if not vectors:
            logger.error("broker.embed() returned no vectors — aborting")
            return 1
        dim = len(vectors[0])
        if dim != 768:
            logger.error(
                "embed dim=%d, expected 768 (documents.embedding column width) "
                "— check output_dimensionality wiring before continuing", dim)
            return 1

        embeddings = [
            ChunkEmbedding(chunk_index=0, doc_id="", model_id=model_id, dim=dim, vector=vec)
            for vec in vectors
        ]
        store.save_embeddings(chunk_ids, embeddings)
        total += len(batch)
        logger.info("embedded batch: %d chunks (running total %d)", len(batch), total)

    logger.info("%sdone — %d chunks processed under model_id=%s",
               "[DRY RUN] " if args.dry_run else "", total, model_id)
    if not args.dry_run and total > 0:
        logger.info(
            "Old-model rows were NOT deleted — once Gemini embeddings are "
            "verified (similarity/resolution spot-checks look right), run:\n"
            "  DELETE FROM aryx_chunk_embedding WHERE model_id != %r;\n"
            "manually, so ChunkStore.check_embed_compat()'s single-row check "
            "stops seeing two coexisting model_ids.", model_id,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
