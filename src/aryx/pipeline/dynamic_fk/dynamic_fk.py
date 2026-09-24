"""Dynamic, value-based + LLM-judged FK detection for tabular ingestion.

Runs AFTER the column-name passes in doc_discovery._detect_fk_links, over
whichever type pairs those passes did not already resolve. Nothing here is
specific to any column name, entity type, or dataset — every judgment is
made from the data actually present in the batch being ingested.

Two stages:

Stage 1 (cheap, no LLM call, no hardcoded column/type names): sample a
bounded number of DISTINCT values per column (deduplicated, so a
heavily-duplicated source costs the same as a clean one), normalize them,
and score value-set overlap between every pair of columns across every pair
of entity types. Produces a candidate list purely from the data itself.

Stage 2 (LLM judge + reason): every Stage-1 candidate is sent to the LLM for
a real relationship judgment with a reason, covering relationships no naming
convention could ever anticipate (differently-named columns, derived/partial
joins). No count cap is applied to how many candidates are judged — every
candidate that clears Stage 1 gets a verdict; ARYX_FK_DYNAMIC_JUDGE_WORKERS
only bounds concurrency (throughput), never coverage, so no relationship is
silently dropped by this stage.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.llm import complete_json
from aryx.pipeline.dynamic_fk.dynamic_fk_sampling import (
    _candidate_columns,
    _headers,
    estimate_join_fanout,
    sample_distinct_values,
    sample_value_counts,
    try_prefix_transforms,
    value_overlap_ratio,
)

logger = logging.getLogger(__name__)

_BATCH_JUDGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "linked": {"type": "boolean"},
                    "cardinality": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["index", "linked", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdicts"],
}


def generate_candidate_pairs(
    plans: list[dict],
    already_linked: set[tuple[str, str]] | None = None,
    log_id: str | None = None,
) -> list[dict]:
    """Stage 1: value-overlap candidate filter.

    Returns every {type_a, col_a, type_b, col_b, overlap, samples_a,
    samples_b} whose overlap clears ARYX_FK_VALUE_OVERLAP_THRESHOLD. No
    count cap — every unresolved type pair and column pair is scored; only
    ARYX_FK_VALUE_SAMPLE_SIZE bounds the per-column sampling cost.
    """
    settings = get_settings()
    already_linked = already_linked or set()
    sample_size = settings.fk_value_sample_size
    threshold = settings.fk_value_overlap_threshold
    fanout_scan_rows = settings.fk_fanout_scan_rows
    max_fanout = settings.fk_max_estimated_fanout
    prefix_lengths = [
        int(n) for n in settings.fk_prefix_transform_lengths.split(",") if n.strip()
    ]

    plan_headers = [_headers(p["data"]) for p in plans]
    value_cache: dict[tuple[int, str], set[str]] = {}

    def _values(idx: int, col: str) -> set[str]:
        key = (idx, col)
        if key not in value_cache:
            value_cache[key] = sample_distinct_values(
                plans[idx]["data"], plan_headers[idx], col, sample_size,
            )
        return value_cache[key]

    candidates: list[dict] = []
    seen_cols: set[tuple[str, str, str, str]] = set()
    for i, plan_a in enumerate(plans):
        type_a = plan_a["ontology_type"]
        for j, plan_b in enumerate(plans):
            if i >= j:
                continue
            type_b = plan_b["ontology_type"]
            if type_a == type_b:
                continue
            if (type_a, type_b) in already_linked or (type_b, type_a) in already_linked:
                continue
            for col_a in _candidate_columns(plan_headers[i]):
                values_a = _values(i, col_a)
                if len(values_a) < 2:
                    continue
                for col_b in _candidate_columns(plan_headers[j]):
                    pair_key = (type_a, col_a, type_b, col_b)
                    if pair_key in seen_cols:
                        continue
                    values_b = _values(j, col_b)
                    if len(values_b) < 2:
                        continue
                    ratio = value_overlap_ratio(values_a, values_b)
                    prefix_len_a: int | None = None
                    prefix_len_b: int | None = None
                    transform_desc: str | None = None
                    eval_a, eval_b = values_a, values_b
                    if ratio < threshold and prefix_lengths:
                        # Fallback: raw values don't overlap enough — try a
                        # derived (prefix-truncated) relationship instead,
                        # e.g. a short grouped code that is really a prefix
                        # of a longer code in the other table. Generic: no
                        # column name or specific transform is hardcoded,
                        # only a small set of configured lengths.
                        best = try_prefix_transforms(values_a, values_b, prefix_lengths)
                        if best and best[0] >= threshold:
                            ratio, prefix_len_a, prefix_len_b, eval_a, eval_b = best
                            transform_desc = (
                                f"Table A's column truncated to its first {prefix_len_a} character(s)"
                                if prefix_len_a is not None else
                                f"Table B's column truncated to its first {prefix_len_b} character(s)"
                            )
                    if ratio < threshold:
                        continue
                    # Selectivity guard: a candidate can have a perfectly
                    # reasonable DISTINCT-value overlap ratio while still
                    # being a shared low-cardinality category (not a real
                    # join key) — that only shows up once you account for
                    # how many ROWS share each value, not just how many
                    # distinct values overlap. Estimate the actual join
                    # fan-out before this candidate is even considered, so a
                    # non-selective pair never reaches the LLM judge or
                    # becomes an fk_link. Uses the SAME prefix transform (if
                    # any) the candidate was found under, since truncation
                    # only ever merges groups and would otherwise understate
                    # the real fan-out risk.
                    fanout = estimate_join_fanout(
                        plans[i]["data"], plan_headers[i], col_a,
                        plans[j]["data"], plan_headers[j], col_b,
                        fanout_scan_rows,
                        prefix_len_a=prefix_len_a, prefix_len_b=prefix_len_b,
                    )
                    if fanout > max_fanout:
                        logger.info(
                            "value_overlap log_id=%s type_a=%s col_a=%s "
                            "type_b=%s col_b=%s ratio=%.3f transform=%r REJECTED "
                            "estimated_fanout=%d exceeds max=%d — non-selective "
                            "join key, skipping",
                            log_id, type_a, col_a, type_b, col_b, ratio,
                            transform_desc, fanout, max_fanout,
                        )
                        seen_cols.add(pair_key)
                        continue
                    seen_cols.add(pair_key)
                    candidates.append({
                        "type_a": type_a, "col_a": col_a,
                        "type_b": type_b, "col_b": col_b,
                        "overlap": ratio,
                        "transform": transform_desc,
                        "samples_a": sorted(eval_a)[:5],
                        "samples_b": sorted(eval_b)[:5],
                    })
                    logger.info(
                        "value_overlap log_id=%s type_a=%s col_a=%s "
                        "type_b=%s col_b=%s ratio=%.3f transform=%r estimated_fanout=%d",
                        log_id, type_a, col_a, type_b, col_b, ratio,
                        transform_desc, fanout,
                    )
    return candidates


# Live-confirmed (2026-09-23, real OCI GenAI "cheap" tier call): despite
# _BATCH_JUDGE_SCHEMA requiring the key "index", the model returned
# "pair_index" instead for every verdict in the response — the judgments
# themselves were correct, only the index key name drifted. LLM structured
# output does not reliably follow an exact property name even when the
# schema marks it required, so parsing accepts common aliases, and falls
# back to response order when no alias is present at all (a model that
# just answers "in order" without indexing anything) rather than silently
# discarding every candidate in the batch over a naming mismatch.
_INDEX_KEY_ALIASES = ("index", "pair_index", "idx", "i")


def _extract_verdicts_by_index(verdicts: list, batch_len: int) -> dict[int, dict]:
    by_index: dict[int, dict] = {}
    for v in verdicts:
        if not isinstance(v, dict):
            continue
        for key in _INDEX_KEY_ALIASES:
            idx = v.get(key)
            if isinstance(idx, int) and 0 <= idx < batch_len:
                by_index[idx] = v
                break
    if by_index:
        return by_index
    # No usable index key on ANY verdict -- if the response has exactly one
    # verdict per candidate, fall back to positional order rather than
    # treating a fully-answered batch as fully missing.
    if len(verdicts) == batch_len:
        return {i: v for i, v in enumerate(verdicts) if isinstance(v, dict)}
    return {}


def _judge_batch(
    batch: list[dict], broker: Broker, log_id: str | None,
) -> list[dict | None]:
    """Stage 2: ask the LLM to judge a BATCH of candidate pairs in one call.

    Returns a list the same length as *batch*, positionally aligned — each
    entry is an fk_link spec (linked) or None (not linked, or no verdict
    came back for that index — same fail-open contract either way). Every
    verdict — accepted, rejected, or missing — is logged with its reason,
    so "why is this pair linked/unlinked" is always answerable from logs
    alone, same as the pre-batching per-candidate version.

    Trade-off, by design (2026-09-23, docs/ingestion/SPARK_PARALLEL_
    MIGRATION_ANALYSIS_2026-09-23.md Phase 2): fewer, larger LLM calls cuts
    the fixed per-call overhead that dominates at high concurrency, but one
    failed call now costs a whole batch's verdicts instead of one
    candidate's — every candidate in a failed batch is treated as
    not-linked and logged, same fail-open behavior as a single-candidate
    failure, just wider blast radius. ARYX_FK_DYNAMIC_JUDGE_BATCH_SIZE=1
    recovers the original one-candidate-per-call behavior exactly.
    """
    system = (
        "You determine, for EACH of several pairs of columns from "
        "different data tables, whether the two columns reference the "
        "same real-world thing (a valid join key), based only on the "
        "column names and sample values given for that pair. Judge every "
        "pair independently — one pair's evidence must never influence "
        "another pair's verdict. Consider derived or partial relationships "
        "(e.g. one column being a truncated, coded, or aggregated form of "
        "the other) as well as direct equality. Be conservative: only say "
        "linked=true when the evidence genuinely supports it. Return "
        "exactly one verdict per pair, each tagged with that pair's index. "
        "Every single verdict MUST include its own short reason (one "
        "sentence) explaining that specific pair's decision — never omit "
        "the reason field, even when linked=false."
    )
    pair_blocks = []
    for i, candidate in enumerate(batch):
        transform = candidate.get("transform")
        transform_note = (
            f" (found via value transform: {transform} — sample values "
            f"shown are AFTER that transform, not raw)"
            if transform else ""
        )
        pair_blocks.append(
            f"Pair {i}{transform_note}:\n"
            f"  Table A type={candidate['type_a']!r} column={candidate['col_a']!r} "
            f"sample values={candidate['samples_a']!r}\n"
            f"  Table B type={candidate['type_b']!r} column={candidate['col_b']!r} "
            f"sample values={candidate['samples_b']!r}\n"
            f"  Cheap value-overlap ratio already measured: {candidate['overlap']:.3f}"
        )
    user = (
        f"Judge each of the following {len(batch)} pairs. For each, is "
        "table A's column a valid reference to table B's column?\n\n"
        + "\n\n".join(pair_blocks)
    )
    try:
        result = complete_json(broker, "cheap", system, user, _BATCH_JUDGE_SCHEMA)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "fk_llm_verdict log_id=%s batch judge call failed for %d candidate(s): %s",
            log_id, len(batch), exc,
        )
        return [None] * len(batch)

    verdicts_by_index = _extract_verdicts_by_index(result.get("verdicts") or [], len(batch))

    links: list[dict | None] = []
    for i, candidate in enumerate(batch):
        verdict = verdicts_by_index.get(i)
        if verdict is None:
            logger.warning(
                "fk_llm_verdict log_id=%s type_a=%s type_b=%s batch "
                "response missing verdict for index %d — treating as not linked",
                log_id, candidate["type_a"], candidate["type_b"], i,
            )
            links.append(None)
            continue
        linked = bool(verdict.get("linked"))
        reason = str(verdict.get("reason", ""))[:200]
        logger.info(
            "fk_llm_verdict log_id=%s type_a=%s col_a=%s type_b=%s col_b=%s "
            "linked=%s reason=%r",
            log_id, candidate["type_a"], candidate["col_a"],
            candidate["type_b"], candidate["col_b"], linked, reason,
        )
        if not linked:
            links.append(None)
            continue
        links.append({
            "source_type": candidate["type_a"],
            "source_attr": candidate["col_a"],
            "target_type": candidate["type_b"],
            "target_attr": candidate["col_b"],
            "name": f"{candidate['type_b'].upper()}_HAS_{candidate['type_a'].upper()}",
            "reason": reason,
        })
    return links


def judge_candidates_with_llm(
    candidates: list[dict], broker: Broker, log_id: str | None = None,
    on_progress: "Callable[[int, int], None] | None" = None,
) -> list[dict]:
    """Stage 2: judge every candidate pair concurrently, batching several
    per LLM call.

    ARYX_FK_DYNAMIC_JUDGE_WORKERS bounds how many batch-judge calls run at
    once. ARYX_FK_DYNAMIC_JUDGE_BATCH_SIZE (default 5) bounds how many
    candidates go into one LLM call — fewer, larger calls cut the fixed
    per-call overhead that dominates at high worker counts (see docs/
    ingestion/SPARK_PARALLEL_MIGRATION_ANALYSIS_2026-09-23.md Phase 2).
    Neither setting caps how many candidates get judged — every item in
    *candidates* receives a verdict (or a logged not-linked fallback if its
    batch's call failed).

    on_progress(done, total) — optional, called once per CANDIDATE as its
    verdict becomes available (not once per batch — batching changes how
    many LLM calls happen, not this callback's granularity), so existing
    callers (e.g. job-progress reporting) see the same per-candidate signal
    regardless of batch size. Never lets a callback exception break judging.
    """
    if not candidates:
        return []
    settings = get_settings()
    workers = max(1, settings.fk_dynamic_judge_workers)
    batch_size = max(1, settings.fk_dynamic_judge_batch_size)
    batches = [candidates[i:i + batch_size] for i in range(0, len(candidates), batch_size)]
    total = len(candidates)
    done = 0
    links: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_judge_batch, batch, broker, log_id): batch for batch in batches}
        for future in as_completed(futures):
            batch_links = future.result()
            for link in batch_links:
                if link is not None:
                    links.append(link)
                done += 1
                if on_progress is not None:
                    try:
                        on_progress(done, total)
                    except Exception:  # noqa: BLE001 — progress reporting must never break judging
                        logger.warning("dynamic_fk on_progress callback failed", exc_info=True)
    return links


def detect_dynamic_fk_links(
    plans: list[dict], broker: Broker,
    already_linked: set[tuple[str, str]] | None = None,
    log_id: str | None = None,
    on_progress: "Callable[[int, int], None] | None" = None,
) -> list[dict]:
    """Full Stage 1 + Stage 2 dynamic FK detection over *plans*.

    Intended to run after doc_discovery._detect_fk_links; *already_linked*
    should be the set of (source_type, target_type) pairs those column-name
    passes already resolved, so this stage only fills the gap they miss —
    it never duplicates or overrides an already-found relationship.

    on_progress — see judge_candidates_with_llm; threaded through so the
    caller (ingest_confirmed) can report real progress during the slow,
    uncapped, per-candidate LLM-judge stage.
    """
    settings = get_settings()
    if not settings.fk_dynamic_detection_enabled or len(plans) < 2:
        return []
    t0 = time.monotonic()
    candidates = generate_candidate_pairs(plans, already_linked=already_linked, log_id=log_id)
    t1 = time.monotonic()
    links = judge_candidates_with_llm(candidates, broker, log_id=log_id, on_progress=on_progress)
    t2 = time.monotonic()
    logger.info(
        "ingest_timing log_id=%s stage=dynamic_fk plans=%d candidates=%d "
        "links_found=%d value_sample_ms=%d llm_judge_ms=%d",
        log_id, len(plans), len(candidates), len(links),
        int((t1 - t0) * 1000), int((t2 - t1) * 1000),
    )
    return links
