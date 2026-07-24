"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { SourceRecordsPage } from "@/lib/types";

export function SourceRecordsPreview({ workspaceId, sourceKey }: { workspaceId: number; sourceKey: string }) {
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<SourceRecordsPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setError(null);
    api.getSourceRecords(workspaceId, sourceKey, page)
      .then((data) => { if (live) setResult(data); })
      .catch((cause) => { if (live) setError(cause instanceof Error ? cause.message : "failed"); });
    return () => { live = false; };
  }, [page, sourceKey, workspaceId]);

  const headers = result?.rows[0] ? Object.keys(result.rows[0]) : [];
  const pages = result ? Math.max(1, Math.ceil(result.total / result.page_size)) : 1;
  return (
    <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
      <div className="flex items-end justify-between gap-4">
        <div><p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle">Source Records</p><h3 className="mt-2 text-xl font-semibold text-navy-900">Data preview</h3></div>
        {result ? <span className="text-xs text-subtle">{result.total.toLocaleString()} records</span> : null}
      </div>
      {error ? <p className="mt-4 text-sm text-rose-600">{error}</p> : null}
      {!result && !error ? <p className="mt-5 flex items-center gap-2 text-sm text-subtle"><Loader2 size={15} className="animate-spin" /> Loading preview…</p> : null}
      {result && result.rows.length === 0 ? <div className="mt-5 rounded-2xl border border-dashed border-navy-200 bg-canvas px-4 py-10 text-center text-sm text-subtle">No landed records are available for this source yet.</div> : null}
      {result && result.rows.length ? <div className="mt-5 overflow-x-auto rounded-2xl border border-navy-100"><table className="min-w-full text-left text-sm"><thead className="bg-navy-50 text-xs uppercase tracking-[0.14em] text-subtle"><tr>{headers.map((header) => <th key={header} className="px-4 py-3 font-semibold">{header}</th>)}</tr></thead><tbody>{result.rows.map((row, index) => <tr key={`${page}-${index}`} className="border-t border-navy-100">{headers.map((header) => <td key={header} className="max-w-xs truncate px-4 py-3 text-navy-800" title={String(row[header] ?? "")}>{String(row[header] ?? "—")}</td>)}</tr>)}</tbody></table></div> : null}
      {result && pages > 1 ? <div className="mt-4 flex items-center justify-end gap-2 text-xs text-subtle"><button aria-label="Previous records page" disabled={page <= 1} onClick={() => setPage(page - 1)} className="focus-ring rounded-full p-2 disabled:opacity-30"><ChevronLeft size={16} /></button>Page {page} of {pages}<button aria-label="Next records page" disabled={page >= pages} onClick={() => setPage(page + 1)} className="focus-ring rounded-full p-2 disabled:opacity-30"><ChevronRight size={16} /></button></div> : null}
    </section>
  );
}
