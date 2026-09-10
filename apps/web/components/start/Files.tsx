"use client";

import { useState } from "react";
import { ArrowRight, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { StepShell, ExampleBox } from "./StepShell";
import { DropZone } from "./files-step/DropZone";
import { FileList } from "./files-step/FileList";

interface Props {
  workspaceId: number;
  onUploaded: (jobId: string | null) => void;
  onBack: () => void;
  onSkip: () => void;
}

const MAX_PER = 2 * 1024 * 1024;
const MAX_TOTAL = 50 * 1024 * 1024;
const MAX_FILES = 50;

/** Files step — drop zone + per-file list. POSTs to /admin/ingest/file
 *  which kicks the doc pipeline (chunk → PII → embed → extract). */
export function Files({ workspaceId, onUploaded, onBack, onSkip }: Props) {
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const addFiles = (incoming: FileList | File[] | null) => {
    if (!incoming) return;
    const next = [...files, ...Array.from(incoming)].slice(0, MAX_FILES);
    setFiles(next);
    setError(null);
  };

  const remove = (i: number) =>
    setFiles((prev) => prev.filter((_, idx) => idx !== i));

  const totalBytes = files.reduce((a, f) => a + f.size, 0);
  const tooBig = files.some((f) => f.size > MAX_PER) || totalBytes > MAX_TOTAL;

  const upload = async () => {
    if (!files.length) return;
    if (tooBig) { setError("Some files exceed the size limits."); return; }
    setBusy(true);
    setError(null);
    try {
      const r = await api.uploadFiles(workspaceId, files);
      onUploaded(r.job_id || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <StepShell progress={70}>
      <h1 className="max-w-2xl text-center font-display text-[2rem] leading-tight text-navy-900">
        Drop the files you want Aryx to read.
      </h1>
      <p className="mt-3 max-w-lg text-center text-[14px] text-subtle">
        PDFs, Word docs, slides, CSVs, JSON, images. Up to 50 files, 2&nbsp;MB
        each, 50&nbsp;MB total — for now.
      </p>

      <DropZone
        fileCount={files.length}
        totalBytes={totalBytes}
        dragging={dragging}
        onDragging={setDragging}
        onFilesAdded={addFiles}
      />

      <FileList files={files} maxPerFileBytes={MAX_PER} onRemove={remove} />

      {error && (
        <div className="mt-3 w-full max-w-2xl rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          {error}
        </div>
      )}

      <div className="mt-7 flex w-full max-w-2xl items-center justify-between gap-3">
        <div className="flex gap-3 text-[12px] text-subtle">
          <button onClick={onBack} className="focus-ring hover:text-navy-700">← Back</button>
          <button onClick={onSkip} className="focus-ring hover:text-navy-700">Skip</button>
        </div>
        <button
          type="button"
          onClick={upload}
          disabled={busy || files.length === 0 || tooBig}
          className="focus-ring inline-flex items-center gap-2 rounded-xl bg-navy-800 px-5 py-2.5 text-[14px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {busy ? <Loader2 size={15} className="animate-spin" />
                 : <>Upload &amp; continue <ArrowRight size={14} /></>}
        </button>
      </div>

      <ExampleBox label="What happens after upload">
        Aryx chunks each document, runs a PII screen, embeds the chunks for
        semantic search, and extracts entities into your graph. Progress shows
        on the next screen — you can leave and come back.
      </ExampleBox>
    </StepShell>
  );
}
