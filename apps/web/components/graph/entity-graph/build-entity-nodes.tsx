import type { Node } from "@xyflow/react";
import { typeColor } from "@/lib/typeColor";
import { NODE_WIDTH, clippedLineStyle, hexToRgba } from "./visual-helpers";
import type { EntityNode, GraphMode } from "./types";

export function buildEntityNodes(
  shown: EntityNode[],
  typeIndex: Map<string, number>,
  selectedId: number | null,
  selectedNeighborIds: Set<number>,
  pathIds: Set<number>,
  expandedIds: Set<number>,
  graphMode: GraphMode,
  focusedEntityIds: Set<number> | null,
): Node[] {
  const hasSelection = selectedId !== null;
  const selectionContextActive = hasSelection;
  const focusActive = graphMode === "focused" && focusedEntityIds !== null && focusedEntityIds.size > 0;

  return shown.map((e) => {
    const idx = typeIndex.get(e.type) ?? 0;
    const color = typeColor(idx);
    const isSelected = selectedId === e.id;
    const isNeighbor = !isSelected && selectedNeighborIds.has(e.id);
    const pathHighlighted = !hasSelection && pathIds.size > 0 && pathIds.has(e.id);
    const isExpanded = expandedIds.has(e.id);
    const isContextNode = isSelected || isNeighbor;
    const isFocusMatched = focusActive && (focusedEntityIds?.has(e.id) ?? false);
    const isDimmed = selectionContextActive
      ? !isContextNode
      : focusActive && !isFocusMatched;
    const background = isSelected
      ? hexToRgba(color, 0.18)
      : isNeighbor
        ? hexToRgba(color, 0.08)
        : pathHighlighted
          ? "#fef3c7"
          : isFocusMatched
            ? hexToRgba(color, 0.08)
            : "#ffffff";
    const borderWidth = isSelected ? 4 : isNeighbor ? 3 : isExpanded ? 3 : 2;
    const typeLabelColor = isSelected ? "#0F1726" : isContextNode ? "#334155" : color;
    const nodeOpacity = selectionContextActive
      ? isSelected ? 1 : isNeighbor ? 0.96 : isDimmed ? 0.12 : 0.72
      : focusActive && !isFocusMatched ? 0.42 : 1;
    const boxShadow = isSelected
      ? `0 0 0 6px ${hexToRgba(color, 0.28)}, 0 14px 30px rgba(15, 23, 38, 0.18)`
      : isNeighbor
        ? `0 0 0 4px ${hexToRgba(color, 0.18)}, 0 8px 18px rgba(15, 23, 38, 0.12)`
        : pathHighlighted
          ? `0 0 0 3px ${hexToRgba(color, 0.18)}, 0 2px 8px rgba(0,0,0,0.12)`
          : isFocusMatched
            ? `0 0 0 3px rgba(45, 212, 191, 0.18), 0 4px 12px rgba(15, 23, 38, 0.08)`
          : isExpanded
            ? `0 0 0 3px ${hexToRgba(color, 0.16)}, 0 2px 8px rgba(0,0,0,0.10)`
            : "0 1px 4px rgba(0,0,0,0.08)";
    return {
      id: String(e.id),
      type: "default",
      data: {
        label: (
          <div style={{ textAlign: "center", lineHeight: 1.3, minWidth: 0, overflow: "hidden", width: "100%" }}>
            <div
              title={e.name}
              style={clippedLineStyle({
                fontWeight: isSelected || pathHighlighted ? 700 : 600,
                fontSize: 11,
                color: "#0F1726",
              })}
            >
              {e.name}
            </div>
            <div
              title={e.type}
              style={clippedLineStyle({ fontSize: 10, color: typeLabelColor, marginTop: 1 })}
            >
              {e.type}
            </div>
            {isExpanded && (
              <div style={{ fontSize: 9, color: "#64748b", marginTop: 2 }}>expanded</div>
            )}
          </div>
        ),
      },
      position: { x: 0, y: 0 },
      style: {
        background,
        border: `${borderWidth}px solid ${color}`,
        borderRadius: 8,
        padding: "6px 10px",
        width: NODE_WIDTH,
        overflow: "hidden",
        boxSizing: "border-box",
        boxShadow,
        opacity: nodeOpacity,
      },
    };
  });
}
