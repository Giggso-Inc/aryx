"use client";

import type { KeyboardEvent } from "react";
import { Database, PencilLine, Shapes, Trash2, Users2, Workflow } from "lucide-react";
import type { ShayWorkspace } from "@/lib/shay-types";
import { formatWorkspaceName } from "@/lib/workspace-name";
import { ActionIcon, MetricTile } from "./workspace-index-card/shared";

export interface WorkspaceCardMetrics {
  users: number | null;
  entities: number | null;
  entityTypes: number | null;
  dataSources: number | null;
}

export function WorkspaceIndexCard({
  workspace,
  metrics,
  onOpen,
  onEdit,
  onDelete,
}: {
  workspace: ShayWorkspace;
  metrics?: WorkspaceCardMetrics;
  onOpen: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const displayName = formatWorkspaceName(workspace.name);
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    event.preventDefault();
    onOpen();
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={handleKeyDown}
      className="group flex h-full flex-col rounded-[1.75rem] border border-navy-100 bg-white p-6 text-left shadow-soft transition-all hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className="flex min-w-0 items-start justify-between gap-4">
        <h3
          title={displayName}
          className="min-w-0 flex-1 truncate text-2xl font-semibold text-navy-900"
        >
          {displayName}
        </h3>
        <div className="flex items-center gap-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          <ActionIcon
            label={`Edit ${displayName}`}
            onClick={(event) => {
              event.stopPropagation();
              onEdit();
            }}
          >
            <PencilLine size={16} />
          </ActionIcon>
          <ActionIcon
            label={`Delete ${displayName}`}
            onClick={(event) => {
              event.stopPropagation();
              onDelete();
            }}
            tone="danger"
          >
            <Trash2 size={16} />
          </ActionIcon>
        </div>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        <MetricTile
          icon={<Users2 size={16} />}
          label="Users"
          value={metrics?.users}
        />
        <MetricTile
          icon={<Database size={16} />}
          label="Data sources"
          value={metrics?.dataSources}
        />
        <MetricTile
          icon={<Workflow size={16} />}
          label="Entities"
          value={metrics?.entities}
        />
        <MetricTile
          icon={<Shapes size={16} />}
          label="Entity types"
          value={metrics?.entityTypes}
        />
      </div>

      <div className="mt-auto pt-6">
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onOpen();
          }}
          className="focus-ring inline-flex w-full items-center justify-center rounded-2xl bg-navy-800 px-5 py-3 text-sm font-semibold text-white shadow-soft transition-colors hover:bg-navy-700"
        >
          View Workspace
        </button>
      </div>
    </div>
  );
}
