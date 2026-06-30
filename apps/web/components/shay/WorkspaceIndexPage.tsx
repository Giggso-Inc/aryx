"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { FolderPlus, Search, X } from "lucide-react";
import { AuthGuard } from "./AuthGuard";
import {
  WorkspaceIndexCard,
  type WorkspaceCardMetrics,
} from "./WorkspaceIndexCard";
import { ShayPageShell } from "./ShayPageShell";
import { api } from "@/lib/api";
import { getShayAccessToken, shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import type { ShayWorkspace } from "@/lib/shay-types";
import { workspaceSectionHref } from "@/lib/workspace-route";

export function WorkspaceIndexPage() {
  const router = useRouter();
  const { session } = useShayAuth();
  const [workspaces, setWorkspaces] = useState<ShayWorkspace[]>([]);
  const [query, setQuery] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deletingWorkspaceId, setDeletingWorkspaceId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [modalError, setModalError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [workspaceToDelete, setWorkspaceToDelete] = useState<ShayWorkspace | null>(null);
  const [workspaceMetrics, setWorkspaceMetrics] = useState<Record<string, WorkspaceCardMetrics>>({});

  const load = async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const list = await shayApi.listWorkspaces(session.access_token);
      setWorkspaces(list.workspaces);
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to load workspaces.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [session?.access_token]);

  useEffect(() => {
    if (!session?.access_token || workspaces.length === 0) {
      setWorkspaceMetrics({});
      return;
    }

    let active = true;

    const loadMetrics = async () => {
      const metricResults = await Promise.allSettled(workspaces.map(async (workspace) => {
        const [members, datasources, bridge] = await Promise.all([
          shayApi.listWorkspaceMembers(workspace.id, session.access_token),
          shayApi.listDatasources(workspace.id, session.access_token),
          shayApi.ensureWorkspaceBridge({
            shay_workspace_id: workspace.id,
            name: workspace.name,
            description: workspace.description ?? "",
            company_id: session.company_id,
          }, session.access_token),
        ]);

        const summary = await api.dataSummary(bridge.aryx_workspace_id).catch(() => null);

        return [workspace.id, {
          users: members.total ?? members.members.length,
          entities: summary?.total_entities ?? null,
          entityTypes: summary?.type_count ?? null,
          dataSources: datasources.total ?? datasources.items.length,
        }] as const;
      }));

      if (!active) {
        return;
      }

      const nextMetrics: Record<string, WorkspaceCardMetrics> = {};
      metricResults.forEach((result) => {
        if (result.status !== "fulfilled") {
          return;
        }
        const [workspaceId, metrics] = result.value;
        nextMetrics[workspaceId] = metrics;
      });
      setWorkspaceMetrics(nextMetrics);
    };

    void loadMetrics();

    return () => {
      active = false;
    };
  }, [session?.access_token, session?.company_id, workspaces]);

  const filteredWorkspaces = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return workspaces;
    return workspaces.filter((workspace) => {
      const nameText = workspace.name.toLowerCase();
      const descriptionText = (workspace.description || "").toLowerCase();
      return nameText.includes(needle) || descriptionText.includes(needle);
    });
  }, [query, workspaces]);

  const resetModal = () => {
    setName("");
    setDescription("");
    setModalError(null);
    setShowCreateModal(false);
  };

  const createWorkspace = async () => {
    const accessToken = session?.access_token || getShayAccessToken();
    if (!accessToken || !session?.company_id || !name.trim()) {
      setModalError("Authentication required");
      return;
    }
    setSaving(true);
    setModalError(null);
    try {
      if (typeof window !== "undefined") {
        window.localStorage.setItem("aryx.shay.session", JSON.stringify({
          ...(session ?? {}),
          access_token: accessToken,
        }));
      }
      const workspace = await shayApi.createWorkspace({
        name: name.trim(),
        description: description.trim(),
      }, accessToken);
      await shayApi.ensureWorkspaceBridge({
        shay_workspace_id: workspace.id,
        name: workspace.name,
        description: workspace.description ?? "",
        company_id: session.company_id,
      }, accessToken);
      resetModal();
      router.push(workspaceSectionHref(workspace.id, "home"));
    } catch (nextError: unknown) {
      setModalError(nextError instanceof Error ? nextError.message : "Workspace creation failed.");
    } finally {
      setSaving(false);
    }
  };

  const deleteWorkspace = async () => {
    const accessToken = session?.access_token || getShayAccessToken();
    if (!workspaceToDelete || !accessToken) {
      setDeleteError("Authentication required");
      return;
    }
    setDeletingWorkspaceId(workspaceToDelete.id);
    setDeleteError(null);
    try {
      await shayApi.deleteWorkspace(workspaceToDelete.id, accessToken);
      setWorkspaceToDelete(null);
      await load();
    } catch (nextError: unknown) {
      setDeleteError(nextError instanceof Error ? nextError.message : "Workspace deletion failed.");
    } finally {
      setDeletingWorkspaceId(null);
    }
  };

  return (
    <AuthGuard>
      <ShayPageShell
        title="Workspaces"
        description="Create and manage workspaces."
        showHero={false}
      >
        <div className="space-y-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <label className="relative block w-full max-w-xl">
              <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-subtle" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search workspaces..."
                className="focus-ring w-full rounded-2xl border border-navy-100 bg-white py-3 pl-11 pr-4 text-sm text-navy-900 shadow-soft"
              />
            </label>
            <button
              type="button"
              onClick={() => {
                setModalError(null);
                setShowCreateModal(true);
              }}
              className="focus-ring inline-flex items-center justify-center gap-2 rounded-2xl bg-navy-800 px-5 py-3 text-sm font-semibold text-white shadow-soft hover:bg-navy-700"
            >
              <FolderPlus size={16} />
              New Workspace
            </button>
          </div>

          {loading ? (
            <div className="rounded-[1.5rem] border border-navy-100 bg-white px-5 py-12 text-center text-sm text-subtle shadow-soft">
              Loading Aryx workspaces...
            </div>
          ) : filteredWorkspaces.length === 0 ? (
            <div className="rounded-[1.75rem] border border-dashed border-navy-200 bg-white px-5 py-16 text-center shadow-soft">
              <div className="mx-auto max-w-md">
                <p className="text-lg font-semibold text-navy-900">
                  {workspaces.length === 0 ? "No workspaces yet." : "No workspaces match that search."}
                </p>
                <p className="mt-2 text-sm text-subtle">
                  {workspaces.length === 0
                    ? "Create the first workspace to start the Aryx bridge."
                    : "Try a different name or description keyword."}
                </p>
              </div>
            </div>
          ) : (
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {filteredWorkspaces.map((workspace) => (
                <WorkspaceIndexCard
                  key={workspace.id}
                  workspace={workspace}
                  metrics={workspaceMetrics[workspace.id]}
                  onOpen={() => router.push(workspaceSectionHref(workspace.id, "home"))}
                  onEdit={() => router.push(workspaceSectionHref(workspace.id, "settings"))}
                  onDelete={() => {
                    setDeleteError(null);
                    setWorkspaceToDelete(workspace);
                  }}
                />
              ))}
            </div>
          )}
        </div>

        {showCreateModal && (
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-navy-900/35 px-4">
            <div className="w-full max-w-lg rounded-[2rem] border border-navy-100 bg-white p-6 shadow-soft">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-2xl font-semibold text-navy-900">
                    Create a workspace
                  </h2>
                  <p className="mt-2 text-sm text-subtle">
                    Spin up a new Aryx workspace and bridge it into the shared runtime.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={resetModal}
                  className="focus-ring rounded-full border border-navy-100 p-2 text-navy-500 hover:bg-navy-50"
                  aria-label="Close create workspace dialog"
                >
                  <X size={16} />
                </button>
              </div>

              <div className="mt-6 space-y-4">
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Workspace name"
                  className="focus-ring w-full rounded-2xl border border-navy-100 bg-white px-4 py-3 text-sm text-navy-900"
                />
                <textarea
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  rows={5}
                  placeholder="What will this workspace own across auth, Aryx ingest, and Ask?"
                  className="focus-ring w-full resize-none rounded-2xl border border-navy-100 bg-white px-4 py-3 text-sm text-navy-900"
                />
                {modalError ? (
                  <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                    {modalError}
                  </div>
                ) : null}
              </div>

              <div className="mt-6 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={resetModal}
                  className="focus-ring rounded-2xl border border-navy-100 px-4 py-2.5 text-sm font-medium text-navy-700 hover:bg-navy-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={createWorkspace}
                  disabled={!name.trim() || saving}
                  className="focus-ring inline-flex items-center gap-2 rounded-2xl bg-navy-800 px-5 py-2.5 text-sm font-semibold text-white shadow-soft hover:bg-navy-700 disabled:opacity-50"
                >
                  <FolderPlus size={16} />
                  {saving ? "Creating..." : "Create Workspace"}
                </button>
              </div>
            </div>
          </div>
        )}

        {workspaceToDelete ? (
          <div className="fixed inset-0 z-[70] flex items-center justify-center bg-navy-900/35 px-4">
            <div className="w-full max-w-md rounded-[2rem] border border-navy-100 bg-white p-6 shadow-soft">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-2xl font-semibold text-navy-900">
                    Delete workspace
                  </h2>
                  <p className="mt-2 text-sm text-subtle">
                    Delete <span className="font-semibold text-navy-900">{workspaceToDelete.name}</span> from the workspace list.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setDeleteError(null);
                    setWorkspaceToDelete(null);
                  }}
                  className="focus-ring rounded-full border border-navy-100 p-2 text-navy-500 hover:bg-navy-50"
                  aria-label="Close delete workspace dialog"
                >
                  <X size={16} />
                </button>
              </div>

              <p className="mt-5 text-sm text-subtle">
                This action removes the workspace and cannot be undone from this screen.
              </p>

              {deleteError ? (
                <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                  {deleteError}
                </div>
              ) : null}

              <div className="mt-6 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => {
                    setDeleteError(null);
                    setWorkspaceToDelete(null);
                  }}
                  className="focus-ring rounded-2xl border border-navy-100 px-4 py-2.5 text-sm font-medium text-navy-700 hover:bg-navy-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={deleteWorkspace}
                  disabled={deletingWorkspaceId === workspaceToDelete.id}
                  className="focus-ring rounded-2xl bg-rose-600 px-5 py-2.5 text-sm font-semibold text-white shadow-soft hover:bg-rose-700 disabled:opacity-50"
                >
                  {deletingWorkspaceId === workspaceToDelete.id ? "Deleting..." : "Delete Workspace"}
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </ShayPageShell>
    </AuthGuard>
  );
}
