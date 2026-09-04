import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { POLL_MS } from "./types";

export function EventLog({ jobId, live }: { jobId: string; live: boolean }) {
  const [events, setEvents] = useState<{
    stage: string; pct: number; detail: string; ts: string;
  }[]>([]);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    try { setEvents(await api.getJobEvents(jobId)); }
    catch { setEvents([]); }
    finally { setLoading(false); }
  }, [jobId]);
  useEffect(() => {
    refresh();
    if (!live) return;
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [refresh, live]);

  return (
    <div className="border-t border-navy-100 bg-navy-50/40 px-4 py-3">
      <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-subtle">
        Event log {live && "· live"}
      </div>
      {loading && events.length === 0 ? (
        <div className="text-[11px] italic text-subtle">Loading…</div>
      ) : events.length === 0 ? (
        <div className="text-[11px] italic text-subtle">
          No events yet — pipeline hasn't reported in.
        </div>
      ) : (
        <ol className="space-y-1.5 font-mono text-[10.5px] leading-snug text-navy-700">
          {events.map((e, i) => (
            <li key={i} className="flex items-start gap-2">
              <span className="shrink-0 text-subtle">
                {new Date(e.ts).toLocaleTimeString([], {
                  hour: "2-digit", minute: "2-digit", second: "2-digit",
                })}
              </span>
              <span className="shrink-0 font-semibold text-steel-600">
                {e.stage}
              </span>
              <span className="shrink-0 text-navy-500">{e.pct}%</span>
              <span className="truncate text-navy-700">{e.detail}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
