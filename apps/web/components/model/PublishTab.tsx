"use client";

import { useEffect, useState } from "react";
import { Download, FolderUp, Loader2 } from "lucide-react";
import { api, isHttpStatusError } from "@/lib/api";
import type { OntologyFormat } from "@/lib/types";

interface Props {
  workspaceId: number;
}

/** Export the workspace ontology to RDF/OWL and trigger a download,
 *  with a text preview of the serialized content. */
export function PublishTab({ workspaceId }: Props) {
  const [formats, setFormats] = useState<OntologyFormat[]>([]);
  const [format, setFormat] = useState("turtle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsEnable, setNeedsEnable] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [lastFilename, setLastFilename] = useState<string | null>(null);

  useEffect(() => {
    api.getOntologyFormats().then((list) => {
      setFormats(list);
      if (list.length && !list.some((f) => f.name === "turtle")) {
        setFormat(list[0].name);
      }
    }).catch(() => {});
  }, []);

  const enable = async () => {
    setBusy(true);
    try {
      await api.setOntologyConfig({ enabled: true, formats: [format] });
      setNeedsEnable(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to enable interchange");
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    setBusy(true);
    setError(null);
    setNeedsEnable(false);
    try {
      const { blob, filename } = await api.exportOntology(workspaceId, format);
      setLastFilename(filename);
      const text = await blob.text();
      setPreview(text.slice(0, 1500));

      // Client-side download, same pattern used across the codebase for
      // blob responses: create an object URL, click a throwaway <a>.
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      if (isHttpStatusError(e, 403)) {
        setNeedsEnable(true);
        setError(`Ontology export is disabled, or "${format}" isn't an enabled format.`);
      } else {
        setError(e instanceof Error ? e.message : "Export failed");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className="mx-auto max-w-2xl space-y-6">
        <div className="space-y-1">
          <h2 className="font-display text-[1.1rem] text-navy-900">Publish the ontology</h2>
          <p className="text-[12px] text-subtle">
            Export the approved schema (and, if enabled, provenance) as RDF/OWL
            for downstream tools.
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[200px] space-y-1">
            <label className="block text-[11px] uppercase tracking-wider text-subtle">Format</label>
            <select
              value={format}
              onChange={(e) => setFormat(e.target.value)}
              className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
            >
              {(formats.length ? formats : [{ name: "turtle", media_type: "", extension: "ttl" }])
                .map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
            </select>
          </div>
          <button
            onClick={publish}
            disabled={busy}
            className="focus-ring inline-flex items-center gap-2 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <FolderUp size={14} />}
            Publish as {format}
          </button>
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
                Enable ontology interchange for {format}
              </button>
            )}
          </div>
        )}

        {preview && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-[12px] font-medium text-navy-800">
              <Download size={13} /> {lastFilename} (preview, first 1500 chars)
            </div>
            <pre className="max-h-96 overflow-auto rounded-xl border border-navy-100 bg-navy-50/40 px-4 py-3 text-[11px] leading-relaxed text-navy-800">
              {preview}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
