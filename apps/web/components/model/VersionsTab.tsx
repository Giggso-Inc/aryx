"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Camera, CheckCircle2, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { OntologyChange, OntologyVersion } from "@/lib/types";

export function VersionsTab({ workspaceId }: { workspaceId: number }) {
  const [versions, setVersions] = useState<OntologyVersion[]>([]);
  const [changes, setChanges] = useState<OntologyChange[]>([]);
  const [loading, setLoading] = useState(true);
  const [label, setLabel] = useState("");
  const [snapping, setSnapping] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [v, c] = await Promise.allSettled([
        api.listOntologyVersions(workspaceId),
        api.getOntologyChanges(workspaceId),
      ]);
      setVersions(v.status === "fulfilled" ? v.value : []);
      setChanges(c.status === "fulfilled" ? c.value : []);
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => { load(); }, [load]);

  const snap = async () => {
    setSnapping(true); setError(null); setResult(null);
    try {
      const v = await api.createOntologySnapshot(workspaceId, label || "manual");
      setLabel("");
      setResult(`Snapshot created (id ${v.id}).`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Snapshot failed");
    } finally {
      setSnapping(false);
    }
  };

  return (
    <div className="space-y-6">
      <p className="text-[12px] text-subtle">
        Snapshots freeze your current types + rules so you can compare or roll back.
        Every edit also writes to the change log below.
      </p>

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

      {/* Snapshot form */}
      <div className="flex gap-2 rounded-xl border border-navy-100 bg-white p-4 shadow-soft">
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && snap()}
          placeholder="Snapshot label (e.g. After Platinum rule added)"
          className="focus-ring flex-1 rounded-lg border border-navy-100 px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
        />
        <button
          type="button"
          onClick={snap}
          disabled={snapping}
          className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {snapping ? <Loader2 size={13} className="animate-spin" /> : <Camera size={13} />}
          Take snapshot
        </button>
      </div>

      {/* Versions table */}
      <section>
        <h3 className="mb-2 text-[12px] font-bold uppercase tracking-[0.1em] text-navy-500">
          Snapshots
        </h3>
        {loading ? (
          <div className="flex items-center gap-2 text-[12px] text-subtle"><Loader2 size={12} className="animate-spin" />Loading…</div>
        ) : versions.length === 0 ? (
          <p className="text-[12px] text-subtle italic">No snapshots yet — take one above to start versioning.</p>
        ) : (
          <div className="overflow-hidden rounded-xl border border-navy-100">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-navy-50 bg-navy-50">
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">Version</th>
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">Label</th>
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">Created at</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-navy-50">
                {[...versions].reverse().map((v) => (
                  <tr key={v.id} className="hover:bg-navy-50/50">
                    <td className="px-3 py-2 font-mono font-semibold text-steel-600">v{v.id}</td>
                    <td className="px-3 py-2 text-navy-800">{v.label || "—"}</td>
                    <td className="px-3 py-2 text-subtle">{new Date(v.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Change log */}
      <section>
        <h3 className="mb-2 text-[12px] font-bold uppercase tracking-[0.1em] text-navy-500">
          Recent changes
        </h3>
        {changes.length === 0 ? (
          <p className="text-[12px] text-subtle italic">No changes logged yet.</p>
        ) : (
          <div className="overflow-hidden rounded-xl border border-navy-100">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-navy-50 bg-navy-50">
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">When</th>
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">Kind</th>
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-navy-50">
                {changes.slice(0, 25).map((c, i) => (
                  <tr key={i} className="hover:bg-navy-50/50">
                    <td className="px-3 py-2 text-subtle">{new Date(c.ts).toLocaleString()}</td>
                    <td className="px-3 py-2 font-medium text-navy-700">{c.kind}</td>
                    <td className="px-3 py-2 text-subtle">{c.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
