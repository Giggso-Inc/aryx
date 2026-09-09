/**
 * Pipeline-jobs table for the observability page.
 *
 * Split out of app/observability/page.tsx (2026-09; Raven Style
 * Compliance Plan Phase 8b line-count reduction).
 */

import { StatusDot } from "./StatusDot";

export type ObservabilityJob = {
  job_id: string; source_system: string; source_dataset: string;
  status: string; stage: string | null; pct: number | null;
  error: string | null; started_at?: string;
};

export function JobsTable({ jobs }: { jobs: ObservabilityJob[] }) {
  return (
    <div className="mb-8">
      <h2 className="mb-3 text-[13px] font-bold uppercase tracking-[0.1em] text-navy-500">Pipeline Jobs</h2>
      <div className="overflow-hidden rounded-xl border border-navy-100 bg-white shadow-soft">
        {jobs.length === 0 ? (
          <div className="py-8 text-center text-[13px] text-subtle">No jobs yet</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-navy-50 bg-navy-50/60">
                  <th className="px-4 py-2.5 text-left font-semibold text-navy-700">Source</th>
                  <th className="px-4 py-2.5 text-left font-semibold text-navy-700">Dataset</th>
                  <th className="px-4 py-2.5 text-left font-semibold text-navy-700">Status</th>
                  <th className="px-4 py-2.5 text-left font-semibold text-navy-700">Stage</th>
                  <th className="px-4 py-2.5 text-right font-semibold text-navy-700">Pct</th>
                  <th className="px-4 py-2.5 text-left font-semibold text-navy-700">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-navy-50">
                {jobs.slice(0, 50).map((j) => (
                  <tr key={j.job_id} className="hover:bg-navy-50/40">
                    <td className="px-4 py-2.5 text-navy-700">{j.source_system}</td>
                    <td className="px-4 py-2.5 text-navy-700 max-w-[160px] truncate">{j.source_dataset}</td>
                    <td className="px-4 py-2.5">
                      <span className="inline-flex items-center gap-1.5">
                        <StatusDot status={j.status} />
                        <span className="capitalize text-navy-700">{j.status}</span>
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-subtle">{j.stage || "—"}</td>
                    <td className="px-4 py-2.5 text-right text-subtle">
                      {j.pct != null ? `${j.pct}%` : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-subtle">
                      {j.started_at ? new Date(j.started_at).toLocaleTimeString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
