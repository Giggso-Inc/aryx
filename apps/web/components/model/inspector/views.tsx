import { GitBranch } from "lucide-react";
import type { Axiom, Rule } from "@/lib/types";

export function AxiomsView({ axioms }: { axioms: Axiom[] }) {
  if (!axioms.length)
    return <Empty label="No axioms on this type yet." />;
  return (
    <ul className="space-y-2">
      {axioms.map((a) => (
        <li
          key={a.id}
          className="rounded-lg border border-navy-100 bg-navy-50/40 px-3 py-2 text-[12px]"
        >
          <div className="text-[10px] uppercase tracking-wider text-subtle">
            {a.kind}
          </div>
          <div className="font-mono text-navy-700">
            {JSON.stringify(a.payload)}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function RulesView({ rules }: { rules: Rule[] }) {
  if (!rules.length)
    return <Empty label="No inference rules yet." />;
  return (
    <ul className="space-y-2">
      {rules.map((r) => (
        <li
          key={r.name}
          className="rounded-lg border border-navy-100 bg-navy-50/40 px-3 py-2 text-[12px]"
        >
          <div className="flex items-center justify-between">
            <span className="font-semibold text-navy-800">{r.name}</span>
            <GitBranch
              size={11}
              className={r.enabled ? "text-emerald-500" : "text-subtle"}
            />
          </div>
          <div className="mt-1 font-mono text-[11px] text-navy-600">
            when <b>{r.attribute}</b> {r.operator} {r.value} →{" "}
            <b>{r.action}</b> {r.label || r.target_name || ""}
          </div>
        </li>
      ))}
    </ul>
  );
}

function Empty({ label }: { label: string }) {
  return (
    <div className="rounded-lg border border-dashed border-navy-200 px-4 py-6 text-center text-[12px] italic text-subtle">
      {label}
    </div>
  );
}
