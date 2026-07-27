"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

export function useJobPoller(jobId: string | null, onDone: (ok: boolean) => void) {
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
        const j = await api.getJob(jobId);
        if (dead) return;
        setStage(j.stage);
        setPct(j.pct);
        if (j.status === "complete") { onDoneRef.current(true); return; }
        if (j.status === "failed") { onDoneRef.current(false); return; }
      } catch { /* ignore transient network errors */ }
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
  }, [jobId]); // onDone intentionally excluded — kept current via ref to avoid poll restart

  return { stage, pct };
}
