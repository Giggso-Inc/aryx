"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle, CheckCircle2, Loader2, Play, Plus, Trash2, ToggleLeft, ToggleRight,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Rule } from "@/lib/types";

const OPS = [">", ">=", "<", "<=", "==", "!=", "contains"];
const ACTIONS = ["set_label", "add_relationship"];

export function RulesTab({ workspaceId }: { workspaceId: number }) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [whenType, setWhenType] = useState("");
  const [whenAttr, setWhenAttr] = useState("");
  const [whenOp, setWhenOp] = useState(">");
  const [whenVal, setWhenVal] = useState("");
  const [action, setAction] = useState("set_label");
  const [labelOrRel, setLabelOrRel] = useState("");
  const [targetType, setTargetType] = useState("");
  const [targetName, setTargetName] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRules(await api.getRules(workspaceId));
    } catch {
      setError("Failed to load rules");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => { load(); }, [load]);

  const saveRule = async () => {
    if (!name.trim() || !whenType.trim() || !whenAttr.trim()) return;
    setSaving(true); setError(null);
    try {
      await api.createRule(workspaceId, {
        name: name.trim(),
        when_type: whenType.trim(),
        attribute: whenAttr.trim(),
        operator: whenOp,
        value: whenVal.trim(),
        action,
        label: labelOrRel.trim() || name,
        target_type: targetType.trim(),
        target_name: targetName.trim(),
      });
      setName(""); setWhenType(""); setWhenAttr(""); setWhenVal("");
      setLabelOrRel(""); setTargetType(""); setTargetName("");
      await load();
      setResult("Rule saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (r: Rule) => {
    try {
      await api.toggleRule(r.name, workspaceId, !r.enabled);
      await load();
    } catch { /* ignore */ }
  };

  const del = async (r: Rule) => {
    if (!confirm(`Delete rule "${r.name}"?`)) return;
    try {
      await api.deleteRule(r.name, workspaceId);
      await load();
    } catch { /* ignore */ }
  };

  const evaluate = async () => {
    setEvaluating(true); setError(null); setResult(null);
    try {
      const res = await api.evaluateRules(workspaceId);
      setResult(`Evaluator: ${res.violations ?? 0} violation(s), ${res.applied ?? 0} inference(s) applied.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Evaluate failed");
    } finally {
      setEvaluating(false);
    }
  };

  return (
    <div className="space-y-6">
      <p className="text-[12px] text-subtle">
        Rules let Aryx infer facts not stored — e.g. <em>Customers with revenue &gt; $1M are Platinum</em>.
        Inferred edges and labels appear on the Graph with a dashed style.
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

      {/* Rules list */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[12px] font-bold uppercase tracking-[0.1em] text-navy-500">
            Active rules ({rules.length})
          </h3>
          <button
            type="button"
            onClick={evaluate}
            disabled={evaluating || rules.length === 0}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-steel-200 bg-white px-3 py-1.5 text-[12px] font-semibold text-steel-700 hover:bg-steel-50 disabled:opacity-50"
          >
            {evaluating ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            Run evaluator
          </button>
        </div>
        {loading ? (
          <div className="flex items-center gap-2 text-[12px] text-subtle"><Loader2 size={12} className="animate-spin" />Loading…</div>
        ) : rules.length === 0 ? (
          <p className="text-[12px] text-subtle italic">No rules yet. Add one below to start inferring facts.</p>
        ) : (
          <div className="overflow-hidden rounded-xl border border-navy-100">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-navy-50 bg-navy-50">
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">Rule</th>
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">Condition</th>
                  <th className="px-3 py-2 text-left font-semibold text-navy-600">Action</th>
                  <th className="px-3 py-2 text-right" />
                </tr>
              </thead>
              <tbody className="divide-y divide-navy-50">
                {rules.map((r) => (
                  <tr key={r.name} className={cn("hover:bg-navy-50/50", !r.enabled && "opacity-50")}>
                    <td className="px-3 py-2 font-semibold text-navy-800">{r.name}</td>
                    <td className="px-3 py-2 text-subtle">
                      if {r.when_type}.{r.attribute} {r.operator} {r.value}
                    </td>
                    <td className="px-3 py-2 text-subtle">
                      {r.action}: {r.label}
                      {r.target_type ? ` → ${r.target_type}` : ""}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center justify-end gap-1">
                        <button type="button" onClick={() => toggle(r)}
                          className="focus-ring rounded-md p-1 text-steel-600 hover:bg-steel-50"
                          title={r.enabled ? "Disable" : "Enable"}>
                          {r.enabled ? <ToggleRight size={14} /> : <ToggleLeft size={14} />}
                        </button>
                        <button type="button" onClick={() => del(r)}
                          className="focus-ring rounded-md p-1 text-rose-500 hover:bg-rose-50">
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Add rule form */}
      <section className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft">
        <h3 className="mb-4 text-[13px] font-bold text-navy-900">Add or update a rule</h3>
        <div className="space-y-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Rule name (e.g. platinum_customer)"
            className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
          />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div>
              <label className="mb-1 block text-[10px] font-semibold text-navy-600">When type</label>
              <input value={whenType} onChange={(e) => setWhenType(e.target.value)}
                placeholder="Customer"
                className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px] focus:border-steel-500" />
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold text-navy-600">Attribute</label>
              <input value={whenAttr} onChange={(e) => setWhenAttr(e.target.value)}
                placeholder="revenue"
                className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px] focus:border-steel-500" />
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold text-navy-600">Operator</label>
              <select value={whenOp} onChange={(e) => setWhenOp(e.target.value)}
                className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px]">
                {OPS.map((op) => <option key={op}>{op}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold text-navy-600">Value</label>
              <input value={whenVal} onChange={(e) => setWhenVal(e.target.value)}
                placeholder="1000000"
                className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px] focus:border-steel-500" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div>
              <label className="mb-1 block text-[10px] font-semibold text-navy-600">Action</label>
              <select value={action} onChange={(e) => setAction(e.target.value)}
                className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px]">
                {ACTIONS.map((a) => <option key={a}>{a}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold text-navy-600">
                {action === "set_label" ? "Set label" : "Relationship name"}
              </label>
              <input value={labelOrRel} onChange={(e) => setLabelOrRel(e.target.value)}
                placeholder={action === "set_label" ? "Platinum" : "BELONGS_TO"}
                className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px] focus:border-steel-500" />
            </div>
            {action === "add_relationship" && (
              <div>
                <label className="mb-1 block text-[10px] font-semibold text-navy-600">Target type</label>
                <input value={targetType} onChange={(e) => setTargetType(e.target.value)}
                  placeholder="Tier"
                  className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[12px] focus:border-steel-500" />
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={saveRule}
            disabled={!name.trim() || !whenType.trim() || !whenAttr.trim() || saving}
            className="focus-ring inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-navy-800 py-2.5 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
          >
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
            Save rule
          </button>
        </div>
      </section>
    </div>
  );
}
