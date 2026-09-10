"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Rule } from "@/lib/types";
import { AddRuleForm } from "./rules-tab/AddRuleForm";
import { RulesList } from "./rules-tab/RulesList";

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

      <RulesList
        rules={rules}
        loading={loading}
        evaluating={evaluating}
        onToggle={toggle}
        onDelete={del}
        onEvaluate={evaluate}
      />

      <AddRuleForm
        name={name}
        whenType={whenType}
        whenAttr={whenAttr}
        whenOp={whenOp}
        whenVal={whenVal}
        action={action}
        labelOrRel={labelOrRel}
        targetType={targetType}
        saving={saving}
        onNameChange={setName}
        onWhenTypeChange={setWhenType}
        onWhenAttrChange={setWhenAttr}
        onWhenOpChange={setWhenOp}
        onWhenValChange={setWhenVal}
        onActionChange={setAction}
        onLabelOrRelChange={setLabelOrRel}
        onTargetTypeChange={setTargetType}
        onSave={saveRule}
      />
    </div>
  );
}
