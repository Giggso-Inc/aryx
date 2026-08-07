"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Play, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { WorkspaceRule } from "@/lib/types";

interface Props {
  workspaceId: number;
}

const OPS = [">", ">=", "<", "<=", "==", "!=", "contains"];
type ActionKind = "set_label" | "add_relationship";

/** Workspace-level inference rules (/rules) — forward-chaining DSL:
 *  when: {type, attr, op, value} → then: {set_label} | {add_relationship,
 *  target_type, target_name}. See aryx.reasoning.engine for the evaluator. */
export function RulesTab({ workspaceId }: Props) {
  const [rules, setRules] = useState<WorkspaceRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyName, setBusyName] = useState<string | null>(null);
  const [evalResult, setEvalResult] = useState<Record<string, unknown> | null>(null);
  const [evaluating, setEvaluating] = useState(false);

  // ── form state ──────────────────────────────────────────────────────
  const [name, setName] = useState("");
  const [whenType, setWhenType] = useState("");
  const [whenAttr, setWhenAttr] = useState("");
  const [whenOp, setWhenOp] = useState("==");
  const [whenValue, setWhenValue] = useState("");
  const [action, setAction] = useState<ActionKind>("set_label");
  const [setLabel, setSetLabel] = useState("");
  const [relName, setRelName] = useState("");
  const [targetType, setTargetType] = useState("");
  const [targetName, setTargetName] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRules(await api.listWorkspaceRules(workspaceId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load rules");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => { load(); }, [load]);

  const toggle = async (rule: WorkspaceRule) => {
    setBusyName(rule.name);
    try {
      await api.setWorkspaceRuleEnabled(workspaceId, rule.name, !rule.enabled);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed");
    } finally {
      setBusyName(null);
    }
  };

  const remove = async (rule: WorkspaceRule) => {
    if (!window.confirm(`Delete rule "${rule.name}"?`)) return;
    setBusyName(rule.name);
    try {
      await api.deleteWorkspaceRule(workspaceId, rule.name);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setBusyName(null);
    }
  };

  const runEvaluator = async () => {
    setEvaluating(true);
    setError(null);
    try {
      setEvalResult(await api.evaluateWorkspaceRules(workspaceId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Evaluation failed");
    } finally {
      setEvaluating(false);
    }
  };

  const submit = async () => {
    if (!name.trim() || !whenAttr.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const when: Record<string, unknown> = {
        attr: whenAttr.trim(), op: whenOp, value: whenValue,
      };
      if (whenType.trim()) when.type = whenType.trim();
      const then: Record<string, unknown> = action === "set_label"
        ? { set_label: setLabel }
        : { add_relationship: relName, target_type: targetType, target_name: targetName };
      await api.upsertWorkspaceRule(workspaceId, name.trim(), when, then, true);
      setName(""); setWhenType(""); setWhenAttr(""); setWhenValue("");
      setSetLabel(""); setRelName(""); setTargetType(""); setTargetName("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
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
          <div className="flex items-center justify-between">
            <h2 className="font-display text-[1.1rem] text-navy-900">
              Rules ({rules.length})
            </h2>
            <button
              onClick={runEvaluator}
              disabled={evaluating}
              className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
            >
              {evaluating ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              Run evaluator
            </button>
          </div>

          {loading ? (
            <div className="flex justify-center py-6 text-subtle"><Loader2 className="animate-spin" size={18} /></div>
          ) : rules.length === 0 ? (
            <div className="rounded-xl border border-dashed border-navy-200 px-4 py-6 text-center text-[12px] italic text-subtle">
              No inference rules yet.
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-navy-100 bg-white">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="bg-navy-50/60 text-left text-[11px] uppercase tracking-wider text-subtle">
                    <th className="px-4 py-2 font-medium">Name</th>
                    <th className="px-4 py-2 font-medium">Condition</th>
                    <th className="px-4 py-2 font-medium">Action</th>
                    <th className="px-4 py-2 font-medium">Enabled</th>
                    <th className="px-4 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {rules.map((r) => (
                    <tr key={r.name} className="border-t border-navy-100">
                      <td className="px-4 py-2.5 font-medium text-navy-900">{r.name}</td>
                      <td className="px-4 py-2.5 font-mono text-[11px] text-navy-600">
                        {r.when.type ? `${String(r.when.type)}.` : ""}
                        {String(r.when.attr ?? "")} {String(r.when.op ?? "")} {String(r.when.value ?? "")}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-[11px] text-navy-600">
                        {r.then.set_label
                          ? `set_label → ${String(r.then.set_label)}`
                          : `add_relationship → ${String(r.then.add_relationship ?? "")}`}
                      </td>
                      <td className="px-4 py-2.5">
                        <button
                          onClick={() => toggle(r)}
                          disabled={busyName === r.name}
                          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                            r.enabled ? "bg-emerald-50 text-emerald-700" : "bg-navy-50 text-subtle"
                          }`}
                        >
                          {r.enabled ? "enabled" : "disabled"}
                        </button>
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <button
                          onClick={() => remove(r)}
                          disabled={busyName === r.name}
                          className="focus-ring inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-white px-2 py-1 text-[11px] text-rose-600 hover:bg-rose-50"
                        >
                          <Trash2 size={11} /> Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {evalResult && (
            <pre className="max-h-64 overflow-auto rounded-xl border border-navy-100 bg-navy-50/40 px-4 py-3 text-[11px] text-navy-800">
              {JSON.stringify(evalResult, null, 2)}
            </pre>
          )}
        </section>

        <section className="space-y-3">
          <h2 className="font-display text-[1.1rem] text-navy-900">Add or update a rule</h2>
          <div className="space-y-4 rounded-xl border border-navy-100 bg-white p-5">
            <Field label="Rule name">
              <input value={name} onChange={(e) => setName(e.target.value)}
                placeholder="high_value_customer"
                className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500" />
            </Field>

            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Field label="When: type (optional)">
                <input value={whenType} onChange={(e) => setWhenType(e.target.value)}
                  placeholder="Customer"
                  className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500" />
              </Field>
              <Field label="Attribute">
                <input value={whenAttr} onChange={(e) => setWhenAttr(e.target.value)}
                  placeholder="revenue"
                  className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500" />
              </Field>
              <Field label="Operator">
                <select value={whenOp} onChange={(e) => setWhenOp(e.target.value)}
                  className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500">
                  {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </Field>
              <Field label="Value">
                <input value={whenValue} onChange={(e) => setWhenValue(e.target.value)}
                  placeholder="1000000"
                  className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500" />
              </Field>
            </div>

            <Field label="Action">
              <select value={action} onChange={(e) => setAction(e.target.value as ActionKind)}
                className="focus-ring w-full max-w-xs rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500">
                <option value="set_label">set_label</option>
                <option value="add_relationship">add_relationship</option>
              </select>
            </Field>

            {action === "set_label" ? (
              <Field label="Label to set">
                <input value={setLabel} onChange={(e) => setSetLabel(e.target.value)}
                  placeholder="Platinum"
                  className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500" />
              </Field>
            ) : (
              <div className="grid grid-cols-3 gap-3">
                <Field label="Relationship name">
                  <input value={relName} onChange={(e) => setRelName(e.target.value)}
                    placeholder="TIER_MEMBER"
                    className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500" />
                </Field>
                <Field label="Target type">
                  <input value={targetType} onChange={(e) => setTargetType(e.target.value)}
                    placeholder="Tier"
                    className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500" />
                </Field>
                <Field label="Target name">
                  <input value={targetName} onChange={(e) => setTargetName(e.target.value)}
                    placeholder="Platinum"
                    className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500" />
                </Field>
              </div>
            )}

            <button
              onClick={submit}
              disabled={!name.trim() || !whenAttr.trim() || saving}
              className="focus-ring inline-flex items-center gap-2 rounded-lg bg-navy-800 px-3 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
            >
              {saving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
              Save rule
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="block text-[11px] uppercase tracking-wider text-subtle">{label}</label>
      {children}
    </div>
  );
}
