"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Loader2, Search } from "lucide-react";
import { api } from "@/lib/api";
import { typeColor } from "@/lib/typeColor";
import type { SourceEntitySummary, SourceEntityTypesPage } from "@/lib/types";

export function SourceEntityOverview({
  workspaceId, sourceKey, summary,
}: {
  workspaceId: number;
  sourceKey: string;
  summary: SourceEntitySummary;
}) {
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<SourceEntityTypesPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!expanded) return;
    let live = true;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      api.getSourceEntityTypes(workspaceId, sourceKey, page, query)
        .then((data) => { if (live) setResult(data); })
        .catch((cause) => { if (live) setError(cause instanceof Error ? cause.message : "failed"); })
        .finally(() => { if (live) setLoading(false); });
    }, 200);
    return () => { live = false; window.clearTimeout(timer); };
  }, [expanded, page, query, sourceKey, workspaceId]);

  return (
    <section className="space-y-4" aria-labelledby="source-entity-overview-title">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p id="source-entity-overview-title" className="text-[11px] font-semibold uppercase tracking-[0.22em] text-subtle">
            Entity Resolution Overview
          </p>
          <p className="mt-2 text-sm text-subtle">Resolved entities linked only to this data source.</p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Metric value={summary.total_entities} label="Total Entities" />
          <Metric value={summary.type_count} label="Entity Types" />
        </div>
      </div>

      <div className="rounded-2xl border border-navy-100 bg-white p-4 shadow-soft">
        {summary.types.length ? (
          <div className="flex flex-wrap gap-2">
            {summary.types.map((item, index) => (
              <div key={item.name} className="min-w-[116px] flex-1 rounded-xl px-3 py-2.5 text-white"
                   style={{ background: typeColor(index) }} title={`${item.name}: ${item.count.toLocaleString()}`}>
                <div className="font-display text-2xl leading-none">{formatCount(item.count)}</div>
                <div className="mt-1 truncate text-[11px] font-medium">{item.name}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-navy-200 bg-canvas px-4 py-8 text-center text-sm text-subtle">
            No resolved entities are linked to this source yet.
          </div>
        )}

        {summary.type_count > 12 ? (
          <button type="button" onClick={() => setExpanded((value) => !value)}
                  className="focus-ring mt-4 rounded-full border border-navy-100 px-4 py-2 text-sm font-semibold text-navy-700 hover:bg-navy-50">
            {expanded ? "Hide all entity types" : `View all ${summary.type_count.toLocaleString()} entity types`}
          </button>
        ) : null}

        {expanded ? (
          <div className="mt-4 border-t border-navy-100 pt-4">
            <label className="flex items-center gap-2 rounded-xl border border-navy-100 bg-canvas px-3 py-2 text-sm">
              <Search size={15} className="text-navy-400" />
              <input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }}
                     className="w-full bg-transparent outline-none" placeholder="Search entity types..." />
            </label>
            {loading ? <p className="mt-4 flex items-center gap-2 text-sm text-subtle"><Loader2 size={15} className="animate-spin" /> Loading types…</p> : null}
            {error ? <p className="mt-4 text-sm text-rose-600">{error}</p> : null}
            {!loading && result ? <TypePage result={result} page={page} onPage={setPage} /> : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function Metric({ value, label }: { value: number; label: string }) {
  return <div className="min-w-[140px] rounded-[1.25rem] border border-navy-100 bg-white px-5 py-3 text-right shadow-soft" title={value.toLocaleString()}>
    <p className="text-3xl font-semibold text-steel-600">{formatCount(value)}</p>
    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-subtle">{label}</p>
  </div>;
}

function TypePage({ result, page, onPage }: { result: SourceEntityTypesPage; page: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(result.total / result.page_size));
  return <div className="mt-3">
    <div className="divide-y divide-navy-100 rounded-xl border border-navy-100">
      {result.items.map((item) => <div key={item.name} className="flex justify-between px-3 py-2 text-sm"><span>{item.name}</span><span className="font-semibold">{item.count.toLocaleString()}</span></div>)}
    </div>
    <div className="mt-3 flex items-center justify-end gap-2 text-xs text-subtle">
      <button aria-label="Previous entity types page" disabled={page <= 1} onClick={() => onPage(page - 1)} className="focus-ring rounded-full p-2 disabled:opacity-30"><ChevronLeft size={16} /></button>
      Page {page} of {pages}
      <button aria-label="Next entity types page" disabled={page >= pages} onClick={() => onPage(page + 1)} className="focus-ring rounded-full p-2 disabled:opacity-30"><ChevronRight size={16} /></button>
    </div>
  </div>;
}

function formatCount(value: number) {
  return value >= 100_000 ? new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value) : value.toLocaleString();
}
