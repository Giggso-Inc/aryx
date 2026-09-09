/**
 * Job-status indicator dot for the observability page's jobs table.
 *
 * Split out of app/observability/page.tsx (2026-09; Raven Style
 * Compliance Plan Phase 8b line-count reduction).
 */

export function StatusDot({ status }: { status: string }) {
  const s = status?.toLowerCase();
  if (s === "complete") return <span className="inline-block size-2 rounded-full bg-emerald-500" />;
  if (s === "running") return <span className="inline-block size-2 rounded-full bg-blue-500 animate-pulse" />;
  if (s === "failed") return <span className="inline-block size-2 rounded-full bg-rose-500" />;
  return <span className="inline-block size-2 rounded-full bg-amber-400" />;
}
