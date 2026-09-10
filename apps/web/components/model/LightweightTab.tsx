"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, FolderUp, Loader2, Scale, Weight } from "lucide-react";
import { api } from "@/lib/api";
import type { OntologyDoc } from "@/lib/types";
import { AddTypeRow } from "./lightweight-tab/AddTypeRow";
import { ApprovedTypesTable } from "./lightweight-tab/ApprovedTypesTable";
import { PendingReviewTable } from "./lightweight-tab/PendingReviewTable";
import { RelationshipsTable } from "./lightweight-tab/RelationshipsTable";

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
      <div className="rounded-xl border border-navy-100 bg-navy-50/40 p-4 text-[12px] text-navy-700">
        <strong>Lifecycle:</strong> Brief → Ingest →
        <span className="inline-flex items-center gap-1.5 align-middle text-steel-600">
          <Weight size={11} /> Lightweight (observed, below)
        </span> →
        HITL review →
        <span className="inline-flex items-center gap-1.5 align-middle text-purple-700">
          <Scale size={11} /> Heavyweight (Rules + Versions tabs)
        </span> →
        <span className="inline-flex items-center gap-1.5 align-middle text-emerald-700">
          <FolderUp size={11} /> Publish
        </span>
      </div>

      {proposed.length > 0 && (
        <PendingReviewTable proposed={proposed} approving={approving} onApprove={approve} />
      )}

      <ApprovedTypesTable approved={approved} deleting={deleting} onDelete={deleteType} />

      <RelationshipsTable rels={rels} />

      <AddTypeRow
        value={newTypeName}
        onChange={setNewTypeName}
        onAdd={createType}
        busy={creating}
      />
    </div>
  );
}
