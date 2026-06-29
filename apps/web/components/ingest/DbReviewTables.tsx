"use client";
import { Check, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/cn";
import type { DiscoveredTable } from "./types";

interface Props {
  discovered: DiscoveredTable[];
  setDiscovered: React.Dispatch<React.SetStateAction<DiscoveredTable[]>>;
  edges: Array<{ source_type: string; target_type: string; name: string }>;
  ingesting: boolean;
  onIngest: () => void;
}

export function DbReviewTables({ discovered, setDiscovered, edges, ingesting, onIngest }: Props) {
  return (
    <div className={cn("rounded-xl border bg-white p-5 shadow-soft animate-fade-in",
      ingesting ? "border-navy-50 opacity-60 pointer-events-none" : "border-navy-100")}>
      <div className="mb-4 flex items-center gap-2">
        <span className={cn("flex size-6 items-center justify-center rounded-full text-[11px] font-bold",
          ingesting ? "bg-emerald-500 text-white" : "bg-navy-800 text-white")}>
          {ingesting ? <Check size={12} /> : "3"}
        </span>
        <h3 className="font-semibold text-navy-900">Review &amp; confirm</h3>
        <span className="ml-auto text-[11px] text-subtle">
          {discovered.filter((d) => d.included).length} of {discovered.length} selected
        </span>
      </div>

      <div className="mb-4 space-y-2">
        {discovered.map((t, i) => (
          <div key={t.table} className={cn("rounded-lg border p-3 transition-colors",
            t.included ? "border-steel-200 bg-steel-50" : "border-navy-100 bg-white opacity-60")}>
            <div className="flex items-start gap-3">
              <input type="checkbox" checked={t.included}
                onChange={() => setDiscovered((prev) => prev.map((d, j) => j === i ? { ...d, included: !d.included } : d))}
                className="mt-1 accent-steel-500" />
              <div className="flex-1 min-w-0">
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="font-medium text-[12px] text-navy-900">{t.table}</span>
                  <span className="text-[10px] text-subtle">→</span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="mb-0.5 block text-[10px] text-navy-500">Entity type</label>
                    <input value={t.ontology_type}
                      onChange={(e) => setDiscovered((prev) => prev.map((d, j) => j === i ? { ...d, ontology_type: e.target.value } : d))}
                      className="focus-ring w-full rounded border border-navy-100 bg-white px-2 py-1 text-[12px] focus:border-steel-500" />
                  </div>
                  <div>
                    <label className="mb-0.5 block text-[10px] text-navy-500">Match keys (comma-sep)</label>
                    <input value={t.match_keys.join(",")}
                      onChange={(e) => setDiscovered((prev) => prev.map((d, j) => j === i ? {
                        ...d, match_keys: e.target.value.split(",").map((k) => k.trim()).filter(Boolean),
                      } : d))}
                      className="focus-ring w-full rounded border border-navy-100 bg-white px-2 py-1 text-[12px] focus:border-steel-500" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {edges.length > 0 && (
        <div className="mb-4 rounded-lg border border-navy-100 bg-navy-50/40 px-3 py-2 text-[11px] text-navy-600">
          <strong>Relationships found:</strong>{" "}
          {edges.slice(0, 5).map((e) => `${e.source_type}→${e.target_type} (${e.name})`).join(", ")}
          {edges.length > 5 && ` +${edges.length - 5} more`}
        </div>
      )}

      <button type="button" onClick={onIngest}
        disabled={discovered.filter((d) => d.included).length === 0}
        className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50">
        <CheckCircle2 size={13} /> Ingest selected tables
      </button>
    </div>
  );
}
