"use client";

import { useMemo, useState } from "react";
import {
  ArrowLeft, Download, Eye, FileCode2, FileSpreadsheet, Search, Trash2, X,
} from "lucide-react";
import { cn } from "@/lib/cn";
import type { XmlGeneratedAsset, XmlSourceDetail } from "@/lib/types";

export function XmlSourceDetailView({
  detail,
  busyTarget,
  onBack,
  onDownloadSource,
  onDeleteSource,
  onPreviewAsset,
  onDownloadAsset,
  onDeleteAsset,
}: {
  detail: XmlSourceDetail;
  busyTarget: string | null;
  onBack: () => void;
  onDownloadSource: () => void;
  onDeleteSource: () => void;
  onPreviewAsset: (asset: XmlGeneratedAsset) => Promise<Record<string, string>[]>;
  onDownloadAsset: (asset: XmlGeneratedAsset) => void;
  onDeleteAsset: (asset: XmlGeneratedAsset) => void;
}) {
  const [query, setQuery] = useState("");
  const [selectedAssetKey, setSelectedAssetKey] = useState<string | null>(null);
  const [previewRows, setPreviewRows] = useState<Record<string, string>[] | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const visibleAssets = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return detail.assets;
    return detail.assets.filter((asset) => {
      const haystack = [asset.filename, asset.ontology_type, asset.dataset]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [detail.assets, query]);
  const selectedAsset = detail.assets.find((asset) => asset.asset_key === selectedAssetKey) || null;

  const openPreview = async (asset: XmlGeneratedAsset) => {
    setSelectedAssetKey(asset.asset_key);
    if (asset.preview_rows.length > 0) {
      setPreviewRows(asset.preview_rows);
      setPreviewLoading(false);
      return;
    }
    setPreviewRows(null);
    setPreviewLoading(true);
    const rows = await onPreviewAsset(asset);
    setPreviewRows(rows);
    setPreviewLoading(false);
  };

  const closePreview = () => {
    setSelectedAssetKey(null);
    setPreviewRows(null);
    setPreviewLoading(false);
  };

  return (
    <div className="space-y-6">
      <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
        <div className="space-y-5">
          <div>
            <button
              type="button"
              onClick={onBack}
              className="focus-ring inline-flex items-center gap-2 rounded-full border border-navy-100 bg-white px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-subtle transition-colors hover:bg-navy-50"
            >
              <ArrowLeft size={14} />
              Back
            </button>

          </div>

          <div className="flex items-start gap-4">
            <div className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-canvas text-steel-600 shadow-soft">
              <FileCode2 size={24} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle">
                Primary Data Source
              </p>
              <div className="mt-2 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between lg:gap-6">
                <h2 className="min-w-0 break-words font-display text-[2.4rem] leading-none text-navy-900 md:text-[2.7rem]">
                  {detail.name}
                </h2>
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  <StatusPill>{detail.status}</StatusPill>
                  <ActionButton
                    label="Download"
                    icon={<Download size={16} />}
                    disabled={busyTarget === `${detail.source_key}:download`}
                    onClick={onDownloadSource}
                  />
                  <ActionButton
                    label="Delete Source"
                    icon={<Trash2 size={16} />}
                    tone="danger"
                    disabled={busyTarget === `${detail.source_key}:delete`}
                    onClick={onDeleteSource}
                  />
                </div>
              </div>

              <p className="mt-4 text-sm text-subtle">
                {detail.record_count.toLocaleString()} records distributed across {detail.generatedAssetCount.toLocaleString()} generated asset
                {detail.generatedAssetCount === 1 ? "" : "s"}.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-[1.5rem] border border-navy-100 bg-[#EEF4FF] p-5 shadow-soft">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle">
          Active Transformation Pipe
        </p>
        <div className="mt-5 flex flex-col gap-6 lg:flex-row lg:items-center">
          <div className="flex min-w-[124px] flex-col items-center text-center">
            <div className="flex size-16 items-center justify-center rounded-2xl bg-navy-800 text-white shadow-soft">
              <FileCode2 size={24} />
            </div>
            <span className="mt-3 text-sm font-semibold text-navy-900">XML Root</span>
          </div>
          <div className="flex flex-1 items-center gap-4">
            <div className="h-px flex-1 bg-navy-100" />
            <div className="rounded-full bg-[#6FE2D0] px-5 py-2 text-center text-xs font-semibold uppercase tracking-[0.16em] text-[#045E58] shadow-sm">
              Splitting &amp; Fragmenting
            </div>
            <div className="h-px flex-1 bg-navy-100" />
          </div>
          <div className="flex min-w-[124px] flex-col items-center text-center">
            <div className="grid size-16 grid-cols-2 gap-1 rounded-2xl bg-white p-3 shadow-soft">
              <div className="rounded bg-[#79F1DC]" />
              <div className="rounded bg-[#7C3AED]" />
              <div className="rounded bg-[#FFD7D1]" />
              <div className="rounded bg-[#D5E3FF]" />
            </div>
            <span className="mt-3 text-sm font-semibold text-navy-900">CSV Output</span>
          </div>
        </div>
      </section>

      <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <h3 className="font-display text-[2.2rem] leading-none text-navy-900 md:text-[2.5rem] lg:text-[1.9rem]">
              Generated Assets
            </h3>
            <span className="rounded-full bg-[#D9E7FF] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-steel-700">
              {detail.generatedAssetCount} asset{detail.generatedAssetCount === 1 ? "" : "s"} active
            </span>
          </div>

          <label className="flex min-w-0 items-center gap-3 rounded-2xl border border-navy-100 bg-canvas px-4 py-3 text-sm text-subtle lg:w-[320px]">
            <Search size={16} className="shrink-0 text-navy-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
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
          {visibleAssets.map((asset) => (
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
                  disabled={previewLoading && selectedAssetKey === asset.asset_key}
                  onClick={() => { void openPreview(asset); }}
                />
                <IconOnlyAction
                  label={`Download ${asset.filename}`}
                  icon={<Download size={16} />}
                  disabled={busyTarget === `${detail.source_key}:${asset.asset_key}:download`}
                  onClick={() => onDownloadAsset(asset)}
                />
                <IconOnlyAction
                  label={`Delete ${asset.filename}`}
                  icon={<Trash2 size={16} />}
                  tone="danger"
                  disabled={busyTarget === `${detail.source_key}:${asset.asset_key}:delete`}
                  onClick={() => onDeleteAsset(asset)}
                />
              </div>
            </div>
          ))}
        </div>
      </section>

      {selectedAsset ? (
        <AssetPreviewModal
          asset={selectedAsset}
          previewRows={previewRows ?? selectedAsset.preview_rows}
          loading={previewLoading}
          onClose={closePreview}
        />
      ) : null}
    </div>
  );
}

function AssetPreviewModal({
  asset,
  previewRows,
  loading,
  onClose,
}: {
  asset: XmlGeneratedAsset;
  previewRows: Record<string, string>[];
  loading: boolean;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/45 px-4 py-8"
      role="dialog"
      aria-modal="true"
      aria-labelledby="xml-asset-preview-title"
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-full max-w-5xl overflow-hidden rounded-[1.5rem] border border-navy-100 bg-white shadow-soft"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-navy-100 px-5 py-4">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle">
              Asset Preview
            </p>
            <h4 id="xml-asset-preview-title" className="mt-1 truncate text-xl font-semibold text-navy-900">
              {asset.filename}
            </h4>
            <p className="mt-1 text-sm text-subtle">
              {asset.ontology_type} · {asset.record_count.toLocaleString()}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="focus-ring inline-flex size-10 items-center justify-center rounded-full border border-navy-100 bg-white text-subtle transition-colors hover:bg-navy-50 hover:text-navy-700"
            aria-label="Close preview"
          >
            <X size={18} />
          </button>
        </div>

        <div className="max-h-[calc(85vh-88px)] overflow-auto p-5">
          {loading ? (
            <div className="rounded-2xl border border-dashed border-navy-200 bg-canvas px-4 py-10 text-center text-sm text-subtle">
              Loading preview…
            </div>
          ) : previewRows.length > 0 ? (
            <div className="overflow-x-auto rounded-2xl border border-navy-100 bg-white">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-navy-50 text-xs uppercase tracking-[0.14em] text-subtle">
                  <tr>
                    {Object.keys(previewRows[0]).map((header) => (
                      <th key={header} className="px-4 py-3 font-semibold">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {previewRows.map((row, index) => (
                    <tr key={index} className="border-t border-navy-100">
                      {Object.values(row).map((value, valueIndex) => (
                        <td key={valueIndex} className="px-4 py-3 text-navy-800">
                          {value || "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="rounded-2xl border border-dashed border-navy-200 bg-canvas px-4 py-10 text-center text-sm text-subtle">
              Preview is unavailable for this asset.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusPill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700">
      {children}
    </span>
  );
}

function ActionButton({
  label,
  icon,
  disabled,
  onClick,
  tone = "default",
}: {
  label: string;
  icon: React.ReactNode;
  disabled: boolean;
  onClick: () => void;
  tone?: "default" | "danger";
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "focus-ring inline-flex items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        tone === "danger"
          ? "border-rose-300 bg-white text-rose-600 hover:bg-rose-50"
          : "border-navy-100 bg-white text-navy-800 hover:bg-navy-50",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function IconOnlyAction({
  label,
  icon,
  disabled,
  tone = "default",
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  disabled: boolean;
  tone?: "default" | "danger";
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "focus-ring inline-flex size-9 items-center justify-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-35",
        tone === "danger"
          ? "text-rose-500 hover:bg-rose-50 hover:text-rose-600"
          : "text-navy-500 hover:bg-navy-50 hover:text-navy-800",
      )}
    >
      {icon}
    </button>
  );
}
