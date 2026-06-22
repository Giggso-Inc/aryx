"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function useJobPoller(jobId: string | null, onDone: (ok: boolean) => void) {
  const [stage, setStage] = useState<string | null>(null);
  const [pct, setPct] = useState<number | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let dead = false;
    const tick = async () => {
      try {
        const j = await api.getJob(jobId);
        if (dead) return;
        setStage(j.stage);
        setPct(j.pct);
        if (j.status === "complete") { onDone(true); return; }
        if (j.status === "failed") { onDone(false); return; }
      } catch { /* ignore transient network errors */ }
      if (!dead) setTimeout(tick, 1500);
    };
    tick();
    return () => { dead = true; };
  }, [jobId, onDone]);

  return { stage, pct };
}
