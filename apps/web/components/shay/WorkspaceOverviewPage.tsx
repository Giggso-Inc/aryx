"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Database, MessageSquareText, Settings2, Sparkles } from "lucide-react";
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
              <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-xl font-semibold text-navy-900">Workspace command center</h2>
                    <p className="mt-2 text-sm text-subtle">
                      Move between Aryx administration and graph work without leaving this workspace.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={openNewChat}
                      className="focus-ring inline-flex items-center gap-2 rounded-full bg-navy-800 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-700"
                    >
                      <Sparkles size={15} />
                      New Ask session
                    </button>
                    <Link
                      href={`/workspaces/${workspace.id}/settings`}
                      className="focus-ring inline-flex items-center gap-2 rounded-full border border-navy-100 px-4 py-2 text-sm font-medium text-navy-700 hover:bg-navy-50"
                    >
                      <Settings2 size={15} />
                      Workspace settings
                    </Link>
                  </div>
                </div>
                <div className="mt-5 grid gap-4 md:grid-cols-2">
                  <ActionCard
                    title="Workspace members"
                    description="Manage company users, membership roles, and shared access from the workspace settings tabs."
                    href={`/workspaces/${workspace.id}/settings?tab=members`}
                  />
                  <ActionCard
                    title="Apps and connections"
                    description="Attach workspace apps while preserving the Aryx bridge to downstream ingest and Ask."
                    href={`/workspaces/${workspace.id}/settings?tab=apps`}
                  />
                  <ActionCard
                    title="Data sources and ingest"
                    description="Register sources, then sync them into Aryx ingest with a workspace-aware datasource map."
                    href={`/workspaces/${workspace.id}/settings?tab=data-sources`}
                  />
                  <ActionCard
                    title="Admin hub"
                    description="Invite and manage company users who can participate in this shared workspace."
                    href="/admin/users"
                  />
                </div>
              </section>

              <section className="space-y-4">
                <div className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
                  <div className="flex items-center gap-2 text-sm font-semibold text-navy-900">
                    <Database size={15} />
                    Recent data sources
                  </div>
                  <div className="mt-4 space-y-3">
                    {datasources.slice(0, 4).map((datasource) => (
                      <div key={datasource.id} className="rounded-2xl border border-navy-100 px-4 py-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-medium text-navy-900">{datasource.name}</p>
                            <p className="mt-1 text-xs text-subtle">
                              {datasource.storage_type} · {datasource.provider || "manual"} · {datasource.processing_status}
                            </p>
                          </div>
                          <span className="rounded-full bg-navy-50 px-2.5 py-1 text-[11px] text-navy-700">
                            {datasource.is_connected ? "Connected" : "Draft"}
                          </span>
                        </div>
                      </div>
                    ))}
                    {datasources.length === 0 ? (
                      <p className="rounded-2xl border border-dashed border-navy-200 px-4 py-6 text-sm text-subtle">
                        No workspace data sources yet. Add the first one in workspace settings.
                      </p>
                    ) : null}
                  </div>
                </div>
              </section>
            </div>

            <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
              <div className="flex items-center gap-2 text-sm font-semibold text-navy-900">
                <MessageSquareText size={15} />
                Mapped chat sessions
              </div>
              <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {threads.map((thread) => (
                  <Link
                    key={thread.shay_thread_id}
                    href={`/workspaces/${workspace.id}/chats/${thread.shay_thread_id}`}
                    className="group rounded-[1.5rem] border border-navy-100 bg-canvas p-4 transition-colors hover:border-steel-300"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h3 className="text-base font-semibold text-navy-900">{thread.title}</h3>
                        <p className="mt-2 text-sm text-subtle">
                          {thread.turn_count} turn{thread.turn_count === 1 ? "" : "s"} · updated {new Date(thread.updated_at).toLocaleString()}
                        </p>
                      </div>
                      <ArrowRight size={16} className="text-subtle transition-transform group-hover:translate-x-1" />
                    </div>
                  </Link>
                ))}
                {threads.length === 0 ? (
                  <button
                    type="button"
                    onClick={openNewChat}
                    className="rounded-[1.5rem] border border-dashed border-navy-200 bg-canvas p-5 text-left text-sm text-subtle hover:border-steel-300"
                  >
                    Create the first Aryx Ask session for this workspace.
                  </button>
                ) : null}
              </div>
            </section>
          </div>
        ) : null}
      </ShayPageShell>
    </AuthGuard>
  );
}

function Metric({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-subtle">{label}</p>
      <p className="mt-3 text-2xl font-semibold text-navy-900">{value}</p>
      <p className="mt-2 text-sm text-subtle">{note}</p>
    </div>
  );
}

function ActionCard({
  title,
  description,
  href,
}: {
  title: string;
  description: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="group rounded-[1.5rem] border border-navy-100 bg-canvas p-4 transition-colors hover:border-steel-300"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-navy-900">{title}</h3>
          <p className="mt-2 text-sm text-subtle">{description}</p>
        </div>
        <ArrowRight size={16} className="text-subtle transition-transform group-hover:translate-x-1" />
      </div>
    </Link>
  );
}
