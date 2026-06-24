"use client";
import { Check, CheckCircle2, FileText } from "lucide-react";
import { cn } from "@/lib/cn";
import type { DiscoverySummary } from "@/lib/types";

interface Props {
  summary: DiscoverySummary;
  approved: Set<string>;
  onToggle: (type: string) => void;
  confirming: boolean;
  onConfirm: () => void;
  onReset: () => void;
}

export function DocsSummaryStep({ summary, approved, onToggle, confirming, onConfirm, onReset }: Props) {
  const canConfirm = approved.size > 0 || (summary.files ?? []).length > 0;
  return (
    <div className={cn("rounded-xl border bg-white p-5 shadow-soft animate-fade-in",
      confirming ? "border-navy-50 opacity-60 pointer-events-none" : "border-navy-100")}>
      <div className="mb-4 flex items-center gap-2">
        <span className={cn("flex size-6 items-center justify-center rounded-full text-[11px] font-bold",
          confirming ? "bg-emerald-500 text-white" : "bg-navy-800 text-white")}>
          {confirming ? <Check size={12} /> : "2"}
        </span>
        <h3 className="font-semibold text-navy-900">Review discovered types</h3>
        <span className="ml-auto text-[11px] text-subtle">{approved.size} of {summary.types.length} selected</span>
      </div>

      <div className="space-y-2 mb-4">
        {summary.types.map((t) => (
          <div key={t.type} onClick={() => onToggle(t.type)}
            className={cn("flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors",
              approved.has(t.type) ? "border-steel-200 bg-steel-50" : "border-navy-100 bg-white hover:bg-navy-50")}>
            <div className={cn("mt-0.5 flex size-4 shrink-0 items-center justify-center rounded border",
              approved.has(t.type) ? "border-steel-500 bg-steel-500" : "border-navy-300")}>
              {approved.has(t.type) && <Check size={10} className="text-white" />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-navy-900">{t.type}</span>
                <span className="rounded-full bg-navy-100 px-2 py-0.5 text-[10px] font-medium text-navy-600">
                  {t.count} mention{t.count !== 1 ? "s" : ""}
                </span>
              </div>
              {t.examples.filter(Boolean).length > 0 && (
                <p className="mt-0.5 truncate text-[11px] text-subtle">
                  e.g. {t.examples.filter(Boolean).slice(0, 3).join(", ")}
                </p>
              )}
            </div>
          </div>
        ))}
        {summary.types.length === 0 && (summary.files ?? []).length === 0 && (
          <p className="py-2 text-[12px] text-subtle italic">
            No entity types found. Try uploading a document with named entities (PDF, DOCX) or a CSV/JSON file.
          </p>
        )}
        {(summary.files ?? []).length > 0 && (
          <div className="mt-1">
            {summary.types.length > 0 && (
              <p className="mb-1 text-[11px] font-medium text-navy-600">Tabular files (all will be ingested)</p>
            )}
            {summary.files.map((f) => (
              <div key={f.filename}
                className="mb-1.5 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
                <FileText size={12} className="shrink-0 text-emerald-600" />
                <span className="flex-1 truncate text-[12px] font-medium text-navy-800">{f.filename}</span>
                <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                  {f.ontology_type}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <button type="button" onClick={onConfirm} disabled={!canConfirm}
          className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50">
          <CheckCircle2 size={13} /> Confirm &amp; ingest
        </button>
        <button type="button" onClick={onReset}
          className="focus-ring rounded-lg px-3 py-2 text-[13px] text-navy-600 hover:bg-navy-50">
          Start over
        </button>
      </div>
    </div>
  );
}
