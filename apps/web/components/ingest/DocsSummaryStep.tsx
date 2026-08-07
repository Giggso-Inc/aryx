"use client";

import { CheckCircle2, Circle, Loader2, RotateCcw } from "lucide-react";
import { cn } from "@/lib/cn";
import type { DiscoverySummary } from "./types";

interface Props {
  summary: DiscoverySummary;
  approved: Set<string>;
  onToggle: (key: string) => void;
  confirming: boolean;
  onConfirm: () => void;
  onReset: () => void;
}

// Composite keys disambiguate discovered types from tabular files sharing
// the same Set<string> (`t:Customer` vs. `f:orders.csv`).
export const typeKey = (type: string) => `t:${type}`;
export const fileKey = (filename: string) => `f:${filename}`;

/** Discovered-type / file checklist shown once GET /admin/docs/summary
 *  returns a populated result — user approves what actually gets ingested. */
export function DocsSummaryStep({
  summary, approved, onToggle, confirming, onConfirm, onReset,
}: Props) {
  const types = summary.types ?? [];
  const files = summary.files ?? [];
  const nothingFound = types.length === 0 && files.length === 0;
  const anyApproved = approved.size > 0;

  return (
    <div className="w-full max-w-2xl">
      <h2 className="text-[15px] font-semibold text-navy-900">
        Here&apos;s what Aryx found
      </h2>
      <p className="mt-1 text-[13px] text-subtle">
        Pick the entity types and files you want ingested into the graph.
      </p>

      {nothingFound && (
        <div className="mt-4 rounded-lg border border-navy-100 bg-navy-50/50 px-4 py-3 text-[13px] text-subtle">
          No entity types or tabular files were discovered in these documents.
        </div>
      )}

      {types.length > 0 && (
        <section className="mt-4">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-subtle">
            Discovered types
          </div>
          <ul className="mt-2 space-y-1.5">
            {types.map((t) => {
              const key = typeKey(t.type);
              const on = approved.has(key);
              return (
                <li key={key}>
                  <button
                    type="button"
                    onClick={() => onToggle(key)}
                    className={cn(
                      "focus-ring flex w-full items-center justify-between rounded-lg border px-3 py-2.5 text-left transition-colors",
                      on ? "border-steel-400 bg-navy-50" : "border-navy-100 bg-white hover:border-navy-200",
                    )}
                  >
                    <span className="flex items-center gap-2.5">
                      {on ? <CheckCircle2 size={16} className="text-steel-600" />
                          : <Circle size={16} className="text-navy-200" />}
                      <span className="text-[13.5px] font-medium text-navy-800">{t.type}</span>
                    </span>
                    <span className="flex items-center gap-2 text-[11.5px] text-subtle">
                      <span>{t.count} mention{t.count === 1 ? "" : "s"}</span>
                      {t.examples.length > 0 && (
                        <span className="hidden max-w-[14rem] truncate sm:inline">
                          · {t.examples.join(", ")}
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {files.length > 0 && (
        <section className="mt-4">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-subtle">
            Tabular files
          </div>
          <ul className="mt-2 space-y-1.5">
            {files.map((f) => {
              const key = fileKey(f.filename);
              const on = approved.has(key);
              return (
                <li key={key}>
                  <button
                    type="button"
                    onClick={() => onToggle(key)}
                    className={cn(
                      "focus-ring flex w-full items-center justify-between rounded-lg border px-3 py-2.5 text-left transition-colors",
                      on ? "border-steel-400 bg-navy-50" : "border-navy-100 bg-white hover:border-navy-200",
                    )}
                  >
                    <span className="flex items-center gap-2.5">
                      {on ? <CheckCircle2 size={16} className="text-steel-600" />
                          : <Circle size={16} className="text-navy-200" />}
                      <span className="text-[13.5px] font-medium text-navy-800">{f.filename}</span>
                    </span>
                    <span className="text-[11.5px] text-subtle">{f.ontology_type}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <div className="mt-6 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={onReset}
          className="focus-ring inline-flex items-center gap-1.5 text-[12px] text-subtle hover:text-navy-700"
        >
          <RotateCcw size={12} /> Start over
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={confirming || !anyApproved}
          className="focus-ring inline-flex items-center gap-2 rounded-xl bg-navy-800 px-5 py-2.5 text-[14px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {confirming ? <Loader2 size={15} className="animate-spin" /> : null}
          Confirm &amp; ingest
        </button>
      </div>
    </div>
  );
}
