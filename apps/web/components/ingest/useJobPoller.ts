"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { isHttpStatusError } from "@/lib/shay-session";

export function useJobPoller(
  jobId: string | null, onDone: (ok: boolean) => void, workspaceId?: number,
) {
  const [stage, setStage] = useState<string | null>(null);
  const [pct, setPct] = useState<number | null>(null);
  const onDoneRef = useRef(onDone);

  useEffect(() => { onDoneRef.current = onDone; }, [onDone]);

  useEffect(() => {
    if (!jobId) return;
    let dead = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      timer = null;
      try {
        // workspaceId: without it, GET /admin/jobs/{job_id} defaults to
        // workspace 1 server-side and 404s for a job in any other
        // workspace even while it's still running successfully -- the
        // caught 404 below then reports a false "failed" for a job that
        // actually completes moments later. Confirmed live on the
        // Documents-tab read flow (workspace 402): a real read job that
        // succeeded (tabular_plans=1) still surfaced "Read job failed".
        const j = await api.getJob(jobId, workspaceId);
        if (dead) return;
        setStage(j.stage);
        setPct(j.pct);
        if (j.status === "complete") { onDoneRef.current(true); return; }
        if (j.status === "failed") { onDoneRef.current(false); return; }
        // "cancelled" (POST /admin/jobs/{job_id}/cancel) is a third terminal
        // state -- without this branch the poller never recognizes it,
        // onDone() never fires, and the UI keeps polling + showing
        // "Ingesting..." forever for a job that will never change state again.
        if (j.status === "cancelled") { onDoneRef.current(false); return; }
      } catch (err) {
        // A 404 means the job is permanently gone (never existed, or aged
        // out of aryx_job's 30-day retention) — retrying forever here would
        // reintroduce the exact "stuck in Reading forever" bug this poller
        // exists to fix, just for a dead job instead of a live one. Every
        // other error (network blip, 5xx) is treated as transient and
        // retried, same as before.
        if (isHttpStatusError(err, 404)) {
          if (!dead) onDoneRef.current(false);
          return;
        }
      }
      if (!dead) timer = setTimeout(tick, 1500);
    };
    // A long-running job (extraction on a large document can run for hours)
    // can outlive a background browser tab's timer budget — most browsers
    // throttle or fully suspend setTimeout in tabs that aren't visible, which
    // silently stalls this poll loop with no error to catch. Re-polling
    // immediately on visibilitychange means returning to the tab catches the
    // job up right away instead of waiting on a timer that may not fire again
    // for a long time (or ever, if it was suspended rather than just slowed).
    const onVisible = () => {
      if (document.visibilityState === "visible" && !dead) {
        if (timer) { clearTimeout(timer); timer = null; }
        tick();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    tick();
    return () => {
      dead = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [jobId, workspaceId]); // onDone intentionally excluded — kept current via ref to avoid poll restart

  return { stage, pct };
}
