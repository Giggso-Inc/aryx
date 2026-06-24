"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity, AlertCircle, CheckCircle2, Clock, Database, RefreshCw,
  Zap, BarChart3, Cpu, Layers,
} from "lucide-react";
import { Header } from "@/components/brand/Header";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import { cn } from "@/lib/cn";
import type { ObservabilityData } from "@/lib/types";

function Metric({
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

function StatusDot({ status }: { status: string }) {
  const s = status?.toLowerCase();
  if (s === "complete") return <span className="inline-block size-2 rounded-full bg-emerald-500" />;
  if (s === "running") return <span className="inline-block size-2 rounded-full bg-blue-500 animate-pulse" />;
  if (s === "failed") return <span className="inline-block size-2 rounded-full bg-rose-500" />;
  return <span className="inline-block size-2 rounded-full bg-amber-400" />;
}

function fmt(ms?: number) {
  if (!ms) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtNum(n?: number) {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export default function ObservabilityPage() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  const [data, setData] = useState<ObservabilityData | null>(null);
  const [jobs, setJobs] = useState<Array<{
    job_id: string; source_system: string; source_dataset: string;
    status: string; stage: string | null; pct: number | null;
    error: string | null; started_at?: string;
  }>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [obs, jobList] = await Promise.all([
        api.getObservability(workspaceId),
        api.listJobs(workspaceId),
      ]);
      setData(obs);
      setJobs(jobList);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [workspaceId]);

  useEffect(() => { setLoading(true); load(); }, [load]);

  const refresh = () => { setRefreshing(true); load(); };

  const mc = data?.model_config as Record<string, string> | undefined;

  return (
    <div className="flex min-h-screen flex-col">
      <Header workspaceId={workspaceId} onWorkspaceChange={setWorkspaceId} />

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="font-display text-2xl font-bold text-navy-900">Observability</h1>
            <p className="mt-0.5 text-[13px] text-subtle">Pipeline health, LLM usage &amp; graph stats</p>
          </div>
          <button
            type="button"
            onClick={refresh}
            disabled={refreshing}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-100 bg-white px-3 py-1.5 text-[13px] font-medium text-navy-700 hover:bg-navy-50 disabled:opacity-50"
          >
            <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>

        {error && (
          <div className="mb-6 flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-[13px] text-rose-700">
            <AlertCircle size={14} className="shrink-0" />
            {error}
          </div>
        )}

        {loading && !data ? (
          <div className="flex h-40 items-center justify-center text-[13px] text-subtle">
            Loading…
          </div>
        ) : data && (
          <>
            {/* Metric cards */}
            <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Metric icon={<Database size={16} />} label="Entities" value={fmtNum(data.graph.entities)} color="navy" />
              <Metric icon={<Layers size={16} />} label="Relationships" value={fmtNum(data.graph.relationships)} color="steel" />
              <Metric icon={<Activity size={16} />} label="Jobs Total" value={fmtNum(data.jobs.total)} color="navy" />
              <Metric icon={<AlertCircle size={16} />} label="Failed Jobs"
                value={fmtNum(data.jobs.failed ?? 0)}
                color={(data.jobs.failed ?? 0) > 0 ? "red" : "green"}
              />
            </div>
            <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Metric icon={<Zap size={16} />} label="LLM Calls" value={fmtNum(data.llm.total_calls)} color="amber" />
              <Metric icon={<BarChart3 size={16} />} label="Total Tokens" value={fmtNum(data.llm.total_tokens)} color="amber" />
              <Metric icon={<Clock size={16} />} label="Avg Latency" value={fmt(data.llm.avg_latency_ms)} color="steel" />
              <Metric icon={<Cpu size={16} />} label="Model" value={mc?.menial_model || mc?.model || "—"} sub={mc?.provider} color="navy" />
            </div>

            {/* Jobs table */}
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

            {/* LLM call log */}
            <div>
              <h2 className="mb-3 text-[13px] font-bold uppercase tracking-[0.1em] text-navy-500">Recent LLM Calls</h2>
              <div className="overflow-hidden rounded-xl border border-navy-100 bg-white shadow-soft">
                {data.llm_recent.length === 0 ? (
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
                        {data.llm_recent.map((c, i) => (
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

            {/* Model config row */}
            {mc && Object.keys(mc).length > 0 && (
              <div className="mt-6 rounded-xl border border-navy-100 bg-navy-50/40 px-5 py-4">
                <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-navy-500">
                  Active Model Configuration
                </div>
                <div className="flex flex-wrap gap-3">
                  {Object.entries(mc).map(([k, v]) => (
                    <div key={k} className="text-[12px]">
                      <span className="text-subtle">{k}: </span>
                      <span className="font-medium text-navy-800">{String(v)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
