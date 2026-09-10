"use client";

import { useEffect, useState } from "react";
import { Header } from "@/components/brand/Header";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import { useWorkspaceAwareHref } from "@/lib/workspace-route";
import { formatWorkspaceName } from "@/lib/workspace-name";
import { BriefCallout } from "./BriefCallout";
import { Hero } from "./Hero";
import { StatCard } from "./StatCard";
import { StepsGrid } from "./StepsGrid";

interface Stats {
  entities: number;
  relationships: number;
  types: number;
  ingest_runs: number;
}

export default function HomePage() {
  const { workspaceId, workspaces } = useWorkspace();
  const [stats, setStats] = useState<Stats | null>(null);
  const active = workspaces.find((w) => w.id === workspaceId) || workspaces[0];
  const activeWorkspaceName = formatWorkspaceName(active?.name);
  const workspaceBadge = activeWorkspaceName === "Workspace"
    ? activeWorkspaceName
    : `${activeWorkspaceName} workspace`;
  const askHref = useWorkspaceAwareHref("/", "ask");
  const ingestHref = useWorkspaceAwareHref("/ingest", "ingest");
  const graphHref = useWorkspaceAwareHref("/graph", "graph");
  const briefHref = useWorkspaceAwareHref("/brief", "brief");

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      api.getOntology(workspaceId),
      api.listJobs(workspaceId),
    ]).then(([ontRes, jobRes]) => {
      if (cancelled) return;
      const ont = ontRes.status === "fulfilled" ? ontRes.value : null;
      const jobs = jobRes.status === "fulfilled" ? jobRes.value : [];
      setStats({
        entities: ont?.entity_count ?? 0,
        types: ont?.types?.length ?? 0,
        relationships: 0,
        ingest_runs: Array.isArray(jobs) ? jobs.length : 0,
      });
    });
    return () => { cancelled = true; };
  }, [workspaceId]);

  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <div className="app-shell-offset flex-1">
        <main className="workspace-section-shell pb-6 pt-6">
          <Hero workspaceBadge={workspaceBadge} askHref={askHref} ingestHref={ingestHref} />

          {stats !== null && (
            <div className="mb-10 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatCard label="Entities" value={stats.entities} />
              <StatCard label="Entity types" value={stats.types} />
              <StatCard label="Ingest runs" value={stats.ingest_runs} />
              <StatCard label="Workspace" value={activeWorkspaceName} />
            </div>
          )}

          <StepsGrid ingestHref={ingestHref} askHref={askHref} graphHref={graphHref} />

          <BriefCallout briefHref={briefHref} />
        </main>
      </div>
    </div>
  );
}
