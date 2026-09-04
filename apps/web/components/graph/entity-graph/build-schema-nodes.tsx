import type { Node } from "@xyflow/react";
import { typeColor } from "@/lib/typeColor";
import { NODE_WIDTH, clippedLineStyle } from "./visual-helpers";

export function buildSchemaOnlyNodes(
  schemaOnlyTypes: string[],
  instanceTypeNames: Set<string>,
  typeSet: Set<string>,
  nameFilter: string,
  typeIndex: Map<string, number>,
): Node[] {
  const nodes: Node[] = [];
  for (const typeName of schemaOnlyTypes) {
    if (instanceTypeNames.has(typeName)) continue;
    if (typeSet.size > 0 && !typeSet.has(typeName)) continue;
    if (nameFilter !== "" && !typeName.toLowerCase().includes(nameFilter.toLowerCase())) continue;
    const idx = typeIndex.get(typeName) ?? 0;
    const color = typeColor(idx);
    nodes.push({
      id: `schema::${typeName}`,
      type: "default",
      data: {
        label: (
          <div style={{ textAlign: "center", lineHeight: 1.3, minWidth: 0, overflow: "hidden", width: "100%" }}>
            <div
              title={typeName}
              style={clippedLineStyle({
                fontWeight: 500,
                fontSize: 11,
                color: "#64748b",
                fontStyle: "italic",
              })}
            >
              {typeName}
            </div>
            <div style={{ fontSize: 9, color, marginTop: 1, opacity: 0.7 }}>
              no instances yet
            </div>
          </div>
        ),
      },
      position: { x: 0, y: 0 },
      style: {
        background: "#f8fafc",
        border: `2px dashed ${color}`,
        borderRadius: 8,
        padding: "6px 10px",
        width: NODE_WIDTH,
        overflow: "hidden",
        boxSizing: "border-box",
        boxShadow: "none",
        opacity: 0.75,
      },
    });
  }
  return nodes;
}
