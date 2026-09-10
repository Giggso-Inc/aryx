/**
 * Top-of-page metric cards + active-model-config row for the observability page.
 *
 * Split out of app/observability/page.tsx (2026-09; Raven Style
 * Compliance Plan Phase 8b line-count reduction).
 */

import { Activity, AlertCircle, BarChart3, Clock, Cpu, Database, Layers, Zap } from "lucide-react";
import type { ObservabilityData } from "@/lib/types";
import { Metric } from "./Metric";
import { fmt, fmtNum } from "./format";

export function MetricsGrid({ data }: { data: ObservabilityData }) {
  const mc = data.model_config as Record<string, string> | undefined;

  return (
    <>
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
        <Metric icon={<Cpu size={16} />} label="Reason Model" value={mc?.answer_model || mc?.model || "—"} sub={mc?.provider} color="navy" />
      </div>
    </>
  );
}

export function ModelConfigRow({ data }: { data: ObservabilityData }) {
  const mc = data.model_config as Record<string, string> | undefined;
  if (!mc || Object.keys(mc).length === 0) return null;

  return (
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
  );
}
