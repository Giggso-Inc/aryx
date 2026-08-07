"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, Loader2, UploadCloud, X } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { SupportedFileTypes } from "./types";

interface Props {
  files: File[];
  setFiles: (files: File[]) => void;
  context: string;
  setContext: (context: string) => void;
  started: boolean;
  onStart: () => void;
}

const FALLBACK_ACCEPT =
  ".pdf,.docx,.doc,.pptx,.ppt,.rtf,.html,.htm,.json,.csv,.xlsx,.xml,.jpg,.jpeg,.png,.tiff,.tif,.bmp";

/** Drag-and-drop + click-to-browse file picker for the Documents tab. Reads
 *  the accepted extensions and size limits from GET /admin/ingest/supported
 *  so the client never drifts from what the backend actually accepts. */
export function DocsUploadStep({
  files, setFiles, context, setContext, started, onStart,
}: Props) {
  const [limits, setLimits] = useState<SupportedFileTypes | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    api.getSupportedFileTypes().then((l) => { if (!cancelled) setLimits(l); })
      .catch(() => { /* fall back to defaults below */ });
    return () => { cancelled = true; };
  }, []);

  const accept = limits?.file_types?.length
    ? limits.file_types.join(",") : FALLBACK_ACCEPT;
  const maxFiles = limits?.max_files ?? 50;
  const maxFileBytes = (limits?.max_file_mb ?? 20) * 1024 * 1024;
  const maxTotalBytes = (limits?.max_total_mb ?? 50) * 1024 * 1024;

  const addFiles = (incoming: FileList | File[] | null) => {
    if (!incoming || started) return;
    const next = [...files, ...Array.from(incoming)].slice(0, maxFiles);
    setFiles(next);
    setError(null);
  };

  const remove = (i: number) => {
    if (started) return;
    setFiles(files.filter((_, idx) => idx !== i));
  };

  const totalBytes = files.reduce((a, f) => a + f.size, 0);
  const tooBig = files.some((f) => f.size > maxFileBytes) || totalBytes > maxTotalBytes;

  const submit = () => {
    if (!files.length) return;
    if (tooBig) { setError("Some files exceed the size limits."); return; }
    onStart();
  };

  return (
    <div className="w-full max-w-2xl">
      <div
        onDragOver={(e) => { e.preventDefault(); if (!started) setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          addFiles(e.dataTransfer.files);
        }}
        onClick={() => !started && inputRef.current?.click()}
        className={cn(
          "w-full rounded-2xl border-[1.5px] border-dashed px-6 py-10 text-center transition-all",
          started ? "cursor-not-allowed border-navy-100 bg-navy-50/50 opacity-70"
                  : "cursor-pointer",
          !started && dragging
            ? "border-steel-500 bg-navy-50"
            : !started && "border-navy-200 bg-white hover:border-steel-400",
        )}
      >
        <UploadCloud size={28} className="mx-auto text-steel-500" />
        <div className="mt-2 text-[14px] font-medium text-navy-800">
          Drop files here or click to browse
        </div>
        <div className="mt-1 text-[12px] text-subtle">
          {files.length === 0
            ? `Up to ${maxFiles} files · ${limits?.max_file_mb ?? 20} MB each · ${limits?.max_total_mb ?? 50} MB total`
            : `${files.length} file${files.length === 1 ? "" : "s"} ready · ${(totalBytes / 1024 / 1024).toFixed(1)} MB`}
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={accept}
          disabled={started}
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />
      </div>

      {files.length > 0 && (
        <ul className="mt-4 space-y-1.5">
          {files.map((f, i) => {
            const oversize = f.size > maxFileBytes;
            return (
              <li
                key={`${f.name}-${i}`}
                className={cn(
                  "flex items-center justify-between rounded-lg border px-3 py-2 text-[12.5px]",
                  oversize ? "border-rose-200 bg-rose-50/50" : "border-navy-100 bg-white",
                )}
              >
                <span className="truncate text-navy-800">{f.name}</span>
                <span className="ml-3 flex shrink-0 items-center gap-3">
                  <span className={cn(
                    "font-mono text-[11px]",
                    oversize ? "text-rose-600" : "text-subtle",
                  )}>
                    {(f.size / 1024).toFixed(0)} KB
                  </span>
                  {!started && (
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); remove(i); }}
                      className="focus-ring rounded p-1 text-subtle hover:bg-navy-50 hover:text-rose-500"
                      aria-label={`Remove ${f.name}`}
                    >
                      <X size={12} />
                    </button>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      <div className="mt-4">
        <label className="text-[11px] font-semibold uppercase tracking-wider text-subtle">
          Business context (optional)
        </label>
        <input
          value={context}
          disabled={started}
          onChange={(e) => setContext(e.target.value)}
          placeholder="e.g. Sales contracts and vendor onboarding forms"
          className="focus-ring mt-1.5 w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500 disabled:opacity-60"
        />
      </div>

      {error && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          {error}
        </div>
      )}

      <div className="mt-6 flex justify-end">
        <button
          type="button"
          onClick={submit}
          disabled={started || files.length === 0 || tooBig}
          className="focus-ring inline-flex items-center gap-2 rounded-xl bg-navy-800 px-5 py-2.5 text-[14px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {started ? <Loader2 size={15} className="animate-spin" />
                    : <>Read &amp; discover types <ArrowRight size={14} /></>}
        </button>
      </div>
    </div>
  );
}
