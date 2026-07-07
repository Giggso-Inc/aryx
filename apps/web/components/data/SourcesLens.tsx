"use client";

import { useRouter } from "next/navigation";
import { useDeferredValue, useState } from "react";
import { Database, EllipsisVertical, Filter, Plus, Search, Trash2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { typeColor } from "@/lib/typeColor";
import type { DataSummary, Datasource } from "@/lib/types";
import { useWorkspaceAwareHref } from "@/lib/workspace-route";

type SourceFilter = "all" | "database" | "documents" | "api";
type SourceRow = {
  id: string;
  name: string;
  kind: string;
  ready: boolean;
  detail?: string;
  count?: number;
};

const FILTER_LABELS: Record<SourceFilter, string> = {
  all: "All",
  database: "Databases",
  documents: "Documents",
  api: "APIs",
};

export function SourcesLens({
  summary,
  datasources,
  loading,
  error,
}: {
  summary: DataSummary;
  datasources: Datasource[];
  loading: boolean;
  error: string | null;
}) {
  const router = useRouter();
  const ingestHref = useWorkspaceAwareHref("/ingest", "ingest");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<SourceFilter>("all");
  const [filterOpen, setFilterOpen] = useState(false);
  const deferredQuery = useDeferredValue(query);
  const rows = buildSourceRows(summary, datasources);
  const visible = rows.filter((source) => matchesQuery(source, filter, deferredQuery));

  return (
    <div className="space-y-5">
      <section className="rounded-[1.5rem] border border-navy-100 bg-white p-4 shadow-soft md:p-5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <p className="shrink-0 text-[11px] font-semibold uppercase tracking-[0.22em] text-subtle">
            All Data Sources
          </p>

          <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:items-center xl:justify-end">
            <label className="flex min-w-0 items-center gap-3 rounded-full border border-navy-100 bg-canvas px-4 py-3 text-sm text-subtle sm:w-full xl:w-[360px]">
              <Search size={16} className="shrink-0 text-navy-400" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search sources by name or ID..."
                className="w-full bg-transparent text-sm text-navy-900 outline-none placeholder:text-subtle"
              />
            </label>

            <div className="flex items-center gap-2">
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setFilterOpen((open) => !open)}
                  className="focus-ring inline-flex shrink-0 items-center gap-2 rounded-full border border-navy-100 bg-white px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle transition-colors hover:bg-navy-50"
                  aria-haspopup="menu"
                  aria-expanded={filterOpen}
                >
                  <Filter size={13} />
                  {filter === "all" ? "Filter" : FILTER_LABELS[filter]}
                </button>
                {filterOpen ? (
                  <div className="absolute right-0 z-20 mt-2 w-44 rounded-2xl border border-navy-100 bg-white p-1.5 shadow-soft">
                    {(["all", "database", "documents", "api"] as SourceFilter[]).map((item) => (
                      <button
                        key={item}
                        type="button"
                        onClick={() => {
                          setFilter(item);
                          setFilterOpen(false);
                        }}
                        className={cn(
                          "focus-ring flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm transition-colors",
                          filter === item
                            ? "bg-navy-800 text-white"
                            : "text-navy-700 hover:bg-navy-50",
                        )}
                      >
                        <span>{FILTER_LABELS[item]}</span>
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>

              <button
                type="button"
                onClick={() => router.push(ingestHref)}
                className="focus-ring inline-flex shrink-0 items-center gap-2 rounded-full bg-navy-800 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-navy-700"
              >
                <Plus size={15} />
                Connect source
              </button>
            </div>
          </div>
        </div>

        {error ? (
          <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        ) : null}

        {!error && loading ? (
          <div className="mt-4 rounded-2xl border border-dashed border-navy-100 bg-canvas px-4 py-10 text-center text-sm text-subtle">
            Reading data source registry...
          </div>
        ) : null}

        {!error && !loading && visible.length === 0 ? (
          <div className="mt-4 rounded-[1.25rem] border border-dashed border-navy-200 bg-canvas px-5 py-10 text-center">
            <div className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-white text-steel-500 shadow-soft">
              <Database size={24} />
            </div>
            <h3 className="mt-4 font-display text-2xl text-navy-900">No sources yet</h3>
            <p className="mx-auto mt-2 max-w-lg text-sm text-subtle">
              Start in Ingest to connect a database, documents, or a REST API.
              Once a source is registered, it will show up here first.
            </p>
          </div>
        ) : null}

        {!error && !loading && visible.length > 0 ? (
          <div className="mt-2">
            <div className="overflow-hidden rounded-[1.5rem] border border-navy-100 bg-white">
              <div className="hidden grid-cols-[minmax(0,1.6fr)_minmax(180px,0.9fr)_minmax(150px,0.8fr)_104px] gap-4 bg-navy-50 px-5 py-4 text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle lg:grid">
                <span>Source Name</span>
                <span>Type</span>
                <span>Status</span>
                <span className="text-right">Actions</span>
              </div>
              {visible.map((source) => (
                <article
                  key={source.id}
                  className="border-t border-navy-100 bg-white px-4 py-4 first:border-t-0 lg:grid lg:grid-cols-[minmax(0,1.6fr)_minmax(180px,0.9fr)_minmax(150px,0.8fr)_104px] lg:items-center lg:gap-4 lg:px-5"
                >
                  <div className="min-w-0">
                    <button
                      type="button"
                      onClick={() => router.push(ingestHref)}
                      className="block truncate text-left text-base font-semibold text-navy-900 underline-offset-4 transition-colors hover:text-steel-600 hover:underline"
                      title={source.name}
                    >
                      {source.name}
                    </button>
                  </div>

                  <div className="mt-3 lg:mt-0">
                    <span className="inline-flex rounded-full bg-navy-50 px-3 py-1 text-xs font-semibold text-navy-700">
                      {kindLabel(source.kind)}
                    </span>
                  </div>

                  <div className="mt-3 lg:mt-0">
                    <span
                      className={cn(
                        "inline-flex rounded-full px-3 py-1 text-xs font-semibold",
                        source.ready
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-amber-100 text-amber-700",
                      )}
                    >
                      {source.ready ? "Ready" : "Configured"}
                    </span>
                  </div>

                  <div className="mt-3 flex items-center gap-2 lg:mt-0 lg:justify-end">
                    <button
                      type="button"
                      aria-label={`Delete ${source.name}`}
                      className="focus-ring inline-flex size-9 items-center justify-center rounded-full text-subtle transition-colors hover:bg-navy-50 hover:text-navy-700"
                    >
                      <Trash2 size={16} />
                    </button>
                    <button
                      type="button"
                      aria-label={`More actions for ${source.name}`}
                      className="focus-ring inline-flex size-9 items-center justify-center rounded-full text-subtle transition-colors hover:bg-navy-50 hover:text-navy-700"
                    >
                      <EllipsisVertical size={16} />
                    </button>
                  </div>
                </article>
              ))}

              <div className="flex items-center justify-between border-t border-navy-100 bg-navy-50 px-5 py-4 text-xs text-subtle">
                <span>
                  Showing {visible.length} of {rows.length} data source
                  {rows.length === 1 ? "" : "s"}
                </span>
                <span>
                  {summary.source_records} source records feeding {summary.total_entities} resolved entities
                </span>
              </div>
            </div>
          </div>
        ) : null}
      </section>

      <section className="space-y-3">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-subtle">
              Entity Resolution Overview
            </p>
            <p className="mt-2 text-sm text-subtle">
              Summary of identified entities across all integrated sources.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <MetricCard value={summary.total_entities} label="Total Entities" />
            <MetricCard value={summary.type_count} label="Total Entity Types" />
          </div>
        </div>

        <div className="rounded-2xl border border-navy-100 bg-white p-4 shadow-soft">
          <h3 className="text-[10px] font-bold uppercase tracking-[0.13em] text-subtle">
            {summary.total_entities} entities · {summary.type_count} types
          </h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {summary.types.map((t, i) => (
              <div
                key={t.name}
                className="min-w-0 flex-1 rounded-xl px-3 py-2.5 text-white"
                style={{ background: typeColor(i), minWidth: 116 }}
                title={t.name}
              >
                <div className="font-display text-2xl leading-none">{t.count}</div>
                <div className="mt-1 truncate text-[11px] font-medium opacity-95">{t.name}</div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

function buildSourceRows(summary: DataSummary, datasources: Datasource[]): SourceRow[] {
  const rows = new Map<string, SourceRow>();
  for (const source of datasources) {
    rows.set(source.name.toLowerCase(), {
      id: String(source.id),
      name: source.name,
      kind: source.kind,
      ready: source.ready,
      detail: source.mask || undefined,
    });
  }
  for (const source of summary.sources) {
    const key = source.source.toLowerCase();
    if (rows.has(key)) {
      const current = rows.get(key)!;
      current.count = source.count;
      continue;
    }
    rows.set(key, {
      id: `summary:${source.source}`,
      name: source.source,
      kind: inferKind(source.source),
      ready: true,
      count: source.count,
    });
  }
  return Array.from(rows.values());
}

function matchesQuery(source: SourceRow, filter: SourceFilter, query: string) {
  if (filter === "database" && !isDatabase(source.kind)) return false;
  if (filter === "documents" && !isDocumentKind(source.kind, source.name)) return false;
  if (filter === "api" && !isApiKind(source.kind)) return false;

  const haystack = [
    source.name,
    source.kind,
    source.detail,
    source.id,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(query.trim().toLowerCase());
}

function isDatabase(kind: string) {
  return ["postgresql", "postgres", "mysql", "mariadb", "oracle", "sqlite", "csv"].includes(kind);
}

function isDocumentKind(kind: string, name: string) {
  return kind === "docs" || /\.(pdf|docx?|pptx?|rtf|txt|md|html?|xml)$/i.test(name);
}

function isApiKind(kind: string) {
  return kind === "rest" || kind === "api";
}

function kindLabel(kind: string) {
  switch (kind) {
    case "csv":
      return "Structured CSV";
    case "docs":
      return "Document";
    case "api":
    case "rest":
      return "REST API";
    case "postgres":
    case "postgresql":
    case "mysql":
    case "mariadb":
    case "oracle":
    case "sqlite":
      return "SQL Database";
    default:
      return kind.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  }
}

function inferKind(sourceName: string) {
  const lower = sourceName.toLowerCase();
  if (lower.startsWith("csv.") || lower.endsWith(".csv")) return "csv";
  if (lower.startsWith("api.") || lower.includes("rest")) return "api";
  if (lower.endsWith(".pdf") || lower.endsWith(".doc") || lower.endsWith(".docx") || lower.endsWith(".xml")) return "docs";
  return "postgresql";
}

function MetricCard({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-[1.25rem] border border-navy-100 bg-white px-5 py-3 text-right shadow-soft">
      <p className="text-3xl font-semibold text-steel-600">{value}</p>
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-subtle">
        {label}
      </p>
    </div>
  );
}
