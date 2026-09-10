/**
 * Single stat-card component for the observability page.
 *
 * Split out of app/observability/page.tsx (2026-09; Raven Style
 * Compliance Plan Phase 8b line-count reduction).
 */

import { cn } from "@/lib/cn";

export function Metric({
  icon, label, value, sub, color = "navy",
}: {
  icon: React.ReactNode; label: string; value: string | number;
  sub?: string; color?: "navy" | "green" | "red" | "amber" | "steel";
}) {
  const ring = {
    navy: "bg-navy-50 text-navy-600",
    green: "bg-emerald-50 text-emerald-600",
    red: "bg-rose-50 text-rose-600",
    amber: "bg-amber-50 text-amber-600",
    steel: "bg-steel-50 text-steel-600",
  }[color];
  return (
    <div className="rounded-xl border border-navy-100 bg-white p-4 shadow-soft">
      <div className={cn("mb-3 inline-flex size-9 items-center justify-center rounded-lg", ring)}>
        {icon}
      </div>
      <div className="text-2xl font-bold text-navy-900">{value}</div>
      <div className="mt-0.5 text-[13px] font-medium text-navy-700">{label}</div>
      {sub && <div className="mt-0.5 text-[11px] text-subtle">{sub}</div>}
    </div>
  );
}
