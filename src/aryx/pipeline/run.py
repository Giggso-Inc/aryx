"""Batch runner wiring extract -> clean -> profile (stages 1-3).

Streams records one at a time: a record is cleaned, handed to an optional
sink, folded into the profile, then released. Nothing holds the full dataset,
so the same code path that serves a small table also survives a terabyte
(slower, not crashing). Parallel partitioned workers are deferred machinery.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from aryx.connectors.base import Connector
from aryx.models import CleanRecord, FieldProfile
from aryx.raven_log import raven_log
from aryx.pipeline.clean import clean
from aryx.pipeline.profile import ProfileAccumulator

logger = logging.getLogger(__name__)

# A sink persists each cleaned record (e.g. to the RDB landing zone). The
# concrete batch-writing sink arrives in Increment 2; None means profile-only.
RecordSink = Callable[[CleanRecord], None]
Progress = Callable[[str, int, str], None]


def run_spine(
    connector: Connector,
    sink: RecordSink | None = None,
    log_every: int = 10_000,
    on_progress: Progress | None = None,
) -> list[FieldProfile]:
    """Stream a source through clean + profile without materializing it.

    Args:
        connector: A configured source connector.
        sink: Optional callback to persist each cleaned record.
        log_every: Emit a progress line every N records.
        on_progress: Optional callback (stage, pct, detail), fired at the
            same cadence as the "spine progress" log line below (PR
            review, 2026-10-04: landing a large tag -- e.g. 439,946
            records at ~35 min live -- previously reported nothing to the
            caller's job-status row between "Discover 8%" and "Discover
            15%", the entire extract+land phase. Combined with §0's
            heartbeat-sweep watchdog, that silence was long enough to get
            a perfectly healthy job killed. pct is indeterminate (held at
            10, between discover()'s own 8/15 bookends) since total
            record count isn't known while streaming -- this is a
            liveness heartbeat, not real completion progress, same
            convention as resolve_chunked()'s on_progress in chunked.py).

    Returns:
        Per-field profiles for the extracted batch.
    """
    accumulator = ProfileAccumulator()
    count = 0
    keys_in = keys_out = 0
    _t0 = time.monotonic()
    for raw in connector.extract():
        record = clean(raw)
        keys_in += len(getattr(raw, "payload", None) or ())
        keys_out += len(getattr(record, "payload", None) or ())
        accumulator.add(record)
        if sink is not None:
            sink(record)
        count += 1
        if count % log_every == 0:
            logger.info("spine progress records=%d", count)
            raven_log("DEBUG", "P4", "ingest.spine.progress spine progress checkpoint",
                      context={"stage": "spine", "records": count, "log_every": log_every,
                               "keys_dropped_by_clean": keys_in - keys_out,
                               "duration_ms": int((time.monotonic() - _t0) * 1000)})
            if on_progress is not None:
                on_progress("Discover", 10, f"{count} records extracted")
    logger.info("spine complete records=%d", count)
    raven_log("DEBUG", "P4", "ingest.spine.complete spine finished",
              context={"stage": "spine", "records": count, "keys_in": keys_in, "keys_out": keys_out,
                       "keys_dropped_by_clean": keys_in - keys_out, "has_sink": sink is not None,
                       "selected_option": "land_and_profile" if sink is not None else "profile_only",
                       "available_options": ["land_and_profile", "profile_only"],
                       "reason_code": "SINK_SUPPLIED" if sink is not None else "NO_SINK",
                       "duration_ms": int((time.monotonic() - _t0) * 1000)})
    return accumulator.result()
