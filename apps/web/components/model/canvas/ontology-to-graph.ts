import type { Edge, Node } from "@xyflow/react";
import type { OntologyDoc } from "@/lib/types";
import type { EntityTypeNodeData } from "../EntityTypeNode";

export function ontologyToGraph(doc: OntologyDoc): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = (doc.types || []).map((t) => ({
    id: t.name,
    type: "entityType",
    position: { x: 0, y: 0 },
    data: {
      label: t.name,
      attributes: t.attributes || [],
      status: t.status || "approved",
      instanceCount: t.instance_count,
      parent: t.parent_type ?? null,
    } satisfies EntityTypeNodeData,
  }));
  const known = new Set(nodes.map((n) => n.id));
  const edges: Edge[] = [];
  for (const t of doc.types || []) {
    if (t.parent_type && known.has(t.parent_type)) {
      edges.push({
        id: `subClassOf::${t.name}::${t.parent_type}`,
        source: t.parent_type,
        target: t.name,
        label: "subClassOf",
        animated: false,
        style: { stroke: "#94A8CB", strokeDasharray: "4 4" },
      });
    }
  }
  for (const r of doc.relationships || []) {
    if (!r.source_type || !r.target_type) continue;
    if (!known.has(r.source_type) || !known.has(r.target_type)) continue;
    edges.push({
      id: `rel::${r.source_type}::${r.name}::${r.target_type}`,
      source: r.source_type,
      target: r.target_type,
      label: r.name,
      style: { stroke: "#4068A8" },
      // Carry the declared-relationship row id (if any) so an edge click
      // can DELETE the right row. Subclass + entity-derived edges have no id.
      data: r.id ? { relId: r.id } : undefined,
    });
  }
  return { nodes, edges };
}
