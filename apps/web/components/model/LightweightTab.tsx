"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { OntologyDoc } from "@/lib/types";
import { AISuggestButton } from "./AISuggestButton";

interface Props {
  workspaceId: number;
  onChanged: () => void;
}

export function LightweightTab({ workspaceId, onChanged }: Props) {
  const [doc, setDoc] = useState<OntologyDoc | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [newTypeName, setNewTypeName] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.getOntology(workspaceId);
      setDoc(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load ontology");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => { load(); }, [load]);

  const approve = async (name: string) => {
    setApproving(name);
    try {
      await api.approveType(workspaceId, name);
      await load(); onChanged();
    } catch { /* ignore */ } finally { setApproving(null); }
  };

  const deleteType = async (name: string) => {
    if (!confirm(`Delete type "${name}"?`)) return;
    setDeleting(name);
    try {
      await api.deleteType(workspaceId, name);
      await load(); onChanged();
    } catch { /* ignore */ } finally { setDeleting(null); }
  };

  const createType = async () => {
    if (!newTypeName.trim()) return;
    setCreating(true);
    try {
      await api.createType(workspaceId, newTypeName.trim(), []);
      setNewTypeName("");
      await load(); onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    } finally { setCreating(false); }
  };

  if (loading) return (
    <div className="flex items-center gap-2 py-8 text-[13px] text-subtle">
      <Loader2 size={14} className="animate-spin" /> Loading ontology…
    </div>
  );

  if (error) return (
    <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
      <AlertCircle size={13} /> {error}
    </div>
  );

  const proposed = doc?.types.filter((t) => t.status === "proposed") ?? [];
  const approved = doc?.types.filter((t) => t.status !== "proposed") ?? [];
  const rels = doc?.relationships ?? [];

  if (!doc || (approved.length === 0 && proposed.length === 0)) {
    return (
      <div className="space-y-4">
        <div className="rounded-xl border border-dashed border-navy-200 bg-navy-50/40 p-6 text-center">
          <p className="text-[13px] text-subtle">
            No ontology defined yet — run <strong>Ingest</strong> and Aryx will propose types,
            or add one manually below.
          </p>
        </div>
        <AddTypeRow
          value={newTypeName}
          onChange={setNewTypeName}
          onAdd={createType}
          busy={creating}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Lifecycle explanation */}
      <div className="rounded-xl border border-navy-100 bg-navy-50/40 p-4 text-[12px] text-navy-700">
        <strong>Lifecycle:</strong> Brief → Ingest → <span className="text-steel-600">🟦 Lightweight (observed, below)</span> →
        HITL review → <span className="text-purple-700">🟪 Heavyweight (Rules + Versions tabs)</span> → <span className="text-emerald-700">📤 Publish</span>
      </div>

      {/* Pending review */}
      {proposed.length > 0 && (
        <section>
          <h3 className="mb-2 text-[12px] font-bold uppercase tracking-[0.1em] text-amber-700">
            🟡 Pending review ({proposed.length}) — HITL gate
          </h3>
          <p className="mb-3 text-[11px] text-subtle">
            Proposed by ingest discovery. Approve to make them part of the governed ontology.
          </p>
          <div className="overflow-hidden rounded-xl border border-amber-200">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-amber-200 bg-amber-50">
                  <th className="px-3 py-2 text-left font-semibold text-navy-700">owl:Class</th>
                  <th className="px-3 py-2 text-left font-semibold text-navy-700">owl:DatatypeProperty</th>
                  <th className="px-3 py-2 text-left font-semibold text-navy-700">Source</th>
                  <th className="px-3 py-2 text-right font-semibold text-navy-700" />
                </tr>
              </thead>
              <tbody className="divide-y divide-amber-100">
                {proposed.map((t) => (
                  <tr key={t.name} className="hover:bg-amber-50/50">
                    <td className="px-3 py-2 font-semibold text-navy-800">{t.name}</td>
                    <td className="px-3 py-2 text-subtle">{t.attributes?.slice(0, 4).join(", ") || "—"}</td>
                    <td className="px-3 py-2 text-subtle italic">{t.source || "discovery"}</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => approve(t.name)}
                        disabled={approving === t.name}
                        className="focus-ring inline-flex items-center gap-1 rounded-md bg-emerald-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                      >
                        {approving === t.name ? <Loader2 size={10} className="animate-spin" /> : <CheckCircle2 size={10} />}
                        Approve
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Approved types */}
      <section>
        <h3 className="mb-2 text-[12px] font-bold uppercase tracking-[0.1em] text-navy-500">
          ✅ Approved entity types · owl:Class ({approved.length})
        </h3>
        {approved.length > 0 ? (
          <div className="overflow-hidden rounded-xl border border-navy-100">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-navy-50 bg-navy-50">
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">owl:Class</th>
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">Instances</th>
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">owl:DatatypeProperty</th>
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">Source</th>
                  <th className="px-3 py-2 text-right" />
                </tr>
              </thead>
              <tbody className="divide-y divide-navy-50">
                {approved.map((t) => (
                  <tr key={t.name} className="hover:bg-navy-50/50">
                    <td className="px-3 py-2 font-semibold text-navy-800">{t.name}</td>
                    <td className="px-3 py-2 text-steel-600 font-mono">{t.instance_count ?? 0}</td>
                    <td className="px-3 py-2 text-subtle text-[11px]">
                      {t.attributes?.slice(0, 5).join(", ") || "—"}
                    </td>
                    <td className="px-3 py-2 text-subtle italic">{t.source || "approved"}</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => deleteType(t.name)}
                        disabled={deleting === t.name}
                        className="focus-ring inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-rose-600 hover:bg-rose-50 disabled:opacity-50"
                      >
                        {deleting === t.name ? <Loader2 size={10} className="animate-spin" /> : <Trash2 size={10} />}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-[12px] text-subtle italic">No approved types yet — approve some above.</p>
        )}
      </section>

      {/* Relationships */}
      <section>
        <h3 className="mb-2 text-[12px] font-bold uppercase tracking-[0.1em] text-navy-500">
          🔗 Relationship types · owl:ObjectProperty ({rels.length})
        </h3>
        {rels.length > 0 ? (
          <div className="overflow-hidden rounded-xl border border-navy-100">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-navy-50 bg-navy-50">
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">owl:ObjectProperty</th>
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">Source → Target</th>
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">Count</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-navy-50">
                {rels.map((r, i) => (
                  <tr key={r.id ?? i} className="hover:bg-navy-50/50">
                    <td className="px-3 py-2 font-semibold text-navy-800">{r.name}</td>
                    <td className="px-3 py-2 text-subtle">
                      {r.source_type && r.target_type
                        ? `${r.source_type} → ${r.target_type}`
                        : "—"}
                    </td>
                    <td className="px-3 py-2 font-mono text-steel-600">{r.count ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-[12px] text-subtle italic">No relationships yet.</p>
        )}
      </section>

      {/* Add type */}
      <AddTypeRow
        value={newTypeName}
        onChange={setNewTypeName}
        onAdd={createType}
        busy={creating}
      />
    </div>
  );
}

function AddTypeRow({
  value, onChange, onAdd, busy,
}: { value: string; onChange: (v: string) => void; onAdd: () => void; busy: boolean }) {
  return (
    <div className="flex items-center gap-2 rounded-xl border border-dashed border-navy-200 p-3">
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onAdd()}
        placeholder="Add new type (e.g. Contract)"
        className="focus-ring flex-1 rounded-lg border border-navy-100 px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
      />
      <button
        type="button"
        onClick={onAdd}
        disabled={!value.trim() || busy}
        className="focus-ring inline-flex items-center gap-1 rounded-lg bg-navy-800 px-3 py-2 text-[12px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
      >
        {busy ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
        Add type
      </button>
    </div>
  );
}
