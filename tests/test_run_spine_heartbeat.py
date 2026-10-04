"""run_spine()'s on_progress heartbeat -- PR review follow-up, 2026-10-04.

Landing a large tag (e.g. 439,946 records at ~35 min live) previously
reported nothing to the caller's job-status row between discover()'s own
"Discover 8%" and "Discover 15%" bookends -- the ENTIRE extract+land
phase. Combined with §0's heartbeat-sweep watchdog
(JobStore.sweep_stale_heartbeat), that silence was long enough to get a
perfectly healthy job killed (make_should_stop() now also stops on
'failed', so the next should_stop() check after a sweep raises
PipelineCancelled and PR #429's cleanup deletes the partial entities).
"""
from __future__ import annotations

from aryx.models import RawRecord, SourceRef
from aryx.pipeline.run import run_spine


class _FakeConnector:
    def __init__(self, n: int) -> None:
        self._n = n

    def extract(self):
        for i in range(self._n):
            yield RawRecord(
                source=SourceRef(system="test", dataset="fake", record_id=str(i)),
                payload={"id": i},
            )


def test_on_progress_fires_at_the_same_cadence_as_log_every():
    calls = []
    run_spine(_FakeConnector(25), log_every=10,
             on_progress=lambda stage, pct, detail: calls.append((stage, pct, detail)))

    assert len(calls) == 2  # fires at 10 and 20, not at 25 (never hits 30)
    for stage, pct, detail in calls:
        assert stage == "Discover"
        assert isinstance(pct, int)


def test_on_progress_never_called_when_record_count_is_below_log_every():
    calls = []
    run_spine(_FakeConnector(5), log_every=10,
             on_progress=lambda *a: calls.append(a))

    assert calls == []


def test_on_progress_none_is_the_default_and_never_raises():
    """Every pre-existing caller that doesn't pass on_progress must keep
    working unchanged."""
    profiles = run_spine(_FakeConnector(25), log_every=10)
    assert profiles is not None  # ran to completion, no exception


def test_on_progress_detail_includes_the_running_record_count():
    calls = []
    run_spine(_FakeConnector(20), log_every=10,
             on_progress=lambda stage, pct, detail: calls.append(detail))

    assert calls[0] == "10 records extracted"
    assert calls[1] == "20 records extracted"
