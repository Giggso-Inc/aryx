import { Download, Eye, FileSpreadsheet, Search, Trash2 } from "lucide-react";
import type { XmlGeneratedAsset } from "@/lib/types";
import { IconOnlyAction, StatusPill } from "./shared";

export function AssetsTable({
  assets,
  totalCount,
  query,
  onQueryChange,
  busyTarget,
  previewLoading,
  previewingAssetKey,
  onPreviewAsset,
  onDownloadAsset,
  onDeleteAsset,
  sourceKey,
}: {
  assets: XmlGeneratedAsset[];
  totalCount: number;
  query: string;
  onQueryChange: (value: string) => void;
  busyTarget: string | null;
  previewLoading: boolean;
  previewingAssetKey: string | null;
  onPreviewAsset: (asset: XmlGeneratedAsset) => void;
  onDownloadAsset: (asset: XmlGeneratedAsset) => void;
  onDeleteAsset: (asset: XmlGeneratedAsset) => void;
  sourceKey: string;
}) {
  return (
    <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-3">
          <h3 className="font-display text-[2.2rem] leading-none text-navy-900 md:text-[2.5rem] lg:text-[1.9rem]">
            Generated Assets
          </h3>
          <span className="rounded-full bg-[#D9E7FF] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-steel-700">
            {totalCount} asset{totalCount === 1 ? "" : "s"} active
          </span>
        </div>

        <label className="flex min-w-0 items-center gap-3 rounded-2xl border border-navy-100 bg-canvas px-4 py-3 text-sm text-subtle lg:w-[320px]">
          <Search size={16} className="shrink-0 text-navy-400" />
          <input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Filter assets..."
            className="w-full bg-transparent text-sm text-navy-900 outline-none placeholder:text-subtle"
          />
        </label>
      </div>

      <div className="mt-5 overflow-hidden rounded-[1.5rem] border border-navy-100">
        <div className="hidden grid-cols-[minmax(0,1.4fr)_160px_160px_140px] gap-4 bg-navy-50 px-5 py-4 text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle lg:grid">
          <span>Asset Details</span>
          <span>Status</span>
          <span>Record Count</span>
          <span className="text-right">Actions</span>
        </div>
        {assets.map((asset) => (
          <div
            key={asset.asset_key}
            className="border-t border-navy-100 px-4 py-4 first:border-t-0 lg:grid lg:grid-cols-[minmax(0,1.4fr)_160px_160px_140px] lg:items-center lg:gap-4 lg:px-5"
          >
            <div className="flex min-w-0 items-start gap-3">
              <div className="mt-0.5 flex size-12 items-center justify-center rounded-2xl bg-canvas text-steel-600">
                <FileSpreadsheet size={20} />
              </div>
              <div className="min-w-0">
                <p className="truncate text-base font-semibold text-navy-900">{asset.filename}</p>
                <p className="mt-1 text-sm text-subtle">{asset.ontology_type}</p>
              </div>
            </div>

            <div className="mt-3 lg:mt-0">
              <StatusPill>{asset.status}</StatusPill>
            </div>

            <div className="mt-3 text-sm font-semibold text-navy-900 lg:mt-0">
              {asset.record_count.toLocaleString()}
            </div>

            <div className="mt-3 flex items-center gap-2 lg:mt-0 lg:justify-end">
              <IconOnlyAction
                label={`View ${asset.filename}`}
                icon={<Eye size={16} />}
                disabled={previewLoading && previewingAssetKey === asset.asset_key}
                onClick={() => onPreviewAsset(asset)}
              />
              <IconOnlyAction
                label={`Download ${asset.filename}`}
                icon={<Download size={16} />}
                disabled={busyTarget === `${sourceKey}:${asset.asset_key}:download`}
                onClick={() => onDownloadAsset(asset)}
              />
              <IconOnlyAction
                label={`Delete ${asset.filename}`}
                icon={<Trash2 size={16} />}
                tone="danger"
                disabled={busyTarget === `${sourceKey}:${asset.asset_key}:delete`}
                onClick={() => onDeleteAsset(asset)}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
