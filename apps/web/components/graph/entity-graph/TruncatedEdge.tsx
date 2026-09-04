import {
  BaseEdge, EdgeLabelRenderer, getSmoothStepPath,
  type EdgeProps, type EdgeTypes,
} from "@xyflow/react";
import { MAX_EDGE_LABEL_WIDTH, hexToRgba } from "./visual-helpers";
import type { TruncatedEdge } from "./types";

export function TruncatedSmoothStepEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  style,
  data,
  pathOptions,
}: EdgeProps<TruncatedEdge>) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    ...pathOptions,
  });
  const label = data?.label ?? "";

  return (
    <>
      <BaseEdge id={id} path={edgePath} markerEnd={markerEnd} style={style} />
      {label ? (
        <EdgeLabelRenderer>
          <div
            title={data?.title}
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              maxWidth: MAX_EDGE_LABEL_WIDTH,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              borderRadius: 6,
              background: hexToRgba(data?.labelBackground ?? "#ffffff", data?.labelBackgroundOpacity ?? 1),
              opacity: data?.labelOpacity,
              padding: "2px 4px",
              color: data?.labelColor,
              fontSize: 10,
              fontWeight: data?.labelFontWeight,
              lineHeight: 1.2,
              pointerEvents: "all",
            }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

export const edgeTypes: EdgeTypes = {
  truncatedSmoothstep: TruncatedSmoothStepEdge,
};
