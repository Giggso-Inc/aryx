"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Download, Loader2 } from "lucide-react";
import { api } from "@/lib/api";

const TOOL_HINTS: Record<string, string> = {
  turtle: "Protégé, GraphDB, Apache Jena, Stardog",
  "json-ld": "Web apps, Google Rich Results, JSON-LD playground",
  xml: "Protégé, legacy RDF stores, OWL API tools",
  "n-triples": "Bulk loaders, line-by-line streaming, dump/diff",
};

const EXT_MAP: Record<string, string> = {
  turtle: "ttl",
  "json-ld": "jsonld",
  xml: "rdf",
  "n-triples": "nt",
};

export function PublishTab({ workspaceId }: { workspaceId: number }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [formats, setFormats] = useState<string[]>([]);
  const [selectedFmt, setSelectedFmt] = useState("");
  const [exporting, setExporting] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([
      api.getOntologyConfig(),
      api.getOntologyFormats(),
    ]).then(([cfg, fmts]) => {
      if (cfg.status === "fulfilled") {
        setEnabled(cfg.value.enabled);
        setFormats(cfg.value.formats ?? []);
        setSelectedFmt(cfg.value.formats?.[0] ?? "");
      }
      if (fmts.status === "fulfilled" && fmts.value.length > 0) {
        const names = fmts.value.map((f) => f.name);
        setFormats((prev) => prev.length ? prev : names);
        if (!selectedFmt) setSelectedFmt(names[0]);
      }
    }).finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const publish = async () => {
    if (!selectedFmt) return;
    setExporting(true); setError(null); setPreview(null);
    try {
      const blob = await api.exportOntology(workspaceId, selectedFmt);
      const text = await blob.text();
      setPreview(text.slice(0, 1500));
      const ext = EXT_MAP[selectedFmt] ?? "ttl";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aryx_ws${workspaceId}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setExporting(false);
    }
  };

  if (loading) return (
    <div className="flex items-center gap-2 py-8 text-[12px] text-subtle">
      <Loader2 size={13} className="animate-spin" /> Checking publish config…
    </div>
  );

  if (enabled === false) return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-[13px] text-amber-800">
      <strong>Publish is disabled.</strong> Enable ontology interchange in Settings (or the API config)
      to publish in Turtle, JSON-LD, RDF-XML, and N-Triples formats.
    </div>
  );

  if (formats.length === 0) return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-[13px] text-amber-800">
      No publish formats enabled. Add formats in Settings.
    </div>
  );

  return (
    <div className="space-y-5">
      <p className="text-[12px] text-subtle">
        Serialise the workspace ontology to standard RDF/OWL formats for use in Protégé,
        GraphDB, Apache Jena, or any SPARQL triple store.
      </p>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          <AlertCircle size={13} /> {error}
        </div>
      )}

      <div className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft">
        <div className="mb-4">
          <label className="mb-1 block text-[11px] font-semibold uppercase tracking-[0.1em] text-navy-600">
            Format
          </label>
          <div className="flex flex-wrap gap-2">
            {formats.map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setSelectedFmt(f)}
                className={`focus-ring rounded-lg border px-4 py-2 text-[12px] font-medium transition-colors ${
                  selectedFmt === f
                    ? "border-steel-400 bg-steel-50 text-steel-700"
                    : "border-navy-100 text-navy-600 hover:bg-navy-50"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
          {selectedFmt && TOOL_HINTS[selectedFmt] && (
            <p className="mt-2 text-[11px] text-subtle">
              Opens in: {TOOL_HINTS[selectedFmt]}
            </p>
          )}
        </div>

        <button
          type="button"
          onClick={publish}
          disabled={!selectedFmt || exporting}
          className="focus-ring inline-flex items-center gap-2 rounded-lg bg-navy-800 px-5 py-2.5 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {exporting ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
          {exporting ? "Generating…" : `Publish as ${selectedFmt || "…"}`}
        </button>
      </div>

      {preview && (
        <div className="rounded-xl border border-navy-100 bg-white p-4 shadow-soft">
          <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-navy-500">
            Preview (first 1,500 chars)
          </div>
          <pre className="overflow-x-auto rounded-lg bg-navy-950 p-3 text-[11px] text-navy-200">
            {preview}
          </pre>
        </div>
      )}
    </div>
  );
}
