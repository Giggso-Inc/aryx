/**
 * State, data loading, and mutation logic for WorkspaceIndexPage.
 *
 * Split out of WorkspaceIndexPage.tsx (2026-09; Raven Style Compliance
 * Plan Phase 8b line-count reduction).
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { getShayAccessToken, shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import { storeShaySession } from "@/lib/shay-session";
import type { ShayWorkspace } from "@/lib/shay-types";
import { workspaceSectionHref } from "@/lib/workspace-route";
import { useWorkspaceMetrics } from "./useWorkspaceMetrics";

export function useWorkspaceIndexPage() {
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

  const workspaceMetrics = useWorkspaceMetrics(workspaces, session?.access_token, session?.company_id);

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

  return {
    router,
    workspaces,
    query,
    setQuery,
    name,
    setName,
    description,
    setDescription,
    loading,
    saving,
    deletingWorkspaceId,
    error,
    modalError,
    setModalError,
    deleteError,
    setDeleteError,
    showCreateModal,
    setShowCreateModal,
    workspaceToDelete,
    setWorkspaceToDelete,
    workspaceToEdit,
    editName,
    setEditName,
    editDescription,
    setEditDescription,
    workspaceMetrics,
    filteredWorkspaces,
    resetModal,
    openEditModal,
    closeEditModal,
    saveEditedWorkspace,
    createWorkspace,
    deleteWorkspace,
  };
}
