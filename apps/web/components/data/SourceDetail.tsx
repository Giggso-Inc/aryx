"use client";

import { ArrowLeft, Database, Download, FileCode2, Trash2 } from "lucide-react";
import { cn } from "@/lib/cn";
import type { DataSourceDetail, XmlGeneratedAsset } from "@/lib/types";
import { SourceEntityOverview } from "./SourceEntityOverview";
import { SourceRecordsPreview } from "./SourceRecordsPreview";
import { XmlSourceDetailView } from "./XmlSourceDetail";

type Props = {
  workspaceId: number; detail: DataSourceDetail; busyTarget: string | null;
  onBack: () => void; onDownloadSource: () => void; onDeleteSource: () => void;
  onPreviewAsset: (asset: XmlGeneratedAsset) => Promise<Record<string, string>[]>;
  onDownloadAsset: (asset: XmlGeneratedAsset) => void;
  onDeleteAsset: (asset: XmlGeneratedAsset) => void;
};

export function SourceDetailView(props: Props) {
  const { detail } = props;
  const SourceIcon = detail.kind === "xml" || detail.kind === "xlsx" ? FileCode2 : Database;
  return <div className="space-y-6">
    <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
      <button type="button" onClick={props.onBack} className="focus-ring inline-flex items-center gap-2 rounded-full border border-navy-100 px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-subtle hover:bg-navy-50"><ArrowLeft size={14} />All sources</button>
      <div className="mt-5 flex items-start gap-4">
        <div className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-canvas text-steel-600 shadow-soft"><SourceIcon size={24} /></div>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle">{detail.display_kind}</p>
          <div className="mt-2 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <h2 className="min-w-0 break-words font-display text-[2.4rem] leading-none text-navy-900">{detail.name}</h2>
            <div className="flex flex-wrap items-center gap-2"><span className={cn("rounded-full px-3 py-1 text-xs font-semibold", detail.ready ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700")}>{detail.status}</span>{detail.actions.download ? <Action label="Download" icon={<Download size={16} />} disabled={props.busyTarget === `${detail.source_key}:download`} onClick={props.onDownloadSource} /> : null}{detail.actions.delete ? <Action label="Delete Source" icon={<Trash2 size={16} />} disabled={props.busyTarget === `${detail.source_key}:delete`} onClick={props.onDeleteSource} danger /> : null}</div>
          </div>
          <p className="mt-4 text-sm text-subtle">{detail.record_count.toLocaleString()} source records{detail.generatedAssetCount ? ` · ${detail.generatedAssetCount.toLocaleString()} generated assets` : ""}</p>
        </div>
      </div>
    </section>

    <SourceEntityOverview workspaceId={props.workspaceId} sourceKey={detail.source_key} summary={detail.entity_summary} />
    {detail.detail_kind === "grouped_assets" ? <XmlSourceDetailView detail={detail} busyTarget={props.busyTarget} onBack={props.onBack} onDownloadSource={props.onDownloadSource} onDeleteSource={props.onDeleteSource} onPreviewAsset={props.onPreviewAsset} onDownloadAsset={props.onDownloadAsset} onDeleteAsset={props.onDeleteAsset} showHeader={false} /> : <SourceRecordsPreview workspaceId={props.workspaceId} sourceKey={detail.source_key} />}
  </div>;
}

function Action({ label, icon, disabled, onClick, danger = false }: { label: string; icon: React.ReactNode; disabled: boolean; onClick: () => void; danger?: boolean }) {
  return <button type="button" disabled={disabled} onClick={onClick} className={cn("focus-ring inline-flex items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-semibold disabled:opacity-50", danger ? "border-rose-300 text-rose-600 hover:bg-rose-50" : "border-navy-100 text-navy-800 hover:bg-navy-50")}>{icon}{label}</button>;
}
