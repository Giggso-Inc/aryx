import { Loader2, Trash2 } from "lucide-react";
import type { OntologyType } from "@/lib/types";

export function ApprovedTypesTable({
  approved,
  deleting,
  onDelete,
}: {
  approved: OntologyType[];
  deleting: string | null;
  onDelete: (name: string) => void;
}) {
  return (
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
                      onClick={() => onDelete(t.name)}
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
  );
}
