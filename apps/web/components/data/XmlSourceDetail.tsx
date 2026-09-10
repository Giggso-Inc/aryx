"use client";

import { useMemo, useState } from "react";
import type { XmlGeneratedAsset, XmlSourceDetail } from "@/lib/types";
import { AssetPreviewModal } from "./xml-source-detail/AssetPreviewModal";
import { AssetsTable } from "./xml-source-detail/AssetsTable";
import { PipelineDiagram } from "./xml-source-detail/PipelineDiagram";
import { SourceHeader } from "./xml-source-detail/SourceHeader";

export function XmlSourceDetailView({
  detail,
  busyTarget,
  onBack,
  onDownloadSource,
  onDeleteSource,
  onPreviewAsset,
  onDownloadAsset,
  onDeleteAsset,
  showHeader = true,
}: {
  detail: XmlSourceDetail;
  busyTarget: string | null;
  onBack: () => void;
  onDownloadSource: () => void;
  onDeleteSource: () => void;
  onPreviewAsset: (asset: XmlGeneratedAsset) => Promise<Record<string, string>[]>;
  onDownloadAsset: (asset: XmlGeneratedAsset) => void;
  onDeleteAsset: (asset: XmlGeneratedAsset) => void;
  showHeader?: boolean;
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
      {showHeader ? (
        <SourceHeader
          detail={detail}
          busyTarget={busyTarget}
          onBack={onBack}
          onDownloadSource={onDownloadSource}
          onDeleteSource={onDeleteSource}
        />
      ) : null}

      <PipelineDiagram />

      <AssetsTable
        assets={visibleAssets}
        totalCount={detail.generatedAssetCount}
        query={query}
        onQueryChange={setQuery}
        busyTarget={busyTarget}
        previewLoading={previewLoading}
        previewingAssetKey={selectedAssetKey}
        onPreviewAsset={(asset) => { void openPreview(asset); }}
        onDownloadAsset={onDownloadAsset}
        onDeleteAsset={onDeleteAsset}
        sourceKey={detail.source_key}
      />

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
