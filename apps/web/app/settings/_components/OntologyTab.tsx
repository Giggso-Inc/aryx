"use client";

import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { Section } from "./shared";
import { OntologyFormatPicker } from "./OntologyFormatPicker";

export function OntologyTab() {
  const [enabled, setEnabled] = useState<boolean>(true);
  const [includeProv, setIncludeProv] = useState<boolean>(false);
  const [baseUri, setBaseUri] = useState("");
  const [selectedFormats, setSelectedFormats] = useState<string[]>([]);
  const [availableFormats, setAvailableFormats] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => {
    Promise.allSettled([
      api.getOntologyConfig(),
      api.getOntologyFormats(),
    ]).then(([cfg, fmts]) => {
      if (cfg.status === "fulfilled") {
        setEnabled(cfg.value.enabled ?? true);
        setSelectedFormats(cfg.value.formats ?? []);
        setBaseUri(cfg.value.base_uri ?? "");
      }
      if (fmts.status === "fulfilled") {
        setAvailableFormats(fmts.value.map((f) => f.name));
      }
    }).finally(() => setLoading(false));
  }, []);

  const toggleFormat = (fmt: string) => {
    setSelectedFormats((prev) =>
      prev.includes(fmt) ? prev.filter((f) => f !== fmt) : [...prev, fmt],
    );
  };

  const save = async () => {
    setSaving(true); setError(null); setResult(null);
    try {
      await api.setOntologyConfig({
        enabled,
        formats: selectedFormats,
        base_uri: baseUri || undefined,
        include_provenance: includeProv,
      });
      setResult("Ontology interchange settings saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return (
    <div className="flex items-center gap-2 py-4 text-[13px] text-subtle">
      <Loader2 size={13} className="animate-spin" />Loading…
    </div>
  );

  return (
    <div className="space-y-5">
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          <AlertCircle size={13} /> {error}
        </div>
      )}
      {result && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] text-emerald-700">
          <CheckCircle2 size={13} /> {result}
        </div>
      )}

      <Section title="Ontology Interchange">
        <p className="mb-4 text-[12px] text-subtle">
          Controls whether the workspace ontology can be published to standard RDF/OWL formats
          (Turtle, JSON-LD, RDF-XML, N-Triples) and which formats are available on the Publish tab.
        </p>

        {/* Enable toggle */}
        <label className="mb-5 flex cursor-pointer items-center gap-3">
          <div className="relative">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="sr-only"
            />
            <div className={`h-5 w-9 rounded-full transition-colors ${enabled ? "bg-steel-500" : "bg-navy-200"}`} />
            <div className={`absolute top-0.5 size-4 rounded-full bg-white shadow transition-transform ${enabled ? "translate-x-4" : "translate-x-0.5"}`} />
          </div>
          <span className="text-[13px] font-medium text-navy-800">
            {enabled ? "Interchange enabled" : "Interchange disabled"}
          </span>
        </label>

        {enabled && (
          <>
            <OntologyFormatPicker
              availableFormats={availableFormats}
              selectedFormats={selectedFormats}
              onToggle={toggleFormat}
            />

            {/* Base URI */}
            <div className="mb-5">
              <label className="mb-1 block text-[11px] font-bold uppercase tracking-[0.1em] text-navy-600">
                Base URI (optional)
              </label>
              <input
                value={baseUri}
                onChange={(e) => setBaseUri(e.target.value)}
                placeholder="https://example.com/ontology/"
                className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
              />
              <p className="mt-1 text-[11px] text-subtle">
                Namespace prefix for published entities. Defaults to a workspace-specific URI.
              </p>
            </div>

            {/* Include provenance */}
            <label className="mb-5 flex cursor-pointer items-center gap-3">
              <input
                type="checkbox"
                checked={includeProv}
                onChange={(e) => setIncludeProv(e.target.checked)}
                className="accent-steel-500"
              />
              <span className="text-[13px] text-navy-800">Include provenance triples</span>
            </label>
          </>
        )}

        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {saving ? <Loader2 size={13} className="animate-spin" /> : null}
          Save settings
        </button>
      </Section>
    </div>
  );
}
