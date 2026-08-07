"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Loader2, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { OntologyDoc, OntologyRelationship } from "@/lib/types";

interface Props {
  workspaceId: number;
  onChanged: () => void;
}

/** Top-level "Lightweight" tab: the workspace-scoped review + management
 *  surface for proposed/approved types and declared relationship types.
 *  Mirrors the data Canvas.tsx already renders via api.getOntology, just
 *  as tables instead of a graph. */
export function LightweightTab({ workspaceId, onChanged }: Props) {
  const [doc, setDoc] = useState<OntologyDoc | null>(null);
  const [relationships, setRelationships] = useState<OntologyRelationship[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyName, setBusyName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [newAttrs, setNewAttrs] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [d, declared] = await Promise.all([
        api.getOntology(workspaceId),
        api.listRelationshipTypes(workspaceId).catch(() => []),
      ]);
      setDoc(d);
      setRelationships(
        declared.map((r) => ({
          id: r.id, name: r.name,
          source_type: r.source_type, target_type: r.target_type,
        })),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load ontology");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => { load(); }, [load]);

  const approve = async (name: string) => {
    setBusyName(name);
    try {
      await api.approveType(workspaceId, name);
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setBusyName(null);
    }
  };

  const remove = async (name: string) => {
    if (!window.confirm(`Delete type "${name}"? Records stay in the graph ` +
      "but are no longer schema-registered.")) return;
    setBusyName(name);
    try {
      await api.deleteType(workspaceId, name);
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setBusyName(null);
    }
  };

  const createType = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const attrs = newAttrs.split(",").map((s) => s.trim()).filter(Boolean);
      await api.createType(workspaceId, newName.trim(), attrs);
      setNewName("");
      setNewAttrs("");
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    } finally {
      setCreating(false);
    }
  };

  const types = doc?.types || [];
  const pending = types.filter((t) => t.status === "proposed");
  const approved = types.filter((t) => t.status !== "proposed");

  if (loading && !doc) {
    return (
      <div className="flex flex-1 items-center justify-center text-subtle">
        <Loader2 className="animate-spin" size={20} />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className="mx-auto max-w-4xl space-y-8">
        {error && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
            {error}
          </div>
        )}

        <Section title={`Pending review (${pending.length})`}>
          {pending.length === 0 ? (
            <Empty label="No proposed types waiting for approval." />
          ) : (
            <Table headers={["Type", "Attributes", "Source", ""]}>
              {pending.map((t) => (
                <tr key={t.name} className="border-t border-navy-100">
                  <Td className="font-medium text-navy-900">{t.name}</Td>
                  <Td className="text-subtle">{(t.attributes || []).join(", ") || "—"}</Td>
                  <Td className="text-subtle">{t.source || "—"}</Td>
                  <Td className="text-right">
                    <button
                      onClick={() => approve(t.name)}
                      disabled={busyName === t.name}
                      className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
                    >
                      {busyName === t.name
                        ? <Loader2 size={12} className="animate-spin" />
                        : <CheckCircle2 size={12} />}
                      Approve
                    </button>
                  </Td>
                </tr>
              ))}
            </Table>
          )}
        </Section>

        <Section title={`Approved entity types (${approved.length})`}>
          {approved.length === 0 ? (
            <Empty label="No approved types yet." />
          ) : (
            <Table headers={["Type", "Attributes", "Instances", "Parent", ""]}>
              {approved.map((t) => (
                <tr key={t.name} className="border-t border-navy-100">
                  <Td className="font-medium text-navy-900">{t.name}</Td>
                  <Td className="text-subtle">{(t.attributes || []).join(", ") || "—"}</Td>
                  <Td className="text-subtle">{t.instance_count ?? 0}</Td>
                  <Td className="text-subtle">{t.parent_type || "—"}</Td>
                  <Td className="text-right">
                    <button
                      onClick={() => remove(t.name)}
                      disabled={busyName === t.name}
                      className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-white px-2.5 py-1.5 text-[12px] font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50"
                    >
                      {busyName === t.name
                        ? <Loader2 size={12} className="animate-spin" />
                        : <Trash2 size={12} />}
                      Delete
                    </button>
                  </Td>
                </tr>
              ))}
            </Table>
          )}
        </Section>

        <Section title={`Relationship types (${relationships.length})`}>
          {relationships.length === 0 ? (
            <Empty label="No relationship types declared yet — draw one on the Diagram tab." />
          ) : (
            <Table headers={["Name", "Source", "Target"]}>
              {relationships.map((r, i) => (
                <tr key={r.id ?? `${r.name}-${i}`} className="border-t border-navy-100">
                  <Td className="font-medium text-navy-900">{r.name}</Td>
                  <Td className="text-subtle">{r.source_type || "—"}</Td>
                  <Td className="text-subtle">{r.target_type || "—"}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Section>

        <Section title="Add new type">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[180px] space-y-1">
              <label className="block text-[11px] uppercase tracking-wider text-subtle">Name</label>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Customer"
                className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
              />
            </div>
            <div className="flex-[2] min-w-[240px] space-y-1">
              <label className="block text-[11px] uppercase tracking-wider text-subtle">
                Attributes (comma-separated)
              </label>
              <input
                value={newAttrs}
                onChange={(e) => setNewAttrs(e.target.value)}
                placeholder="name, region, segment"
                className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 font-mono text-[13px] text-navy-800 focus:border-steel-500"
              />
            </div>
            <button
              onClick={createType}
              disabled={!newName.trim() || creating}
              className="focus-ring inline-flex items-center gap-2 rounded-lg bg-navy-800 px-3 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
            >
              {creating ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
              Add type
            </button>
          </div>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="font-display text-[1.1rem] text-navy-900">{title}</h2>
      {children}
    </section>
  );
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
