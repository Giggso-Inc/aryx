"use client";

import { useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Upload } from "lucide-react";
import { api } from "@/lib/api";

const FORMATS = ["auto", "turtle", "json-ld", "xml", "n-triples"];

export function ImportTab({
  workspaceId, onImported,
}: { workspaceId: number; onImported: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState("auto");
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<{ count: number; types: string[]; message?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFile(e.target.files?.[0] ?? null);
    setResult(null); setError(null);
  };

  const doImport = async () => {
    if (!file) return;
    setImporting(true); setError(null); setResult(null);
    try {
      const content = await file.text();
      const res = await api.importOntology(
        workspaceId, content,
        format === "auto" ? "" : format,
        file.name,
      );
      setResult({ count: res.imported, types: res.types ?? [], message: res.message });
      if (res.imported > 0) onImported();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="space-y-5">
      <p className="text-[12px] text-subtle">
        Bring a standard vocabulary (schema.org, FIBO, a Protégé export).
        Classes become <strong>proposed</strong> types that pass the HITL review gate in
        the Lightweight tab.
      </p>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          <AlertCircle size={13} /> {error}
        </div>
      )}
      {result && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] text-emerald-800">
          <div className="flex items-center gap-2 font-semibold">
            <CheckCircle2 size={13} />
            Imported {result.count} type(s) as proposed.
          </div>
          {result.types.length > 0 && (
            <p className="mt-1 text-[11px]">{result.types.join(", ")}</p>
          )}
          {result.message && (
            <p className="mt-1 text-[11px] text-emerald-700">{result.message}</p>
          )}
        </div>
      )}

      <div className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft">
        {/* Drop zone */}
        <div
          className="mb-4 cursor-pointer rounded-xl border-2 border-dashed border-navy-200 p-6 text-center hover:border-steel-400 hover:bg-steel-50/30 transition-colors"
          onClick={() => fileRef.current?.click()}
        >
          <Upload size={20} className="mx-auto mb-2 text-navy-400" />
          <p className="text-[13px] font-medium text-navy-700">
            {file ? file.name : "Click to upload an ontology file"}
          </p>
          <p className="mt-1 text-[11px] text-subtle">
            Supported: .ttl, .owl, .rdf, .xml, .jsonld, .json, .nt, .n3
          </p>
          <input
            ref={fileRef}
            type="file"
            accept=".ttl,.owl,.rdf,.xml,.jsonld,.json,.nt,.n3"
            onChange={onFile}
            className="hidden"
          />
        </div>

        {/* Format */}
        <div className="mb-4">
          <label className="mb-1 block text-[11px] font-semibold uppercase tracking-[0.1em] text-navy-600">
            Format
          </label>
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value)}
            className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] text-navy-800"
          >
            {FORMATS.map((f) => <option key={f}>{f}</option>)}
          </select>
        </div>

        <button
          type="button"
          onClick={doImport}
          disabled={!file || importing}
          className="focus-ring inline-flex w-full items-center justify-center gap-2 rounded-lg bg-navy-800 py-2.5 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {importing ? (
            <><Loader2 size={13} className="animate-spin" /> Importing…</>
          ) : (
            <><Upload size={13} /> Import vocabulary</>
          )}
        </button>
      </div>
    </div>
  );
}
