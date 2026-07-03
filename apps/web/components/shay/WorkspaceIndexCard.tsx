"use client";

import type { KeyboardEvent, MouseEvent, ReactNode } from "react";
import { Database, PencilLine, Shapes, Trash2, Users2, Workflow } from "lucide-react";
import type { ShayWorkspace } from "@/lib/shay-types";
import { formatWorkspaceName } from "@/lib/workspace-name";

export interface WorkspaceCardMetrics {
  users: number | null;
  entities: number | null;
  entityTypes: number | null;
  dataSources: number | null;
}

const numberFormatter = new Intl.NumberFormat("en-US");

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
      className="group rounded-[1.75rem] border border-navy-100 bg-white p-6 text-left shadow-soft transition-all hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-4">
        <h3 className="text-2xl font-semibold text-navy-900">{displayName}</h3>
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

      <div className="mt-6">
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

function ActionIcon({
  children,
  label,
  onClick,
  tone = "default",
}: {
  children: ReactNode;
  label: string;
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
  tone?: "default" | "danger";
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className={`focus-ring rounded-full border p-2 transition-colors ${
        tone === "danger"
          ? "border-rose-100 text-rose-600 hover:bg-rose-50"
          : "border-navy-100 text-navy-500 hover:bg-navy-50"
      }`}
    >
      {children}
    </button>
  );
}

function MetricTile({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: number | null | undefined;
}) {
  return (
    <div className="rounded-[1.35rem] border border-navy-100 bg-[linear-gradient(90deg,_rgba(64,104,168,0.06),_rgba(255,255,255,0.96))] px-4 py-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-steel-700">
          {label}
        </span>
        <span className="text-steel-600">{icon}</span>
      </div>
      <div className="mt-4 text-3xl font-semibold leading-none text-navy-900">
        {formatMetric(value)}
      </div>
    </div>
  );
}

function formatMetric(value: number | null | undefined) {
  if (typeof value !== "number") {
    return "--";
  }
  return numberFormatter.format(value);
}
