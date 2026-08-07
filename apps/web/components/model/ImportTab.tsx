"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2, UploadCloud } from "lucide-react";
import { api, isHttpStatusError } from "@/lib/api";
import type { OntologyFormat, OntologyImportResult } from "@/lib/types";

interface Props {
  workspaceId: number;
  onImported: () => void;
}

const ACCEPT = ".ttl,.owl,.rdf,.xml,.jsonld,.json,.nt,.n3";

/** Drag/click upload of an RDF/OWL vocabulary → POST /ontology/import
 *  (JSON body, not multipart — the backend reads file text client-side). */
export function ImportTab({ workspaceId, onImported }: Props) {
  const [formats, setFormats] = useState<OntologyFormat[]>([]);
  const [format, setFormat] = useState(""); // "" = auto-detect from extension
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsEnable, setNeedsEnable] = useState(false);
  const [result, setResult] = useState<OntologyImportResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.getOntologyFormats().then(setFormats).catch(() => {});
  }, []);

  const pick = useCallback((f: File | null) => {
    setFile(f);
    setResult(null);
    setError(null);
  }, []);

  const enable = async () => {
    setBusy(true);
    try {
      await api.setOntologyConfig({ enabled: true });
      setNeedsEnable(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to enable interchange");
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setNeedsEnable(false);
    try {
      const content = await file.text();
      const res = await api.importOntology(workspaceId, content, format, file.name);
      setResult(res);
      onImported();
    } catch (e) {
      if (isHttpStatusError(e, 403)) {
        setNeedsEnable(true);
        setError("Ontology import is disabled for this workspace.");
      } else {
        setError(e instanceof Error ? e.message : "Import failed");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className="mx-auto max-w-2xl space-y-6">
        <div className="space-y-1">
          <h2 className="font-display text-[1.1rem] text-navy-900">Import a vocabulary</h2>
          <p className="text-[12px] text-subtle">
            Upload an RDF/OWL document — classes become proposed types, ready for
            HITL review in the Lightweight tab. Individuals import straight into
            the graph as real entities + relationships.
          </p>
        </div>

        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const f = e.dataTransfer.files?.[0];
            if (f) pick(f);
          }}
          onClick={() => inputRef.current?.click()}
          className={`flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
            dragOver ? "border-steel-500 bg-steel-50" : "border-navy-200 bg-white hover:bg-navy-50/40"
          }`}
        >
          <UploadCloud size={28} className="text-subtle" />
          {file ? (
            <p className="text-[13px] font-medium text-navy-800">{file.name}</p>
          ) : (
            <>
              <p className="text-[13px] font-medium text-navy-800">
                Drag a file here, or click to browse
              </p>
              <p className="text-[11px] text-subtle">{ACCEPT}</p>
            </>
          )}
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => pick(e.target.files?.[0] || null)}
          />
        </div>

        <div className="space-y-1">
          <label className="block text-[11px] uppercase tracking-wider text-subtle">Format</label>
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value)}
            className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
          >
            <option value="">Auto-detect from filename</option>
            {formats.map((f) => (
              <option key={f.name} value={f.name}>{f.name}</option>
            ))}
          </select>
        </div>

        {error && (
          <div className="space-y-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
            <p>{error}</p>
            {needsEnable && (
              <button
                onClick={enable}
                disabled={busy}
                className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
              >
                Enable ontology interchange
              </button>
            )}
          </div>
        )}

        {result && (
          <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] text-emerald-800">
            <CheckCircle2 size={14} className="mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">{result.message}</p>
              <p className="mt-1 text-emerald-700">
                {result.imported} type(s)
                {typeof result.entities_imported === "number" &&
                  ` · ${result.entities_imported} entities`}
                {typeof result.relationships_imported === "number" &&
                  ` · ${result.relationships_imported} relationships`}
              </p>
            </div>
          </div>
        )}

        <button
          onClick={submit}
          disabled={!file || busy}
          className="focus-ring inline-flex items-center gap-2 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <UploadCloud size={14} />}
          Import vocabulary
        </button>
      </div>
    </div>
  );
}
