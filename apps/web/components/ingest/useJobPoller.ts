"use client";

import { useEffect, useRef, useState } from "react";
import { api, isHttpStatusError } from "@/lib/api";

const POLL_MS = 1_500;

/** Poll /admin/jobs/{jobId} every 1.5s until it reaches a terminal state.
 *  Mirrors the resilience pattern in components/start/Running.tsx exactly:
 *  re-poll immediately on tab visibility change (setTimeout is throttled in
 *  background tabs) and treat a 404 (job aged out / never existed) as a
 *  terminal failure instead of retrying forever. */
export function useJobPoller(
  jobId: string | null,
  onDone: (ok: boolean) => void,
): { stage: string | null; pct: number | null } {
  const [stage, setStage] = useState<string | null>(null);
  const [pct, setPct] = useState<number | null>(null);

  // Keep the latest onDone without re-running the polling effect on every
  // render (callers typically pass an inline closure).
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    if (!jobId) {
      setStage(null);
      setPct(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      try {
        const j = await api.getJob(jobId);
        if (cancelled) return;
        setStage(j.stage);
        setPct(j.pct ?? null);
        if (j.status === "complete") {
          onDoneRef.current(true);
          return;
        }
        if (j.status === "failed" || j.status === "cancelled") {
          onDoneRef.current(false);
          return;
        }
        timer = setTimeout(tick, POLL_MS);
      } catch (err) {
        if (cancelled) return;
        if (isHttpStatusError(err, 404)) {
          // Permanently gone — retrying forever just spins.
          onDoneRef.current(false);
          return;
        }
        // Transient (network blip, 5xx) — keep trying.
        timer = setTimeout(tick, POLL_MS);
      }
    };

    const onVisible = () => {
      if (document.visibilityState === "visible" && !cancelled) {
        if (timer) { clearTimeout(timer); timer = null; }
        tick();
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [jobId]);

  return { stage, pct };
}
