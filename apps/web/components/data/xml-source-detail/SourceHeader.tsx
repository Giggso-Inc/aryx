import { ArrowLeft, Download, FileCode2, Trash2 } from "lucide-react";
import type { XmlSourceDetail } from "@/lib/types";
import { ActionButton, StatusPill } from "./shared";

export function SourceHeader({
  detail,
  busyTarget,
  onBack,
  onDownloadSource,
  onDeleteSource,
}: {
  detail: XmlSourceDetail;
  busyTarget: string | null;
  onBack: () => void;
  onDownloadSource: () => void;
  onDeleteSource: () => void;
}) {
  return (
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
  );
}
