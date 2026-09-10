import { RefreshCw, Search, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { typeColor } from "@/lib/typeColor";
import { PathFinder } from "./PathFinder";
import type { EntityNode, GraphMode } from "./types";

export function GraphSidebar({
  graphMode,
  hasFocusSource,
  onResetOverview,
  onSetFocused,
  onSetFull,
  panelEntity,
  nameFilter,
  onNameFilterChange,
  allTypes,
  allEntities,
  typeFilter,
  onToggleType,
  onClearTypeFilter,
  visibleCount,
  edgesCount,
  onReload,
  showPathTools,
  showPath,
  onTogglePath,
  pathIds,
  onClearPath,
  workspaceId,
  onPath,
}: {
  graphMode: GraphMode;
  hasFocusSource: boolean;
  onResetOverview: () => void;
  onSetFocused: () => void;
  onSetFull: () => void;
  panelEntity: EntityNode | null;
  nameFilter: string;
  onNameFilterChange: (value: string) => void;
  allTypes: string[];
  allEntities: EntityNode[];
  typeFilter: Set<string>;
  onToggleType: (type: string) => void;
  onClearTypeFilter: () => void;
  visibleCount: number;
  edgesCount: number;
  onReload: () => void;
  showPathTools: boolean;
  showPath: boolean;
  onTogglePath: () => void;
  pathIds: Set<number>;
  onClearPath: () => void;
  workspaceId: number;
  onPath: (ids: number[]) => void;
}) {
  const modeButtonClass = (mode: GraphMode) => cn(
    "focus-ring rounded-lg border px-2.5 py-1.5 text-[11px] font-medium shadow-soft backdrop-blur-sm transition-colors",
    graphMode === mode
      ? "border-teal-200 bg-teal-50 text-teal-800"
      : "border-navy-100 bg-white/90 text-navy-700 hover:bg-navy-50",
  );

  return (
    <div className="absolute top-3 left-3 z-10 flex w-[248px] flex-col gap-2">
      <div className="rounded-xl border border-navy-100 bg-white/90 p-2 shadow-soft backdrop-blur-sm">
        <div className="mb-2 px-1 text-[10px] font-bold uppercase tracking-wider text-navy-500">Graph mode</div>
        <div className="flex flex-wrap gap-1">
          <button type="button" onClick={onResetOverview} className={modeButtonClass("overview")}>
            Overview
          </button>
          <button
            type="button"
            onClick={onSetFocused}
            disabled={!hasFocusSource}
            className={cn(modeButtonClass("focused"), !hasFocusSource && "opacity-50")}
          >
            Focused
          </button>
          <button type="button" onClick={onSetFull} className={modeButtonClass("full")}>
            Full View
          </button>
        </div>
      </div>

      {!panelEntity && graphMode !== "overview" && (
        <div className="flex items-center gap-2 rounded-xl border border-navy-100 bg-white/90 px-3 py-2 shadow-soft backdrop-blur-sm">
          <Search size={13} className="text-subtle" />
          <input
            value={nameFilter}
            onChange={(e) => onNameFilterChange(e.target.value)}
            placeholder="Search entities…"
            className="min-w-0 flex-1 bg-transparent text-[12px] text-navy-800 outline-none placeholder:text-subtle"
          />
          {nameFilter && (
            <button type="button" onClick={() => onNameFilterChange("")}
              className="text-subtle hover:text-navy-700"><X size={11} /></button>
          )}
        </div>
      )}

      {!panelEntity && graphMode !== "overview" && (
        <div className="rounded-xl border border-navy-100 bg-white/90 p-2 shadow-soft backdrop-blur-sm max-h-52 overflow-y-auto">
          <div className="mb-1 px-1 text-[10px] font-bold uppercase tracking-wider text-navy-500">Filter by type</div>
          {allTypes.map((t, i) => {
            const isSchemaOnly = !allEntities.some((e) => e.type === t);
            return (
              <button
                key={t}
                type="button"
                onClick={() => onToggleType(t)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg px-2 py-1 text-[11px] font-medium transition-colors",
                  typeFilter.size > 0 && !typeFilter.has(t) ? "text-subtle" : "text-navy-800",
                )}
              >
                <span className="size-2.5 rounded-full shrink-0"
                  style={{ background: isSchemaOnly ? "transparent" : typeColor(i), border: `2px ${isSchemaOnly ? "dashed" : "solid"} ${typeColor(i)}` }} />
                <span className={isSchemaOnly ? "italic text-subtle" : ""}>{t}</span>
              </button>
            );
          })}
          {typeFilter.size > 0 && (
            <button type="button" onClick={onClearTypeFilter}
              className="mt-1 w-full rounded-lg px-2 py-1 text-[10px] text-steel-600 hover:bg-steel-50">
              Clear filter
            </button>
          )}
        </div>
      )}

      {!panelEntity && (
        <div className="rounded-xl border border-navy-100 bg-white/90 px-3 py-2 shadow-soft backdrop-blur-sm text-[11px] text-subtle">
          {graphMode === "overview"
          ? `${visibleCount} overview node${visibleCount !== 1 ? "s" : ""} · ${edgesCount} overview rel${edgesCount !== 1 ? "s" : ""}`
          : `${visibleCount} / ${allEntities.length} entities · ${edgesCount} rel${edgesCount !== 1 ? "s" : ""}`}
        </div>
      )}

      {!panelEntity && (
        <div className="flex gap-1">
          <button type="button" onClick={onReload}
            className="focus-ring flex items-center gap-1 rounded-lg border border-navy-100 bg-white/90 px-2 py-1.5 text-[11px] text-navy-700 hover:bg-navy-50 shadow-soft backdrop-blur-sm">
            <RefreshCw size={11} /> Reload
          </button>
          {showPathTools && (
            <button type="button" onClick={onTogglePath}
              className={cn(
                "focus-ring flex items-center gap-1 rounded-lg border px-2 py-1.5 text-[11px] shadow-soft backdrop-blur-sm",
                showPath ? "border-steel-200 bg-steel-50 text-steel-700" : "border-navy-100 bg-white/90 text-navy-700 hover:bg-navy-50",
              )}>
              Path finder
            </button>
          )}
        </div>
      )}

      {!panelEntity && showPathTools && showPath && (
        <div className="rounded-xl border border-navy-100 bg-white/90 p-3 shadow-soft backdrop-blur-sm">
          <PathFinder
            entities={allEntities}
            workspaceId={workspaceId}
            onPath={onPath}
          />
          {pathIds.size > 0 && (
            <button type="button" onClick={onClearPath}
              className="mt-2 text-[10px] text-subtle hover:text-navy-700">
              Clear path
            </button>
          )}
        </div>
      )}
    </div>
  );
}
