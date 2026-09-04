import { CheckCircle2, Loader2 } from "lucide-react";
import type { OntologyType } from "@/lib/types";

export function PendingReviewTable({
  proposed,
  approving,
  onApprove,
}: {
  proposed: OntologyType[];
  approving: string | null;
  onApprove: (name: string) => void;
}) {
  return (
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
                    onClick={() => onApprove(t.name)}
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
  );
}
