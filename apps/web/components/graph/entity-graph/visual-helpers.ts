import type { CSSProperties } from "react";

export const NODE_WIDTH = 160;
export const OVERVIEW_NODE_WIDTH = 190;
export const MAX_EDGE_LABEL_WIDTH = 180;

export const clippedTextStyle: CSSProperties = {
  display: "block",
  maxWidth: "100%",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

export function clippedLineStyle(style: CSSProperties): CSSProperties {
  return { ...clippedTextStyle, ...style };
}

export function hexToRgba(hex: string, alpha: number): string {
  const normalized = hex.replace("#", "");
  const safeHex = normalized.length === 3
    ? normalized.split("").map((char) => `${char}${char}`).join("")
    : normalized;
  const int = Number.parseInt(safeHex, 16);
  const r = (int >> 16) & 255;
  const g = (int >> 8) & 255;
  const b = int & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
