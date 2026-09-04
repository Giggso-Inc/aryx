import { Loader2, Play, ToggleLeft, ToggleRight, Trash2 } from "lucide-react";
import { cn } from "@/lib/cn";
import type { Rule } from "@/lib/types";

export function RulesList({
  rules,
  loading,
  evaluating,
  onToggle,
  onDelete,
  onEvaluate,
}: {
  rules: Rule[];
  loading: boolean;
  evaluating: boolean;
  onToggle: (rule: Rule) => void;
  onDelete: (rule: Rule) => void;
  onEvaluate: () => void;
}) {
  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[12px] font-bold uppercase tracking-[0.1em] text-navy-500">
          Active rules ({rules.length})
        </h3>
        <button
          type="button"
          onClick={onEvaluate}
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
                      <button type="button" onClick={() => onToggle(r)}
                        className="focus-ring rounded-md p-1 text-steel-600 hover:bg-steel-50"
                        title={r.enabled ? "Disable" : "Enable"}>
                        {r.enabled ? <ToggleRight size={14} /> : <ToggleLeft size={14} />}
                      </button>
                      <button type="button" onClick={() => onDelete(r)}
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
  );
}
