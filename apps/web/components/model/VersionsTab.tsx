"use client";

import { useCallback, useEffect, useState } from "react";
import { Camera, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { OntologyChange, OntologyVersion } from "@/lib/types";

interface Props {
  workspaceId: number;
}

/** Ontology version snapshots + the recent change log, backed by
 *  /ontology-versions (POST snapshot, GET list, GET /changes). */
export function VersionsTab({ workspaceId }: Props) {
  const [versions, setVersions] = useState<OntologyVersion[]>([]);
  const [changes, setChanges] = useState<OntologyChange[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [snapshotting, setSnapshotting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [v, c] = await Promise.all([
        api.listOntologyVersions(workspaceId),
        api.getOntologyChanges(workspaceId),
      ]);
      setVersions(v);
      setChanges(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load versions");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => { load(); }, [load]);

  const takeSnapshot = async () => {
    setSnapshotting(true);
    setError(null);
    try {
      await api.createOntologySnapshot(workspaceId, label.trim());
      setLabel("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Snapshot failed");
    } finally {
      setSnapshotting(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className="mx-auto max-w-4xl space-y-8">
        {error && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
            {error}
          </div>
        )}

        <section className="space-y-3">
          <h2 className="font-display text-[1.1rem] text-navy-900">Take a snapshot</h2>
          <div className="flex items-end gap-3">
            <div className="flex-1 space-y-1">
              <label className="block text-[11px] uppercase tracking-wider text-subtle">Label</label>
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Pre-Q3 model freeze"
                className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
              />
            </div>
            <button
              onClick={takeSnapshot}
              disabled={snapshotting}
              className="focus-ring inline-flex items-center gap-2 rounded-lg bg-navy-800 px-3 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
            >
              {snapshotting ? <Loader2 size={13} className="animate-spin" /> : <Camera size={13} />}
              Take snapshot
            </button>
          </div>
        </section>

        {loading ? (
          <div className="flex justify-center py-6 text-subtle"><Loader2 className="animate-spin" size={18} /></div>
        ) : (
          <>
            <section className="space-y-3">
              <h2 className="font-display text-[1.1rem] text-navy-900">
                Versions ({versions.length})
              </h2>
              {versions.length === 0 ? (
                <Empty label="No snapshots yet." />
              ) : (
                <Table headers={["Version", "Label", "Created by", "Created"]}>
                  {versions.map((v) => (
                    <tr key={v.id} className="border-t border-navy-100">
                      <Td className="text-subtle">v{v.version_no}</Td>
                      <Td className="font-medium text-navy-900">{v.label || "—"}</Td>
                      <Td className="text-subtle">{v.created_by || "—"}</Td>
                      <Td className="text-subtle">{formatDate(v.created_at)}</Td>
                    </tr>
                  ))}
                </Table>
              )}
            </section>

            <section className="space-y-3">
              <h2 className="font-display text-[1.1rem] text-navy-900">
                Recent changes ({changes.length})
              </h2>
              {changes.length === 0 ? (
                <Empty label="No recorded changes yet." />
              ) : (
                <Table headers={["When", "Actor", "Action", "Kind", "Name"]}>
                  {changes.map((c) => (
                    <tr key={c.id} className="border-t border-navy-100">
                      <Td className="text-subtle">{formatDate(c.changed_at)}</Td>
                      <Td className="text-subtle">{c.actor}</Td>
                      <Td className="font-mono text-[11px] text-navy-700">{c.op}</Td>
                      <Td className="text-subtle">{c.target_kind}</Td>
                      <Td className="font-medium text-navy-900">{c.target_name}</Td>
                    </tr>
                  ))}
                </Table>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function formatDate(v: string): string {
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString();
}

function Table({ headers, children }: { headers: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-xl border border-navy-100 bg-white">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="bg-navy-50/60 text-left text-[11px] uppercase tracking-wider text-subtle">
            {headers.map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Td({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <td className={`px-4 py-2.5 ${className}`}>{children}</td>;
}

function Empty({ label }: { label: string }) {
  return (
    <div className="rounded-xl border border-dashed border-navy-200 px-4 py-6 text-center text-[12px] italic text-subtle">
      {label}
    </div>
  );
}
