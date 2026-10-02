"""ingest_confirmed()'s FK-detection block must report real job progress.

Real incident (docs/falkordb_high_cpu_2026-07-29.md follow-up): a CSV-only
confirm (approved_files, no approved_types — so the mentions loop's own
jobs.update_stage() calls never run either) sat at its initial
jobs.create() values — status "queued", pct 0 — for the ENTIRE duration of
column-name FK detection, script data-flow analysis, workspace FK
detection, and dynamic (LLM-judged) FK detection, because none of those
steps called jobs.update_stage() at all. Live-confirmed: a 33-file SL3500e
batch sat "queued" in the job API for 9+ minutes of real, ongoing
dynamic-FK activity, indistinguishable from a hung/never-started job.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.pipeline.doc_discovery.doc_discovery import ingest_confirmed


def _csv_plan(filename: str, otype: str) -> dict:
    return {
        "filename": filename, "ontology_type": otype, "match_keys": ["id"],
        "data": b"id,name\n1,Widget\n2,Gadget\n",
    }


def _sticky_sequence(values: list[float]):
    """Like side_effect=values, but repeats the final value forever once
    exhausted instead of raising StopIteration. PR #416's should_stop()
    check (now called once per tabular plan, outside the mocked
    detect_dynamic_fk_links/run_pipeline this file scripts time.monotonic
    for) is an extra, unrelated caller of the same globally-patched
    time.monotonic -- a plain finite side_effect list sized only for this
    test's own on_progress candidates broke the moment anything else called
    it too."""
    it = iter(values)
    last = values[-1] if values else 0.0

    def _next(*_args, **_kwargs):
        nonlocal last
        try:
            last = next(it)
        except StopIteration:
            pass
        return last

    return _next


def _run(*, detect_dynamic_fk_links_impl=None, job_id="job-fk-progress", jobs=None,
          monotonic_values=None, progress_min_interval_s=2.0):
    data = {
        "mentions": [],
        "tabular": [_csv_plan("a.csv", "A"), _csv_plan("b.csv", "B")],
    }
    jobs = jobs if jobs is not None else MagicMock()
    dfk_kwargs = (
        {"side_effect": detect_dynamic_fk_links_impl}
        if detect_dynamic_fk_links_impl is not None
        else {"return_value": []}
    )
    monotonic_patch = (
        patch("aryx.pipeline.doc_discovery.doc_discovery.time.monotonic",
              side_effect=_sticky_sequence(monotonic_values))
        if monotonic_values is not None
        else patch("aryx.pipeline.doc_discovery.doc_discovery.time.monotonic",
                    return_value=0.0)
    )
    with patch("aryx.pipeline.doc_discovery.doc_discovery.get_settings") as mock_settings, \
         patch("aryx.pipeline.doc_discovery.doc_discovery.DatasourceStore", return_value=MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.run_pipeline"), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.OntologyStore", return_value=MagicMock()), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_fk_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_script_data_flow_links", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._detect_fk_links_workspace", return_value=[]), \
         patch("aryx.pipeline.doc_discovery.doc_discovery._persist_tabular_sources"), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.restore_generic_source_entry"), \
         patch("aryx.pipeline.doc_discovery.doc_discovery.detect_dynamic_fk_links", **dfk_kwargs), \
         monotonic_patch:
        settings_mock = MagicMock()
        settings_mock.rdb_dsn = "postgresql://x"
        settings_mock.graph_url = "redis://x"
        settings_mock.ingest_workers = 1
        settings_mock.ingest_relate = True
        settings_mock.fk_dynamic_progress_report_min_interval_s = progress_min_interval_s
        mock_settings.return_value = settings_mock
        ingest_confirmed(
            data, [], ["a.csv", "b.csv"], broker=MagicMock(),
            jobs=jobs, job_id=job_id, workspace_id=1,
        )
    return jobs


def test_update_stage_called_before_column_name_fk_detection():
    jobs = _run()
    stages = [c.args[1] for c in jobs.update_stage.call_args_list]
    assert "FK Detection" in stages, (
        "the FK-detection block must call jobs.update_stage() so the job "
        "leaves its initial 'queued' status — previously it called this "
        "nowhere, so a CSV-only confirm stayed 'queued' for the entire "
        "FK-detection phase regardless of how long it actually ran"
    )


def test_update_stage_calls_are_all_for_the_right_job_id():
    jobs = _run()
    assert jobs.update_stage.call_count > 0
    for c in jobs.update_stage.call_args_list:
        assert c.args[0] == "job-fk-progress"


def test_dynamic_fk_on_progress_reports_through_to_update_stage():
    """The slow, uncapped, per-candidate LLM-judge stage must report
    incremental progress — this is the actual long pole that looked
    identical to a hang without it (near-zero CPU, no log output for
    9+ minutes on a real batch). Calls spaced >= the throttle interval
    apart (see the throttle tests below for the 2026-09-23 Phase 2 fix)
    must all still reach update_stage — throttling must never suppress
    genuinely-spaced-out progress, only a rapid-fire burst."""
    def _fake_detect(plans, broker, already_linked=None, log_id=None, on_progress=None):
        if on_progress is not None:
            on_progress(1, 3)
            on_progress(2, 3)
            on_progress(3, 3)
        return []

    jobs = _run(detect_dynamic_fk_links_impl=_fake_detect,
                monotonic_values=[0.0, 3.0, 6.0], progress_min_interval_s=2.0)
    details = [c.args[3] for c in jobs.update_stage.call_args_list
               if c.args[1] == "FK Detection"]
    assert any("1/3" in d for d in details)
    assert any("2/3" in d for d in details)
    assert any("3/3" in d for d in details)


def test_dynamic_fk_progress_is_throttled_for_rapid_candidates():
    """2026-09-23 (Phase 2, docs/ingestion/SPARK_PARALLEL_MIGRATION_ANALYSIS_
    2026-09-23.md): live-measured, jobs.update_stage() (2 DB round-trips)
    called once per candidate became the dominant bottleneck once more
    workers made LLM judging itself faster than that write — 2186
    candidates at ~1.1s/write is ~40 minutes of pure sequential DB writes,
    regardless of worker count. Candidates arriving faster than the
    throttle interval must NOT each get their own update_stage call."""
    total = 10

    def _fake_detect(plans, broker, already_linked=None, log_id=None, on_progress=None):
        if on_progress is not None:
            for i in range(1, total + 1):
                on_progress(i, total)
        return []

    # All candidates arrive at the same instant (no real time passes
    # between them). The very first call always reports immediately (so
    # the stage visibly starts without waiting a full throttle interval),
    # candidates 2-9 collapse into nothing (same instant, throttled), and
    # the last (is_last) always reports regardless of timing.
    jobs = _run(detect_dynamic_fk_links_impl=_fake_detect,
                monotonic_values=[0.0] * total, progress_min_interval_s=2.0)
    details = [c.args[3] for c in jobs.update_stage.call_args_list
               if c.args[1] == "FK Detection"]
    dynamic_fk_details = [d for d in details if "Judging candidate" in d]
    assert dynamic_fk_details == [
        "Judging candidate foreign keys (1/10)…",
        f"Judging candidate foreign keys ({total}/{total})…",
    ], (
        "rapid-fire candidates sharing one instant must collapse to just "
        "the first (immediate) and last (always-reports) calls, not one "
        "update_stage call per candidate"
    )


def test_dynamic_fk_progress_final_candidate_always_reports():
    """The last candidate must always report regardless of throttle
    timing, so the stage ends at an accurate 100% rather than whatever
    percentage happened to be written last before throttling kicked in."""
    total = 5

    def _fake_detect(plans, broker, already_linked=None, log_id=None, on_progress=None):
        if on_progress is not None:
            for i in range(1, total + 1):
                on_progress(i, total)
        return []

    # Every candidate arrives well within the throttle window of the
    # previous one (0.1s apart, interval=2.0s) -- only candidate 1 (the
    # first, always-unthrottled call) and candidate 5 (is_last) should
    # reach update_stage.
    jobs = _run(detect_dynamic_fk_links_impl=_fake_detect,
                monotonic_values=[0.0, 0.1, 0.2, 0.3, 0.4], progress_min_interval_s=2.0)
    details = [c.args[3] for c in jobs.update_stage.call_args_list
               if c.args[1] == "FK Detection"]
    dynamic_fk_details = [d for d in details if "Judging candidate" in d]
    assert dynamic_fk_details == [
        "Judging candidate foreign keys (1/5)…",
        "Judging candidate foreign keys (5/5)…",
    ]


def test_dynamic_fk_progress_wiring_survives_a_failing_update_stage_call():
    """A job-store write failing mid-batch (e.g. a transient DB hiccup)
    must never abort FK detection or the rest of the confirm job — mirrors
    dynamic_fk.py's own on_progress guard (see test_dynamic_fk.py)."""
    def _fake_detect(plans, broker, already_linked=None, log_id=None, on_progress=None):
        if on_progress is not None:
            try:
                on_progress(1, 1)
            except Exception:  # noqa: BLE001
                pass
        return []

    # Fail only the 4th call (the FK-detection "scanning for dynamic FK"
    # stage report) — every other update_stage call in the full run
    # (including the later, unrelated per-file-processing ones) must keep
    # succeeding normally, proving this doesn't cascade.
    calls_seen = {"n": 0}

    def _flaky_update_stage(*args, **kwargs):
        calls_seen["n"] += 1
        if calls_seen["n"] == 4:
            raise RuntimeError("db down")

    flaky_jobs = MagicMock()
    flaky_jobs.update_stage.side_effect = _flaky_update_stage
    # Must not raise even though one update_stage call fails.
    _run(detect_dynamic_fk_links_impl=_fake_detect, job_id="job-fk-progress-2", jobs=flaky_jobs)
    assert calls_seen["n"] >= 4
