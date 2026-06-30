"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight, Database, MessageCircle, Network, Upload, Zap,
} from "lucide-react";
import { Header } from "@/components/brand/Header";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import { useWorkspaceAwareHref } from "@/lib/workspace-route";

interface Stats {
  entities: number;
  relationships: number;
  types: number;
  ingest_runs: number;
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft">
      <div className="text-[2rem] font-bold text-navy-900">{value}</div>
      <div className="mt-1 text-[12px] text-subtle">{label}</div>
    </div>
  );
}

const STEPS = [
  {
    num: 1,
    title: "Ingest",
    href: "/ingest",
    icon: <Upload size={18} />,
    body: "Drop files or connect a database. Aryx reads the rows, resolves duplicates, and writes entities into the knowledge graph.",
  },
  {
    num: 2,
    title: "Ask",
    href: "/",
    icon: <MessageCircle size={18} />,
    body: "Type a company, ticket, or keyword. Aryx traverses the graph and shows every connected entity, relationships, and provenance.",
  },
  {
    num: 3,
    title: "Graph",
    href: "/graph",
    icon: <Network size={18} />,
    body: "See the whole picture as an interactive canvas. Filter by type, follow relationships, and click any node to explore neighbours.",
  },
];

export default function HomePage() {
  const { workspaceId, workspaces } = useWorkspace();
  const [stats, setStats] = useState<Stats | null>(null);
  const active = workspaces.find((w) => w.id === workspaceId) || workspaces[0];
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
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-10">

        {/* Hero */}
        <div className="mb-10 rounded-2xl bg-navy-900 px-8 py-10 text-white">
          <div className="flex items-center gap-2 mb-3">
            <Zap size={18} className="text-steel-300" />
            <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-steel-300">
              {active?.name ?? "Default"} workspace
            </span>
          </div>
          <h1 className="font-display text-[2.2rem] font-bold leading-tight">
            A Fortress of Structured Knowledge
          </h1>
          <p className="mt-3 max-w-xl text-[15px] text-navy-200">
            Turn messy enterprise data into a single knowledge graph you can query
            in plain English and explore visually.
          </p>
          <div className="mt-6 flex gap-3">
            <Link
              href={askHref}
              className="inline-flex items-center gap-1.5 rounded-lg bg-white px-4 py-2 text-[13px] font-semibold text-navy-900 hover:bg-navy-50"
            >
              <MessageCircle size={14} /> Ask a question
            </Link>
            <Link
              href={ingestHref}
              className="inline-flex items-center gap-1.5 rounded-lg border border-navy-600 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-800"
            >
              <Upload size={14} /> Ingest data
            </Link>
          </div>
        </div>

        {/* Stats */}
        {stats !== null && (
          <div className="mb-10 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Entities" value={stats.entities} />
            <StatCard label="Entity types" value={stats.types} />
            <StatCard label="Ingest runs" value={stats.ingest_runs} />
            <StatCard label="Workspace" value={active?.name ?? "—"} />
          </div>
        )}

        {/* Steps */}
        <div className="mb-4">
          <h2 className="font-display text-[1.3rem] font-bold text-navy-900">
            How to use Aryx
          </h2>
          <p className="mt-1 text-[13px] text-subtle">
            Use the nav above to move through Ingest → Ask → Graph in order.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {STEPS.map((s) => (
            <Link
              key={s.num}
              href={s.title === "Ingest" ? ingestHref : s.title === "Ask" ? askHref : graphHref}
              className="group rounded-xl border border-navy-100 bg-white p-5 shadow-soft transition-shadow hover:shadow-md"
            >
              <div className="mb-3 flex items-center gap-2">
                <span className="flex size-7 items-center justify-center rounded-full bg-navy-100 text-[12px] font-bold text-navy-700">
                  {s.num}
                </span>
                <span className="text-[13px] font-semibold text-navy-800">
                  {s.icon && (
                    <span className="mr-1 inline-block align-text-bottom text-navy-600">
                      {s.icon}
                    </span>
                  )}
                  {s.title}
                </span>
              </div>
              <p className="text-[12px] text-subtle">{s.body}</p>
              <div className="mt-3 flex items-center gap-1 text-[11px] font-medium text-steel-600 opacity-0 transition-opacity group-hover:opacity-100">
                Go <ArrowRight size={11} />
              </div>
            </Link>
          ))}
        </div>

        {/* Brief callout */}
        <div className="mt-8 flex items-start gap-4 rounded-xl border border-steel-200 bg-steel-50 p-5">
          <Database size={20} className="mt-0.5 shrink-0 text-steel-600" />
          <div>
            <h3 className="text-[13px] font-semibold text-navy-900">
              Ground your workspace with a Brief
            </h3>
            <p className="mt-1 text-[12px] text-subtle">
              A brief tells Aryx what domain, aim, and entity types matter most —
              improving extraction quality significantly.
            </p>
            <Link
              href={briefHref}
              className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-steel-600 hover:text-steel-800"
            >
              Edit brief <ArrowRight size={11} />
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
