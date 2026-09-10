"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import { Header } from "@/components/brand/Header";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import type { ObservabilityData } from "@/lib/types";
import { JobsTable, type ObservabilityJob } from "@/components/observability/JobsTable";
import { LlmCallsTable } from "@/components/observability/LlmCallsTable";
import { MetricsGrid, ModelConfigRow } from "@/components/observability/MetricsGrid";

export default function ObservabilityPage() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  const [data, setData] = useState<ObservabilityData | null>(null);
  const [jobs, setJobs] = useState<ObservabilityJob[]>([]);
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

  return (
    <div className="flex min-h-screen flex-col">
      <Header workspaceId={workspaceId} onWorkspaceChange={setWorkspaceId} />

      <div className="app-shell-offset flex-1">
        <main className="workspace-section-shell pb-6 pt-6">
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
              <MetricsGrid data={data} />
              <JobsTable jobs={jobs} />
              <LlmCallsTable calls={data.llm_recent} />
              <ModelConfigRow data={data} />
            </>
          )}
        </main>
      </div>
    </div>
  );
}
