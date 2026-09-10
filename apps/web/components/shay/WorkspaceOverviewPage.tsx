"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AuthGuard } from "./AuthGuard";
import { ShayPageShell } from "./ShayPageShell";
import { ShayWorkspaceTabs } from "./ShayWorkspaceTabs";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import { workspaceSectionHref } from "@/lib/workspace-route";
import { formatWorkspaceName } from "@/lib/workspace-name";
import type {
  ShayBridgeThread,
  ShayBridgeWorkspaceMap,
  ShayDatasource,
  ShayWorkspace,
} from "@/lib/shay-types";
import { ChatSessionsPanel } from "./workspace-overview/ChatSessionsPanel";
import { CommandCenter } from "./workspace-overview/CommandCenter";
import { DataSourcesPanel } from "./workspace-overview/DataSourcesPanel";
import { Metric } from "./workspace-overview/shared";

export function WorkspaceOverviewPage({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const { session } = useShayAuth();
  const [workspace, setWorkspace] = useState<ShayWorkspace | null>(null);
  const [mapping, setMapping] = useState<ShayBridgeWorkspaceMap | null>(null);
  const [datasources, setDatasources] = useState<ShayDatasource[]>([]);
  const [threads, setThreads] = useState<ShayBridgeThread[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session) return;
    let active = true;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const nextWorkspace = await shayApi.getWorkspace(workspaceId, session.access_token);
        const bridge = nextWorkspace.bridge ?? null;
        const resolvedWorkspaceId = nextWorkspace.id;
        const [datasourceList, threadList] = await Promise.all([
          shayApi.listDatasources(resolvedWorkspaceId, session.access_token),
          shayApi.listBridgeThreads(resolvedWorkspaceId),
        ]);
        if (!active) return;
        if (resolvedWorkspaceId !== workspaceId) {
          router.replace(workspaceSectionHref(resolvedWorkspaceId, "home"));
        }
        setWorkspace(nextWorkspace);
        setMapping(bridge);
        setDatasources(datasourceList.items);
        setThreads(threadList);
      } catch (nextError: unknown) {
        if (!active) return;
        setError(nextError instanceof Error ? nextError.message : "Unable to load workspace.");
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [router, session?.access_token, workspaceId]);

  const openNewChat = () => {
    const resolvedWorkspaceId = workspace?.id ?? workspaceId;
    router.push(`/workspaces/${resolvedWorkspaceId}/chats/${crypto.randomUUID()}`);
  };

  return (
    <AuthGuard>
      <ShayPageShell
        eyebrow="Workspace bridge"
        title={workspace ? formatWorkspaceName(workspace.name) : "Workspace"}
        description={workspace?.description || "This workspace is bridged to Aryx so data sources, Ask sessions, and workspace controls run from one mapped surface."}
        actions={workspace ? <ShayWorkspaceTabs workspaceId={workspace.id} /> : undefined}
        contentWidth="detail"
      >
        {loading ? (
          <div className="rounded-[1.5rem] border border-navy-100 bg-white px-5 py-12 text-center text-sm text-subtle shadow-soft">
            Loading workspace bridge...
          </div>
        ) : error ? (
          <div className="rounded-[1.5rem] border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-700">
            {error}
          </div>
        ) : workspace ? (
          <div className="space-y-6">
            <div className="grid gap-4 md:grid-cols-4">
              <Metric label="Workspace" value={workspace.id.slice(0, 8)} note="User-facing source of truth" />
              <Metric label="Aryx workspace" value={String(mapping?.aryx_workspace_id ?? "—")} note="Mapped ingest and Ask runtime" />
              <Metric label="Data sources" value={String(datasources.length)} note="Unified Aryx surface" />
              <Metric label="Chat sessions" value={String(threads.length)} note="Mapped to Aryx Ask" />
            </div>

            <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_380px]">
              <CommandCenter workspaceId={workspace.id} onNewChat={openNewChat} />
              <DataSourcesPanel datasources={datasources} />
            </div>

            <ChatSessionsPanel workspaceId={workspace.id} threads={threads} onNewChat={openNewChat} />
          </div>
        ) : null}
      </ShayPageShell>
    </AuthGuard>
  );
}
