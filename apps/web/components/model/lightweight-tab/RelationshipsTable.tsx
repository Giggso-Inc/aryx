import type { OntologyRelationship } from "@/lib/types";

export function RelationshipsTable({ rels }: { rels: OntologyRelationship[] }) {
  return (
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
  );
}
