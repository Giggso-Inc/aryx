"use client";
import { useRef } from "react";
import { Check, FileText, Upload, Zap } from "lucide-react";
import { cn } from "@/lib/cn";

interface Props {
  files: File[];
  setFiles: React.Dispatch<React.SetStateAction<File[]>>;
  context: string;
  setContext: (v: string) => void;
  started: boolean;
  onStart: () => void;
}

export function DocsUploadStep({ files, setFiles, context, setContext, started, onStart }: Props) {
  const dropRef = useRef<HTMLDivElement>(null);
  return (
    <div className={cn("rounded-xl border bg-white p-5 shadow-soft",
      started ? "border-navy-50 opacity-60 pointer-events-none" : "border-navy-100")}>
      <div className="mb-3 flex items-center gap-2">
        <span className={cn("flex size-6 items-center justify-center rounded-full text-[11px] font-bold",
          started ? "bg-emerald-500 text-white" : "bg-navy-800 text-white")}>
          {started ? <Check size={12} /> : "1"}
        </span>
        <h3 className="font-semibold text-navy-900">Upload files</h3>
      </div>

      <div ref={dropRef}
        onDrop={(e) => { e.preventDefault(); setFiles((p) => [...p, ...[...e.dataTransfer.files]]); }}
        onDragOver={(e) => e.preventDefault()}
        className="mb-3 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-navy-200 bg-navy-50/40 py-8 hover:bg-navy-50"
        onClick={() => document.getElementById("doc-file-input")?.click()}>
        <Upload size={24} className="mb-2 text-navy-400" />
        <p className="text-[13px] text-navy-600">Drop files here or click to browse</p>
        <p className="mt-0.5 text-[11px] text-subtle">DOCX, PDF, PPTX, RTF, HTML, CSV, JSON</p>
        <input id="doc-file-input" type="file" multiple accept=".docx,.pdf,.pptx,.rtf,.html,.csv,.json,.xml"
          className="hidden" onChange={(e) => e.target.files && setFiles((p) => [...p, ...Array.from(e.target.files!)])} />
      </div>

      {files.length > 0 && (
        <ul className="mb-3 space-y-1">
          {files.map((f, i) => (
            <li key={i} className="flex items-center gap-2 rounded-lg bg-navy-50 px-3 py-1.5 text-[12px]">
              <FileText size={12} className="text-steel-500" />
              <span className="flex-1 truncate text-navy-700">{f.name}</span>
              <span className="text-subtle">{(f.size / 1024).toFixed(0)} KB</span>
              <button type="button" onClick={() => setFiles(files.filter((_, j) => j !== i))} className="text-subtle hover:text-rose-500">×</button>
            </li>
          ))}
        </ul>
      )}

      <div className="mb-3">
        <label className="mb-1 block text-[11px] font-medium text-navy-600">Business context (optional)</label>
        <input value={context} onChange={(e) => setContext(e.target.value)}
          placeholder="e.g. Customer success documents for a SaaS company"
          className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] focus:border-steel-500" />
      </div>

      <button type="button" onClick={onStart} disabled={!files.length || started}
        className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50">
        <Zap size={13} /> Read &amp; discover types
      </button>
    </div>
  );
}
