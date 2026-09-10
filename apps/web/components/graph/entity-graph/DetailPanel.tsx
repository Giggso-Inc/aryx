import { GitMerge, Loader2, X } from "lucide-react";
import type { EntityNode, NeighborNode } from "./types";

interface DetailPanelProps {
  entity: EntityNode;
  neighbors: NeighborNode[];
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onNavigate: (neighbor: NeighborNode) => void;
  onExpandOnCanvas: (entityId: number, neighbors: NeighborNode[]) => void;
}

function formatAttributeValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function DetailPanel({
  entity,
  neighbors,
  loading,
  error,
  onClose,
  onNavigate,
  onExpandOnCanvas,
}: DetailPanelProps) {
  const attributes = entity.attributes ?? {};
  const hasAttributes = Object.keys(attributes).length > 0;

  return (
    <div className="absolute right-0 top-0 bottom-0 z-10 w-72 border-l border-navy-100 bg-white shadow-soft flex flex-col">
      <div className="flex items-start justify-between gap-2 border-b border-navy-100 px-4 py-3">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-steel-500">{entity.type}</div>
          <h3 className="truncate font-semibold text-navy-900">{entity.name}</h3>
          <div className="text-[10px] text-subtle">id:{entity.id}</div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {!loading && neighbors.length > 0 && (
            <button
              type="button"
              title="Show all connections for this node on the canvas"
              onClick={() => onExpandOnCanvas(entity.id, neighbors)}
              className="focus-ring flex items-center gap-1 rounded-md border border-steel-200 bg-steel-50 px-2 py-1 text-[10px] font-medium text-steel-700 hover:bg-steel-100"
            >
              <GitMerge size={10} />
              Expand
            </button>
          )}
          <button type="button" onClick={onClose}
            className="focus-ring rounded-md p-1 text-subtle hover:bg-navy-50">
            <X size={14} />
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        <div>
          <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-navy-500">Attributes</div>
          {loading && !hasAttributes ? (
            <div className="flex items-center gap-1 text-[12px] text-subtle">
              <Loader2 size={11} className="animate-spin" />Loading details…
            </div>
          ) : hasAttributes ? (
            <div className="space-y-1">
              {Object.entries(attributes).map(([k, v]) => (
                <div key={k} className="rounded-lg bg-navy-50 px-2.5 py-1.5">
                  <div className="text-[10px] text-subtle">{k}</div>
                  <div className="whitespace-pre-wrap break-words text-[12px] text-navy-800">
                    {formatAttributeValue(v)}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-navy-100 bg-navy-50/50 px-2.5 py-2 text-[12px] italic text-subtle">
              No attributes available for this node.
            </div>
          )}
        </div>
        <div>
          <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-navy-500">
            Neighbors {loading ? "…" : `(${neighbors.length})`}
          </div>
          {loading ? (
            <div className="flex items-center gap-1 text-[12px] text-subtle">
              <Loader2 size={11} className="animate-spin" />Loading…
            </div>
          ) : error ? (
            <div className="rounded-lg border border-rose-100 bg-rose-50 px-2.5 py-2 text-[12px] text-rose-700">
              {error}
            </div>
          ) : neighbors.length === 0 ? (
            <div className="text-[12px] text-subtle italic">No connections</div>
          ) : (
            <ul className="space-y-1">
              {neighbors.map((n) => (
                <li key={`${n.id}-${n.relationship}-${n.direction}`}>
                  <button
                    type="button"
                    onClick={() => onNavigate(n)}
                    className="focus-ring w-full rounded-lg border border-navy-100 px-2.5 py-1.5 text-left hover:bg-navy-50"
                  >
                    <div className="text-[10px] text-steel-500">{n.type} · {n.relationship}</div>
                    <div className="truncate text-[12px] font-medium text-navy-800">{n.name}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
