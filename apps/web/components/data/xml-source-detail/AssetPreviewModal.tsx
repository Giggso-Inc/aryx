import { X } from "lucide-react";
import type { XmlGeneratedAsset } from "@/lib/types";

export function AssetPreviewModal({
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
