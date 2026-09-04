"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { FolderPlus, Search } from "lucide-react";
import { AuthGuard } from "./AuthGuard";
import {
  WorkspaceIndexCard,
  type WorkspaceCardMetrics,
} from "./WorkspaceIndexCard";
import { WorkspaceProfileDialog } from "./WorkspaceProfileDialog";
import { ShayPageShell } from "./ShayPageShell";
import { api } from "@/lib/api";
import { getShayAccessToken, shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import { storeShaySession } from "@/lib/shay-session";
import type { ShayWorkspace } from "@/lib/shay-types";
import { workspaceSectionHref } from "@/lib/workspace-route";
import { CreateWorkspaceModal } from "./workspace-index/CreateWorkspaceModal";
import { DeleteWorkspaceModal } from "./workspace-index/DeleteWorkspaceModal";
import { resolveWorkspaceDataSourceCount } from "./workspace-index/resolve-source-count";

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
  const [workspaceToEdit, setWorkspaceToEdit] = useState<ShayWorkspace | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
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
        const aryxWorkspaceId = workspace.bridge?.aryx_workspace_id;
        const [membersResult, datasourcesResult, groupedSourcesResult, summaryResult] = await Promise.allSettled([
          shayApi.listWorkspaceMembers(workspace.id, session.access_token),
          shayApi.listDatasources(workspace.id, session.access_token),
          aryxWorkspaceId
            ? api.listDataSources(aryxWorkspaceId)
            : Promise.resolve(null),
          aryxWorkspaceId
            ? api.dataSummary(aryxWorkspaceId)
            : Promise.resolve(null),
        ]);
        const members = membersResult.status === "fulfilled" ? membersResult.value : null;
        const datasources = datasourcesResult.status === "fulfilled" ? datasourcesResult.value : null;
        const groupedSources = groupedSourcesResult.status === "fulfilled" ? groupedSourcesResult.value : null;
        const summary = summaryResult.status === "fulfilled" ? summaryResult.value : null;

        return [workspace.id, {
          users: members?.total ?? members?.members.length ?? null,
          entities: summary?.total_entities ?? null,
          entityTypes: summary?.type_count ?? null,
          dataSources: resolveWorkspaceDataSourceCount({
            summarySourceCount: summary?.sources.length ?? null,
            catalogSourceCount: groupedSources?.length ?? null,
            datasourceTotal: datasources?.total ?? null,
            datasourceItemsCount: datasources?.items.length ?? null,
          }),
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

  const openEditModal = (workspace: ShayWorkspace) => {
    setWorkspaceToEdit(workspace);
    setEditName(workspace.name);
    setEditDescription(workspace.description ?? "");
    setModalError(null);
  };

  const closeEditModal = () => {
    setWorkspaceToEdit(null);
    setEditName("");
    setEditDescription("");
    setModalError(null);
  };

  const saveEditedWorkspace = async () => {
    if (!workspaceToEdit || !session?.company_id) {
      setModalError("Authentication required");
      return;
    }
    const accessToken = session.access_token || getShayAccessToken();
    if (!accessToken) {
      setModalError("Authentication required");
      return;
    }
    setSaving(true);
    setModalError(null);
    try {
      const updated = await shayApi.updateWorkspace(
        workspaceToEdit.id,
        { name: editName.trim(), description: editDescription.trim() },
        accessToken,
      );
      setWorkspaces((current) =>
        current.map((workspace) => (workspace.id === updated.id ? updated : workspace)),
      );
      closeEditModal();
    } catch (nextError: unknown) {
      setModalError(nextError instanceof Error ? nextError.message : "Workspace save failed.");
    } finally {
      setSaving(false);
    }
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
      storeShaySession({
        ...(session ?? {}),
        access_token: accessToken,
      });
      const workspace = await shayApi.createWorkspace({
        name: name.trim(),
        description: description.trim(),
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
        contentWidth="wide"
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
                  onEdit={() => openEditModal(workspace)}
                  onDelete={() => {
                    setDeleteError(null);
                    setWorkspaceToDelete(workspace);
                  }}
                />
              ))}
            </div>
          )}
        </div>

        <CreateWorkspaceModal
          open={showCreateModal}
          name={name}
          description={description}
          modalError={modalError}
          saving={saving}
          onNameChange={setName}
          onDescriptionChange={setDescription}
          onClose={resetModal}
          onCreate={() => void createWorkspace()}
        />

        <DeleteWorkspaceModal
          workspace={workspaceToDelete}
          deleteError={deleteError}
          deleting={Boolean(workspaceToDelete && deletingWorkspaceId === workspaceToDelete.id)}
          onClose={() => {
            setDeleteError(null);
            setWorkspaceToDelete(null);
          }}
          onConfirm={() => void deleteWorkspace()}
        />

        {workspaceToEdit ? (
          <WorkspaceProfileDialog
            description={editDescription}
            error={modalError}
            name={editName}
            onClose={closeEditModal}
            onDescriptionChange={setEditDescription}
            onNameChange={setEditName}
            onSave={saveEditedWorkspace}
            saving={saving}
            title="Edit workspace"
            descriptionText="Update the workspace name and description directly from the workspace library."
          />
        ) : null}
      </ShayPageShell>
    </AuthGuard>
  );
}
