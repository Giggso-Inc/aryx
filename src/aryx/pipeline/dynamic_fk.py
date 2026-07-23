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

import csv
import io
import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from aryx.broker import Broker
from aryx.config import get_settings
from aryx.llm import complete_json
from aryx.pipeline.value_normalize import normalize_value

logger = logging.getLogger(__name__)

_JUDGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "linked": {"type": "boolean"},
        "cardinality": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["linked", "reason"],
    "additionalProperties": False,
}


def _headers(data: bytes) -> list[str]:
    try:
        line = data.split(b"\n")[0].decode("utf-8", "ignore")
        return next(csv.reader(io.StringIO(line)))
    except Exception:  # noqa: BLE001
        return []


def sample_distinct_values(
    data: bytes, headers: list[str], col: str, sample_size: int,
) -> set[str]:
    """Return up to *sample_size* distinct normalized values for *col*.

    Scans rows until the file is exhausted or *sample_size* distinct values
    have been collected — deduping as it goes so a heavily-duplicated source
    (e.g. a data extract that is 90%+ duplicate rows) costs the same as a
    clean one, not O(raw row count).
    """
    values: set[str] = set()
    try:
        idx = headers.index(col)
    except ValueError:
        return values
    lines = data.split(b"\n")[1:]
    for line in lines:
        if len(values) >= sample_size:
            break
        try:
            row = next(csv.reader(io.StringIO(line.decode("utf-8", "ignore"))), None)
        except Exception:  # noqa: BLE001
            continue
        if row and idx < len(row):
            v = row[idx].strip()
            if v:
                values.add(normalize_value(v))
    return values


def value_overlap_ratio(values_a: set[str], values_b: set[str]) -> float:
    """Fraction of the smaller set's values also present in the other set.

    Using the smaller side as the denominator means a small lookup/reference
    table fully contained in a much larger transactional table still scores
    near 1.0 — the typical parent/child shape of tabular sources — instead
    of being washed out by a Jaccard-style union denominator.
    """
    if not values_a or not values_b:
        return 0.0
    smaller, larger = (values_a, values_b) if len(values_a) <= len(values_b) else (values_b, values_a)
    if not smaller:
        return 0.0
    return len(smaller & larger) / len(smaller)


def sample_value_counts(
    data: bytes, headers: list[str], col: str, max_rows: int,
) -> Counter[str]:
    """Return normalized-value -> occurrence-count for *col*, scanning at
    most *max_rows* rows.

    Unlike sample_distinct_values() (which stops once enough DISTINCT values
    are seen), this scans a bounded number of ROWS so it stays cheap
    regardless of the column's cardinality — the exact case a distinct-only
    sampler misses: a low-cardinality column (few distinct values, e.g. a
    category code) never trips a distinct-value cap, so an unbounded scan of
    it would cost the full row count. A capped row scan is still a valid,
    conservative fan-out signal.
    """
    counts: Counter[str] = Counter()
    try:
        idx = headers.index(col)
    except ValueError:
        return counts
    lines = data.split(b"\n")[1:]
    for line in lines[:max_rows]:
        try:
            row = next(csv.reader(io.StringIO(line.decode("utf-8", "ignore"))), None)
        except Exception:  # noqa: BLE001
            continue
        if row and idx < len(row):
            v = row[idx].strip()
            if v:
                counts[normalize_value(v)] += 1
    return counts


def estimate_join_fanout(
    data_a: bytes, headers_a: list[str], col_a: str,
    data_b: bytes, headers_b: list[str], col_b: str,
    max_rows: int,
) -> int:
    """Estimate how many relationship rows joining col_a to col_b would
    produce: for every value shared by both sides, its occurrence count on
    side A times its occurrence count on side B, summed.

    This is what actually distinguishes a real (near-unique) join key from a
    shared low-cardinality category code: a category shared by hundreds of
    rows on each side multiplies into a huge number of pairs even though its
    *distinct*-value overlap ratio looks perfectly reasonable.
    """
    counts_a = sample_value_counts(data_a, headers_a, col_a, max_rows)
    counts_b = sample_value_counts(data_b, headers_b, col_b, max_rows)
    return sum(counts_a[v] * counts_b[v] for v in counts_a.keys() & counts_b.keys())


