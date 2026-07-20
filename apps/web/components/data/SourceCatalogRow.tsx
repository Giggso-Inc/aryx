"use client";

import { Download, Eye, FileCode2, FileSpreadsheet, Trash2 } from "lucide-react";
import { cn } from "@/lib/cn";
import type { DataSourceCatalogItem } from "@/lib/types";

export function SourceCatalogRow({ source, busy, onView, onDownload, onDelete }: {
  source: DataSourceCatalogItem; busy: boolean; onView: () => void;
  onDownload: () => void; onDelete: () => void;
}) {
  const recordCount = source.record_count ?? 0;
  return <article className="border-t border-navy-100 bg-white px-4 py-4 first:border-t-0 xl:grid xl:grid-cols-[minmax(240px,1.5fr)_minmax(120px,.75fr)_95px_95px_90px_90px_100px_120px] xl:items-center xl:gap-3 xl:px-5">
    <div className="flex min-w-0 items-start gap-3"><div className={cn("mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-2xl bg-canvas", source.isXmlParent ? "text-steel-600" : "text-emerald-700")}>{source.isXmlParent ? <FileCode2 size={18} /> : <FileSpreadsheet size={18} />}</div><div className="min-w-0"><button type="button" onClick={onView} className="focus-ring block max-w-full truncate rounded text-left text-base font-semibold text-navy-900 underline-offset-4 hover:text-steel-600 hover:underline" title={source.name}>{source.name}</button><p className="mt-1 text-xs text-subtle">{recordCount.toLocaleString()} record{recordCount === 1 ? "" : "s"}{source.isXmlParent ? ` · ${(source.generatedAssetCount ?? 0).toLocaleString()} generated assets` : ""}</p></div></div>
    <Field label="Type"><span className={cn("inline-flex rounded-full px-3 py-1 text-xs font-semibold", source.isXmlParent ? "bg-[#E8F0FF] text-steel-700" : "bg-emerald-50 text-emerald-700")}>{source.display_kind}</span></Field>
    <Field label="Entities"><Count value={source.total_entities} /></Field>
    <Field label="Entity Types"><Count value={source.entity_type_count} /></Field>
    <Field label="Nodes"><Count value={source.node_count ?? source.total_entities} /></Field>
    <Field label="Edges"><Count value={source.edge_count} missingLabel="Unavailable" /></Field>
    <Field label="Status"><span className={cn("inline-flex rounded-full px-3 py-1 text-xs font-semibold", source.ready ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700")}>{source.ready ? "Ready" : "Configured"}</span></Field>
    <div className="mt-3 flex items-center gap-2 xl:mt-0 xl:justify-end"><Icon label={`View ${source.name}`} icon={<Eye size={16} />} disabled={busy} onClick={onView} /><Icon label={`Download ${source.name}`} icon={<Download size={16} />} disabled={busy || !source.actions.download} onClick={onDownload} /><Icon label={`Delete ${source.name}`} icon={<Trash2 size={16} />} disabled={busy || !source.actions.delete} onClick={onDelete} danger /></div>
  </article>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="mt-3 flex items-center justify-between gap-3 xl:mt-0 xl:block"><span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-subtle xl:hidden">{label}</span>{children}</div>;
}

function Count({ value, missingLabel }: { value?: number | null; missingLabel?: string }) {
  if (value == null) {
    return <span className="text-sm font-semibold text-subtle" title={missingLabel}>—</span>;
  }
  const safeValue = value;
  const compact = safeValue >= 100_000 ? new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(safeValue) : safeValue.toLocaleString();
  return <span className="text-sm font-semibold text-navy-900" title={safeValue.toLocaleString()}>{compact}</span>;
}

function Icon({ label, icon, disabled, onClick, danger = false }: { label: string; icon: React.ReactNode; disabled: boolean; onClick: () => void; danger?: boolean }) {
  return <button type="button" aria-label={label} disabled={disabled} onClick={onClick} className={cn("focus-ring inline-flex size-9 items-center justify-center rounded-full disabled:cursor-not-allowed disabled:opacity-35", danger ? "text-rose-500 hover:bg-rose-50" : "text-navy-500 hover:bg-navy-50")}>{icon}</button>;
}
