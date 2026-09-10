"use client";

import { useEffect, useState } from "react";
import { Save, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { OntologyType, SurvivorshipPolicy } from "@/lib/types";
import { cn } from "@/lib/cn";
import { AttributeOverridesList } from "./survivor-editor/AttributeOverridesList";
import { SourcePriorityEditor } from "./survivor-editor/SourcePriorityEditor";

interface Props {
  type: OntologyType;
  workspaceId: number;
  initialPolicy: SurvivorshipPolicy;
}

const STRATEGIES = [
  "first_non_empty",
  "source_priority",
  "most_recent",
  "most_complete",
  "most_frequent",
] as const;

/** Editable survivorship policy (G3x). Workspace-scoped — the same policy
 *  drives every type, so this editor exposes default + per-attr overrides
 *  + source-priority list. Saved via PUT /admin/workspaces/{id}/survivorship. */
export function SurvivorEditor({ type, workspaceId, initialPolicy }: Props) {
  const [policy, setPolicy] = useState<SurvivorshipPolicy>(initialPolicy);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newSource, setNewSource] = useState("");

  useEffect(() => { setPolicy(initialPolicy); }, [initialPolicy, type.name]);

  const dirty = JSON.stringify(policy) !== JSON.stringify(initialPolicy);

  const setDefault = (s: string) =>
    setPolicy({ ...policy, default_strategy: s });

  const setAttrOverride = (attr: string, value: string) => {
    const next = { ...(policy.attribute_strategies || {}) };
    if (!value || value === (policy.default_strategy || "first_non_empty")) {
      delete next[attr];
    } else {
      next[attr] = value;
    }
    setPolicy({ ...policy, attribute_strategies: next });
  };

  const addSource = () => {
    const v = newSource.trim();
    if (!v) return;
    const list = policy.source_priority || [];
    if (list.includes(v)) { setNewSource(""); return; }
    setPolicy({ ...policy, source_priority: [...list, v] });
    setNewSource("");
  };

  const removeSource = (s: string) => setPolicy({
    ...policy,
    source_priority: (policy.source_priority || []).filter((x) => x !== s),
  });

  const save = async () => {
    setBusy(true); setError(null); setSaved(null);
    try {
      await api.setSurvivorship(workspaceId, policy);
      setSaved("Policy saved");
      setTimeout(() => setSaved(null), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally { setBusy(false); }
  };

  const def = policy.default_strategy || "first_non_empty";

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-navy-100 bg-white px-3 py-2.5">
        <label className="block text-[10px] uppercase tracking-wider text-subtle">
          Default strategy
        </label>
        <select
          value={def}
          onChange={(e) => setDefault(e.target.value)}
          className="focus-ring mt-1 w-full rounded-md border border-navy-100 bg-white px-2 py-1.5 font-mono text-[12px] text-navy-800 focus:border-steel-500"
        >
          {STRATEGIES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      <SourcePriorityEditor
        sources={policy.source_priority || []}
        usedByDefault={def === "source_priority"}
        newSource={newSource}
        onNewSourceChange={setNewSource}
        onAdd={addSource}
        onRemove={removeSource}
      />

      <AttributeOverridesList
        typeName={type.name}
        attributes={type.attributes}
        overrides={policy.attribute_strategies}
        defaultStrategy={def}
        onChange={setAttrOverride}
      />

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-700">
          {error}
        </div>
      )}
      {saved && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11px] text-emerald-700">
          {saved}
        </div>
      )}

      {dirty && (
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className={cn(
            "focus-ring inline-flex w-full items-center justify-center gap-2 rounded-lg bg-navy-800 px-3 py-2 text-[13px] font-semibold text-white hover:bg-navy-700",
            busy && "opacity-60",
          )}
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          Save survivorship policy
        </button>
      )}
    </div>
  );
}
