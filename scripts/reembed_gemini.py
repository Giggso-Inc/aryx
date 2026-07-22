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
from typing import Any, Iterator

from aryx.broker import Broker, default_broker
from aryx.config import get_settings
from aryx.models import ChunkEmbedding
from aryx.queries import load
from aryx.store.chunk_store import ChunkStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("reembed_gemini")


def _fetch_unembedded_chunks(
    pool: Any, model_id: str, batch_size: int,
) -> Iterator[list[tuple[int, str]]]:
    """Yield bounded keyset pages of chunks missing the target embedding.

    Args:
        pool: Psycopg- or Oracle-compatible connection pool.
        model_id: Target embedding model identifier.
        batch_size: Maximum rows fetched per database round trip.

    Yields:
        Ordered ``(chunk_id, text)`` batches.

    Raises:
        ValueError: If ``batch_size`` is not positive.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    after_id = 0
    while True:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    load("select_unembedded_chunks_page"),
                    {
                        "model_id": model_id,
                        "after_id": after_id,
                        "batch_size": batch_size,
                    },
                )
                rows = cur.fetchall()
        if not rows:
            return
        batch = [(int(row[0]), str(row[1])) for row in rows]
        yield batch
        after_id = batch[-1][0]


def _embed_batch(
    store: ChunkStore,
    broker: Broker,
    batch: list[tuple[int, str]],
    model_id: str,
) -> bool:
    """Embed and persist one validated chunk batch; return success."""
    chunk_ids = [row[0] for row in batch]
    vectors = broker.embed([row[1] for row in batch])
    if not vectors:
        logger.error("broker.embed() returned no vectors — aborting")
        return False
    if len(vectors) != len(batch):
        logger.error(
            "broker.embed() returned %d vectors for %d chunks — aborting",
            len(vectors), len(batch),
        )
        return False
    dims = {len(vector) for vector in vectors}
    if dims != {768}:
        logger.error(
            "embed dims=%s, expected only 768 "
            "(aryx_chunk_embedding.embedding column width) — check "
            "output_dimensionality wiring before continuing",
            sorted(dims),
        )
        return False

    embeddings = [
        ChunkEmbedding(
            chunk_index=0,
            doc_id="",
            model_id=model_id,
            dim=768,
            vector=vector,
        )
        for vector in vectors
    ]
    store.save_embeddings(chunk_ids, embeddings)
    return True


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
    model_id = settings.embed_model_override or "gemini-embedding-2"

    total = 0
    for batch in _fetch_unembedded_chunks(store._pool, model_id, args.batch_size):
        chunk_ids = [r[0] for r in batch]
        if args.dry_run:
            total += len(batch)
            logger.info("dry-run: would embed %d chunks (ids %s..%s)",
                       len(batch), chunk_ids[0], chunk_ids[-1])
            continue

        if not _embed_batch(store, broker, batch, model_id):
            return 1
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