def _candidate_columns(headers: list[str]) -> list[str]:
    """Every header is a candidate — no hardcoded name allow-list.

    Only aryx-internal bookkeeping columns (leading underscore, e.g.
    _element_type) are excluded.
    """
    return [h for h in headers if h and not h.startswith("_")]


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
                    # becomes an fk_link.
                    fanout = estimate_join_fanout(
                        plans[i]["data"], plan_headers[i], col_a,
                        plans[j]["data"], plan_headers[j], col_b,
                        fanout_scan_rows,
                    )
                    if fanout > max_fanout:
                        logger.info(
                            "value_overlap log_id=%s type_a=%s col_a=%s "
                            "type_b=%s col_b=%s ratio=%.3f REJECTED "
                            "estimated_fanout=%d exceeds max=%d — non-selective "
                            "join key, skipping",
                            log_id, type_a, col_a, type_b, col_b, ratio,
                            fanout, max_fanout,
                        )
                        seen_cols.add(pair_key)
                        continue
                    seen_cols.add(pair_key)
                    candidates.append({
                        "type_a": type_a, "col_a": col_a,
                        "type_b": type_b, "col_b": col_b,
                        "overlap": ratio,
                        "samples_a": sorted(values_a)[:5],
                        "samples_b": sorted(values_b)[:5],
                    })
                    logger.info(
                        "value_overlap log_id=%s type_a=%s col_a=%s "
                        "type_b=%s col_b=%s ratio=%.3f estimated_fanout=%d",
                        log_id, type_a, col_a, type_b, col_b, ratio, fanout,
                    )
    return candidates


def _judge_one(candidate: dict, broker: Broker, log_id: str | None) -> dict | None:
    """Stage 2: ask the LLM whether this candidate pair is a real relationship.

    Returns an fk_link spec if the LLM confirms a link, else None. Every
    verdict — accepted or rejected — is logged with its reason, so "why is
    this pair linked/unlinked" is always answerable from logs alone.
    """
    system = (
        "You determine whether two columns from two different data tables "
        "reference the same real-world thing (a valid join key), based only "
        "on the column names and sample values given. Consider derived or "
        "partial relationships (e.g. one column being a truncated, coded, or "
        "aggregated form of the other) as well as direct equality. Be "
        "conservative: only say linked=true when the evidence genuinely "
        "supports it."
    )
    user = (
        f"Table A type={candidate['type_a']!r} column={candidate['col_a']!r} "
        f"sample values={candidate['samples_a']!r}\n"
        f"Table B type={candidate['type_b']!r} column={candidate['col_b']!r} "
        f"sample values={candidate['samples_b']!r}\n"
        f"Cheap value-overlap ratio already measured: {candidate['overlap']:.3f}\n"
        "Is table A's column a valid reference to table B's column?"
    )
    try:
        result = complete_json(broker, "cheap", system, user, _JUDGE_SCHEMA)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "fk_llm_verdict log_id=%s type_a=%s type_b=%s judge call failed: %s",
            log_id, candidate["type_a"], candidate["type_b"], exc,
        )
        return None
    linked = bool(result.get("linked"))
    reason = str(result.get("reason", ""))[:200]
    logger.info(
        "fk_llm_verdict log_id=%s type_a=%s col_a=%s type_b=%s col_b=%s "
        "linked=%s reason=%r",
        log_id, candidate["type_a"], candidate["col_a"],
        candidate["type_b"], candidate["col_b"], linked, reason,
    )
    if not linked:
        return None
    return {
        "source_type": candidate["type_a"],
        "source_attr": candidate["col_a"],
        "target_type": candidate["type_b"],
        "target_attr": candidate["col_b"],
        "name": f"{candidate['type_b'].upper()}_HAS_{candidate['type_a'].upper()}",
        "reason": reason,
    }


def judge_candidates_with_llm(
    candidates: list[dict], broker: Broker, log_id: str | None = None,
) -> list[dict]:
    """Stage 2: judge every candidate pair concurrently.

    ARYX_FK_DYNAMIC_JUDGE_WORKERS bounds how many judge calls run at once —
    it never caps how many candidates get judged. Every item in *candidates*
    receives a verdict.
    """
    if not candidates:
        return []
    settings = get_settings()
    workers = max(1, settings.fk_dynamic_judge_workers)
    links: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_judge_one, c, broker, log_id) for c in candidates]
        for future in as_completed(futures):
            link = future.result()
            if link is not None:
                links.append(link)
    return links


def detect_dynamic_fk_links(
    plans: list[dict], broker: Broker,
    already_linked: set[tuple[str, str]] | None = None,
    log_id: str | None = None,
) -> list[dict]:
    """Full Stage 1 + Stage 2 dynamic FK detection over *plans*.

    Intended to run after doc_discovery._detect_fk_links; *already_linked*
    should be the set of (source_type, target_type) pairs those column-name
    passes already resolved, so this stage only fills the gap they miss —
    it never duplicates or overrides an already-found relationship.
    """
    settings = get_settings()
    if not settings.fk_dynamic_detection_enabled or len(plans) < 2:
        return []
    t0 = time.monotonic()
    candidates = generate_candidate_pairs(plans, already_linked=already_linked, log_id=log_id)
    t1 = time.monotonic()
    links = judge_candidates_with_llm(candidates, broker, log_id=log_id)
    t2 = time.monotonic()
    logger.info(
        "ingest_timing log_id=%s stage=dynamic_fk plans=%d candidates=%d "
        "links_found=%d value_sample_ms=%d llm_judge_ms=%d",
        log_id, len(plans), len(candidates), len(links),
        int((t1 - t0) * 1000), int((t2 - t1) * 1000),
    )
    return links
