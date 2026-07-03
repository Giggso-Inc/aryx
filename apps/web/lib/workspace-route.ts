"use client";

import { useMemo } from "react";
import { usePathname } from "next/navigation";

export interface WorkspaceScope {
  shayWorkspaceId: string | null;
  section: WorkspaceSection | null;
}

export const WORKSPACE_TABS = [
  { label: "Home", section: "home" },
  { label: "Brief", section: "brief" },
  { label: "Ingest", section: "ingest" },
  { label: "Data", section: "data" },
  { label: "Graph", section: "graph" },
  { label: "Ontology", section: "ontology" },
  { label: "Ask", section: "ask" },
  { label: "Observability", section: "observability" },
  { label: "Settings", section: "settings" },
] as const;

export type WorkspaceSection = typeof WORKSPACE_TABS[number]["section"];

const WORKSPACE_SECTIONS = new Set<WorkspaceSection>(
  WORKSPACE_TABS.map((tab) => tab.section),
);

function asWorkspaceSection(value?: string | null): WorkspaceSection | null {
  if (!value || !WORKSPACE_SECTIONS.has(value as WorkspaceSection)) {
    return null;
  }
  return value as WorkspaceSection;
}

export function parseWorkspaceScope(pathname?: string | null): WorkspaceScope {
  if (!pathname) {
    return { shayWorkspaceId: null, section: null };
  }

  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] !== "workspaces" || !parts[1]) {
    return { shayWorkspaceId: null, section: null };
  }

  if (parts[2] === "chats") {
    return {
      shayWorkspaceId: parts[1],
      section: "ask",
    };
  }

  if (parts[2] === "model") {
    return {
      shayWorkspaceId: parts[1],
      section: "ontology",
    };
  }

  return {
    shayWorkspaceId: parts[1],
    section: asWorkspaceSection(parts[2]) ?? "home",
  };
}

export function workspaceSectionHref(
  shayWorkspaceId: string,
  section: WorkspaceSection,
) {
  return `/workspaces/${shayWorkspaceId}/${section}`;
}

export function workspaceModelHref(shayWorkspaceId: string) {
  return `/workspaces/${shayWorkspaceId}/model`;
}

export function workspaceStartHref(shayWorkspaceId: string) {
  return `/workspaces/${shayWorkspaceId}/start`;
}

export function useWorkspaceScope() {
  const pathname = usePathname();
  return useMemo(() => parseWorkspaceScope(pathname), [pathname]);
}

export function useWorkspaceAwareHref(
  fallbackHref: string,
  section: WorkspaceSection,
) {
  const { shayWorkspaceId } = useWorkspaceScope();

  return useMemo(() => {
    if (!shayWorkspaceId) {
      return fallbackHref;
    }
    return workspaceSectionHref(shayWorkspaceId, section);
  }, [fallbackHref, section, shayWorkspaceId]);
}
