/**
 * Recent-LLM-calls table for the observability page.
 *
 * Split out of app/observability/page.tsx (2026-09; Raven Style
 * Compliance Plan Phase 8b line-count reduction).
 */

import { cn } from "@/lib/cn";
import type { ObservabilityData } from "@/lib/types";
import { fmt, fmtNum } from "./format";

export function LlmCallsTable({ calls }: { calls: ObservabilityData["llm_recent"] }) {
  return (
    <div>
      <h2 className="mb-3 text-[13px] font-bold uppercase tracking-[0.1em] text-navy-500">Recent LLM Calls</h2>
      <div className="overflow-hidden rounded-xl border border-navy-100 bg-white shadow-soft">
        {calls.length === 0 ? (
          <div className="py-8 text-center text-[13px] text-subtle">No LLM calls recorded yet</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-navy-50 bg-navy-50/60">
                  <th className="px-4 py-2.5 text-left font-semibold text-navy-700">Role</th>
                  <th className="px-4 py-2.5 text-left font-semibold text-navy-700">Model</th>
                  <th className="px-4 py-2.5 text-right font-semibold text-navy-700">Prompt tok</th>
                  <th className="px-4 py-2.5 text-right font-semibold text-navy-700">Completion tok</th>
                  <th className="px-4 py-2.5 text-right font-semibold text-navy-700">Latency</th>
                  <th className="px-4 py-2.5 text-left font-semibold text-navy-700">Source</th>
                  <th className="px-4 py-2.5 text-left font-semibold text-navy-700">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-navy-50">
                {calls.map((c, i) => (
                  <tr key={i} className="hover:bg-navy-50/40">
                    <td className="px-4 py-2.5">
                      <span className={cn(
                        "rounded-full px-2 py-0.5 text-[11px] font-semibold",
                        c.role === "ask" ? "bg-steel-50 text-steel-700" : "bg-navy-50 text-navy-700",
                      )}>{c.role}</span>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-[11px] text-navy-700">{c.model}</td>
                    <td className="px-4 py-2.5 text-right text-subtle">{fmtNum(c.prompt_tokens)}</td>
                    <td className="px-4 py-2.5 text-right text-subtle">{fmtNum(c.completion_tokens)}</td>
                    <td className="px-4 py-2.5 text-right text-subtle">{fmt(c.latency_ms)}</td>
                    <td className="px-4 py-2.5 text-subtle">{c.source}</td>
                    <td className="px-4 py-2.5 text-subtle">
                      {c.ts ? new Date(c.ts).toLocaleTimeString() : "—"}
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
