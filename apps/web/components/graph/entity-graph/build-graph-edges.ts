import { MarkerType, type Edge } from "@xyflow/react";
import type { EntityRel, GraphMode, TruncatedEdgeData } from "./types";

export function edgeKey(source: number, target: number, name: string): string {
  return `${source}->${target}:${name}`;
}

export function edgePairKey(source: number, target: number): string {
  return `${Math.min(source, target)}::${Math.max(source, target)}`;
}

export function buildGraphEdges(
  rels: EntityRel[],
  shownIds: Set<number>,
  selectedId: number | null,
  selectedEdgeKeys: Set<string>,
  pathIds: Set<number>,
  graphMode: GraphMode,
  focusedEntityIds: Set<number> | null,
  focusedEdgePairs: Set<string>,
  selectedAccentColor: string,
): Edge[] {
  const hasSelection = selectedId !== null;
  const selectionContextActive = hasSelection;
  const focusActive = graphMode === "focused" && focusedEntityIds !== null && focusedEntityIds.size > 0;

  return rels
    .filter((r) => shownIds.has(r.source) && shownIds.has(r.target))
    .map((r, i) => {
      const selectedEdge = hasSelection && selectedEdgeKeys.has(edgeKey(r.source, r.target, r.name));
      const highlighted = !hasSelection && pathIds.has(r.source) && pathIds.has(r.target);
      const focusHighlighted = focusActive &&
        (focusedEntityIds?.has(r.source) ?? false) &&
        (focusedEntityIds?.has(r.target) ?? false) &&
        focusedEdgePairs.has(edgePairKey(r.source, r.target));
      const stroke = selectedEdge
        ? selectedAccentColor
        : highlighted
          ? "#D97706"
          : focusHighlighted
            ? "#0F9D8B"
            : "#4068A8";
      return {
        id: `e${r.source}-${r.target}-${i}`,
        source: String(r.source),
        target: String(r.target),
        type: "truncatedSmoothstep",
        animated: selectedEdge || highlighted || focusHighlighted,
        style: {
          stroke,
          strokeWidth: selectedEdge ? 3.8 : highlighted ? 2.5 : focusHighlighted ? 2.3 : 1.5,
          opacity: selectionContextActive ? (selectedEdge ? 1 : 0.1) : focusActive && !focusHighlighted ? 0.18 : 1,
        },
        data: {
          label: r.name,
          title: r.name,
          labelColor: selectedEdge ? "#0F1726" : "#334155",
          labelFontWeight: selectedEdge ? 700 : 500,
          labelOpacity: selectionContextActive ? (selectedEdge ? 1 : 0.18) : focusActive && !focusHighlighted ? 0.38 : 1,
          labelBackground: selectedEdge ? "#ffffff" : "#f8fafc",
          labelBackgroundOpacity: selectionContextActive ? (selectedEdge ? 0.98 : 0.18) : focusActive && !focusHighlighted ? 0.4 : 0.9,
        } satisfies TruncatedEdgeData,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: stroke,
          width: 14,
          height: 14,
        },
      };
    });
}
