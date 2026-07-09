"""G10: band routing, queue offers, apply_decision merge/reject."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.models import ResolutionRecord
from aryx.resolution.cluster import UnionFind
from aryx.resolution.review_queue import apply_decision
from aryx.resolution.run import _route_pair


class FakeSink:
    """Collects offered pairs for assertions."""

    def __init__(self) -> None:
        self.offers: list[dict] = []

    def offer(self, left, right, score, llm_verdict, llm_reason,
              status) -> None:
        self.offers.append({"left": left.record_id, "right": right.record_id,
                            "score": score, "llm_verdict": llm_verdict,
                            "status": status})


def _pair() -> tuple[ResolutionRecord, ResolutionRecord, UnionFind]:
    left = ResolutionRecord(record_id=1, text="a", payload={})
    right = ResolutionRecord(record_id=2, text="b", payload={})
    union = UnionFind()
    union.add(1)
    union.add(2)
    return left, right, union


def _merged(union: UnionFind) -> bool:
    return union.find(1) == union.find(2)


def test_above_auto_merge_merges_without_queue() -> None:
    """score >= 0.92 -> merge, nothing queued."""
    left, right, union = _pair()
    sink = FakeSink()
    decision = _route_pair(left, right, 0.95, MagicMock(), union, sink)
    assert _merged(union) and sink.offers == []
    assert decision == "merge"


def test_band_llm_accept_merges_and_logs_auto_llm() -> None:
    """[0.90, 0.92) with LLM yes -> merge + auto_llm labeled row."""
    left, right, union = _pair()
    sink = FakeSink()
    with patch("aryx.resolution.run.adjudicate", return_value=True):
        decision = _route_pair(left, right, 0.91, MagicMock(), union, sink)
    assert _merged(union)
    assert sink.offers[0]["status"] == "auto_llm"
    assert sink.offers[0]["llm_verdict"] is True
    assert decision == "adjudicate_merge"


def test_band_llm_failure_queues_pending_no_merge() -> None:
    """LLM down -> fail-to-human: pending row, conservative non-merge."""
    left, right, union = _pair()
    sink = FakeSink()
    with patch("aryx.resolution.run.adjudicate",
               side_effect=RuntimeError("llm down")):
        decision = _route_pair(left, right, 0.91, MagicMock(), union, sink)
    assert not _merged(union)
    assert sink.offers[0]["status"] == "pending"
    assert decision == "adjudicate_no_merge"


def test_review_band_queues_pending() -> None:
    """[0.75, 0.90) -> human queue, treated as non-merge for this run."""
    left, right, union = _pair()
    sink = FakeSink()
    decision = _route_pair(left, right, 0.80, MagicMock(), union, sink)
    assert not _merged(union)
    assert sink.offers[0]["status"] == "pending"
    assert sink.offers[0]["llm_verdict"] is None
    assert decision == "review"


def test_below_review_rejected_silently() -> None:
    """score < 0.75 -> auto-reject: no merge, no queue row."""
    left, right, union = _pair()
    sink = FakeSink()
    decision = _route_pair(left, right, 0.60, MagicMock(), union, sink)
    assert not _merged(union) and sink.offers == []
    assert decision == "reject"


def test_no_sink_band_pair_skipped_quietly() -> None:
    """review=None (queue not wired) keeps the funnel working."""
    left, right, union = _pair()
    decision = _route_pair(left, right, 0.80, MagicMock(), union, None)
    assert not _merged(union)
    assert decision == "review_dropped"


def test_review_sink_failure_does_not_abort_run() -> None:
    """A review-queue write failure must not raise — pair is dropped, run continues."""
    class RaisingSink:
        def offer(self, *args, **kwargs) -> None:
            raise RuntimeError("db down")

    left, right, union = _pair()
    decision = _route_pair(left, right, 0.80, MagicMock(), union, RaisingSink())
    assert not _merged(union)
    assert decision == "review_dropped"


def test_run_id_threaded_into_route_pair_log(caplog) -> None:
    """run_id passed to _route_pair appears in its log line for correlation."""
    import logging
    left, right, union = _pair()
    sink = FakeSink()
    with caplog.at_level(logging.INFO, logger="aryx.resolution.run"):
        _route_pair(left, right, 0.95, MagicMock(), union, sink, run_id=42)
    assert any("run_id=42" in r.getMessage() for r in caplog.records)


def test_apply_decision_approve_merges_entities() -> None:
    """Human approval unions the two records' entities."""
    store = MagicMock()
    store.decide.return_value = {"id": 7, "left_record_id": 1,
                                 "right_record_id": 2}
    row = apply_decision(store, 7, approve=True, decided_by="ravi")
    store.decide.assert_called_once_with(7, True, "ravi")
    store.merge_entities_of.assert_called_once_with(1, 2)
    assert row["id"] == 7


def test_apply_decision_reject_leaves_separate() -> None:
    """Rejection records the label; entities stay separate."""
    store = MagicMock()
    store.decide.return_value = {"id": 8, "left_record_id": 1,
                                 "right_record_id": 2}
    apply_decision(store, 8, approve=False, decided_by="ravi")
    store.merge_entities_of.assert_not_called()
