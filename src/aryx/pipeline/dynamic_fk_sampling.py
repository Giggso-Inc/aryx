"""Value-sampling and overlap-scoring primitives for dynamic FK detection —
pure functions with no config/LLM dependency, so they can be tested and
reused without any settings or broker mocking.

Split out of `pipeline/dynamic_fk.py` (Raven Style Compliance Plan, Phase
2a, 2026-09-03).
"""
from __future__ import annotations

import csv
import io
from collections import Counter

from aryx.pipeline.value_normalize import normalize_value


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


def _truncate_counts(counts: Counter[str], length: int) -> Counter[str]:
    out: Counter[str] = Counter()
    for v, c in counts.items():
        out[v[:length]] += c
    return out


def estimate_join_fanout(
    data_a: bytes, headers_a: list[str], col_a: str,
    data_b: bytes, headers_b: list[str], col_b: str,
    max_rows: int,
    prefix_len_a: int | None = None,
    prefix_len_b: int | None = None,
) -> int:
    """Estimate how many relationship rows joining col_a to col_b would
    produce: for every value shared by both sides, its occurrence count on
    side A times its occurrence count on side B, summed.

    This is what actually distinguishes a real (near-unique) join key from a
    shared low-cardinality category code: a category shared by hundreds of
    rows on each side multiplies into a huge number of pairs even though its
    *distinct*-value overlap ratio looks perfectly reasonable.

    prefix_len_a/prefix_len_b apply the same prefix truncation used to find
    a derived-relationship candidate (see try_prefix_transforms) before
    counting — truncation only ever MERGES groups (never splits them), so
    fanout must be estimated on the actual values being joined, not the
    untransformed originals, or a derived join's real fan-out risk would be
    underestimated.
    """
    counts_a = sample_value_counts(data_a, headers_a, col_a, max_rows)
    counts_b = sample_value_counts(data_b, headers_b, col_b, max_rows)
    if prefix_len_a is not None:
        counts_a = _truncate_counts(counts_a, prefix_len_a)
    if prefix_len_b is not None:
        counts_b = _truncate_counts(counts_b, prefix_len_b)
    return sum(counts_a[v] * counts_b[v] for v in counts_a.keys() & counts_b.keys())


def try_prefix_transforms(
    values_a: set[str], values_b: set[str], lengths: list[int],
) -> tuple[float, int | None, int | None, set[str], set[str]] | None:
    """Fallback when raw values don't overlap enough: try truncating each
    side to a small set of configured lengths, compared against the OTHER
    side's raw values — catches a derived/grouped relationship (e.g. a
    shorter code that is really a prefix of a longer one in another table)
    that no naming convention or literal value match can find. Generic: no
    column name or specific transform is hardcoded, only prefix lengths.

    Returns (best_ratio, prefix_len_a, prefix_len_b, values_a', values_b')
    for the best-scoring transform tried, or None if no lengths configured.
    Exactly one of prefix_len_a/prefix_len_b is set (whichever side was
    truncated); the other is None.
    """
    best: tuple[float, int | None, int | None, set[str], set[str]] | None = None
    for length in lengths:
        trunc_a = {v[:length] for v in values_a}
        ratio_a = value_overlap_ratio(trunc_a, values_b)
        if best is None or ratio_a > best[0]:
            best = (ratio_a, length, None, trunc_a, values_b)
        trunc_b = {v[:length] for v in values_b}
        ratio_b = value_overlap_ratio(values_a, trunc_b)
        if best is None or ratio_b > best[0]:
            best = (ratio_b, None, length, values_a, trunc_b)
    return best


def _candidate_columns(headers: list[str]) -> list[str]:
    """Every header is a candidate — no hardcoded name allow-list.

    Only aryx-internal bookkeeping columns (leading underscore, e.g.
    _element_type) are excluded.
    """
    return [h for h in headers if h and not h.startswith("_")]
