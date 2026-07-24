"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, Database, Filter, Plus, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/cn";
import type { DataSourceCatalogItem } from "@/lib/types";
import { useWorkspaceAwareHref } from "@/lib/workspace-route";
import { SourceCatalogRow } from "./SourceCatalogRow";

export type SourceFilter = "all" | "database" | "documents" | "api";
const FILTER_LABELS: Record<SourceFilter, string> = {
  all: "All", database: "Databases", documents: "Documents", api: "APIs",
};

type Props = {
  sources: DataSourceCatalogItem[]; total: number; page: number; pageSize: number;
  query: string; filter: SourceFilter; loading: boolean; error: string | null;
  busyKey: string | null; onQueryChange: (value: string) => void;
  onFilterChange: (value: SourceFilter) => void; onPageChange: (page: number) => void;
  onViewSource: (source: DataSourceCatalogItem) => void;
  onDownloadSource: (source: DataSourceCatalogItem) => void;
  onDeleteSource: (source: DataSourceCatalogItem) => void;
};

export function SourcesLens(props: Props) {
  const router = useRouter();
  const ingestHref = useWorkspaceAwareHref("/ingest", "ingest");
  const [filterOpen, setFilterOpen] = useState(false);
  const pages = Math.max(1, Math.ceil(props.total / props.pageSize));
  const start = props.total === 0 ? 0 : (props.page - 1) * props.pageSize + 1;
  const end = Math.min(props.page * props.pageSize, props.total);

  return <section className="rounded-[1.5rem] border border-navy-100 bg-white p-4 shadow-soft md:p-5">
    <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
      <p className="shrink-0 text-[11px] font-semibold uppercase tracking-[0.22em] text-subtle">All Data Sources</p>
      <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:items-center xl:justify-end">
        <label className="flex min-w-0 items-center gap-3 rounded-full border border-navy-100 bg-canvas px-4 py-3 text-sm text-subtle sm:w-full xl:w-[360px]">
          <Search size={16} className="shrink-0 text-navy-400" />
          <input value={props.query} onChange={(event) => props.onQueryChange(event.target.value)} placeholder="Search sources by name or type..." className="w-full bg-transparent text-sm text-navy-900 outline-none placeholder:text-subtle" />
        </label>
        <div className="flex items-center gap-2">
          <div className="relative">
            <button type="button" onClick={() => setFilterOpen((open) => !open)} aria-haspopup="menu" aria-expanded={filterOpen} className="focus-ring inline-flex items-center gap-2 rounded-full border border-navy-100 px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle hover:bg-navy-50"><Filter size={13} />{props.filter === "all" ? "Filter" : FILTER_LABELS[props.filter]}</button>
            {filterOpen ? <div className="absolute right-0 z-20 mt-2 w-44 rounded-2xl border border-navy-100 bg-white p-1.5 shadow-soft">{(Object.keys(FILTER_LABELS) as SourceFilter[]).map((item) => <button key={item} type="button" onClick={() => { props.onFilterChange(item); setFilterOpen(false); }} className={cn("focus-ring flex w-full rounded-xl px-3 py-2 text-left text-sm", props.filter === item ? "bg-navy-800 text-white" : "text-navy-700 hover:bg-navy-50")}>{FILTER_LABELS[item]}</button>)}</div> : null}
          </div>
          <button type="button" onClick={() => router.push(ingestHref)} className="focus-ring inline-flex items-center gap-2 rounded-full bg-navy-800 px-4 py-3 text-sm font-semibold text-white hover:bg-navy-700"><Plus size={15} />Connect source</button>
        </div>
      </div>
    </div>

    {props.error ? <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{props.error}</div> : null}
    {!props.error && props.loading ? <div className="mt-4 rounded-2xl border border-dashed border-navy-100 bg-canvas px-4 py-10 text-center text-sm text-subtle">Reading data source registry...</div> : null}
    {!props.error && !props.loading && props.sources.length === 0 ? <EmptyState filtered={Boolean(props.query || props.filter !== "all")} /> : null}
    {!props.error && !props.loading && props.sources.length ? <div className="mt-4 overflow-hidden rounded-[1.5rem] border border-navy-100">
      <div className="hidden grid-cols-[minmax(240px,1.5fr)_minmax(120px,.75fr)_95px_95px_90px_90px_100px_120px] gap-3 bg-navy-50 px-5 py-4 text-[10px] font-semibold uppercase tracking-[0.15em] text-subtle xl:grid"><span>Source Name</span><span>Type</span><span>Entities</span><span>Entity Types</span><span>Nodes</span><span>Edges</span><span>Status</span><span className="text-right">Actions</span></div>
      {props.sources.map((source) => <SourceCatalogRow key={source.source_key} source={source} busy={props.busyKey?.startsWith(`${source.source_key}:`) ?? false} onView={() => props.onViewSource(source)} onDownload={() => props.onDownloadSource(source)} onDelete={() => props.onDeleteSource(source)} />)}
      <div className="flex flex-col gap-3 border-t border-navy-100 bg-navy-50 px-5 py-4 text-xs text-subtle sm:flex-row sm:items-center sm:justify-between"><span>Showing {start.toLocaleString()}–{end.toLocaleString()} of {props.total.toLocaleString()} data sources</span><div className="flex items-center gap-2"><button aria-label="Previous sources page" disabled={props.page <= 1} onClick={() => props.onPageChange(props.page - 1)} className="focus-ring rounded-full p-2 disabled:opacity-30"><ChevronLeft size={16} /></button><span>Page {props.page} of {pages}</span><button aria-label="Next sources page" disabled={props.page >= pages} onClick={() => props.onPageChange(props.page + 1)} className="focus-ring rounded-full p-2 disabled:opacity-30"><ChevronRight size={16} /></button></div></div>
    </div> : null}
  </section>;
}

function EmptyState({ filtered }: { filtered: boolean }) {
  return <div className="mt-4 rounded-[1.25rem] border border-dashed border-navy-200 bg-canvas px-5 py-10 text-center"><div className="mx-auto flex size-14 items-center justify-center rounded-2xl bg-white text-steel-500 shadow-soft"><Database size={24} /></div><h3 className="mt-4 font-display text-2xl text-navy-900">{filtered ? "No matching sources" : "No sources yet"}</h3><p className="mx-auto mt-2 max-w-lg text-sm text-subtle">{filtered ? "Adjust the source search or filter." : "Connect a database, document, or REST API from Ingest."}</p></div>;
}
