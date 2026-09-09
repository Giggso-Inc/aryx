/**
 * Write-path mutation handlers for WorkspaceSettingsPage (save profile,
 * member add/update/remove, purge/delete workspace).
 *
 * Split out of WorkspaceSettingsPage.tsx (2026-09; Raven Style
 * Compliance Plan Phase 8b line-count reduction). Takes the
 * useWorkspaceSettingsState() return value so both hooks share one
 * source of truth for state.
 */

import { shayApi } from "@/lib/shay-api";
import { formatWorkspaceName } from "@/lib/workspace-name";
import type { ShayWorkspaceMember } from "@/lib/shay-types";
import type { useWorkspaceSettingsState } from "./useWorkspaceSettingsState";

export function useWorkspaceSettingsActions(state: ReturnType<typeof useWorkspaceSettingsState>) {
  const {
    router, session, workspaceId, workspace, setWorkspace, bridge,
    canManageWorkspace, draftName, draftDescription,
    setError, setNotice, setSavingProfile, setEditProfileOpen,
    setMemberBusy, setAddMemberOpen, load,
    setPurging, setDeleting, setDangerError, setDangerNotice,
  } = state;

  const saveWorkspace = async () => {
    if (!session || !workspace || !canManageWorkspace) return;
    setSavingProfile(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await shayApi.updateWorkspace(
        workspace.id,
        { name: draftName, description: draftDescription },
        session.access_token,
      );
      setWorkspace(updated);
      state.setBridge(updated.bridge ?? null);
      setNotice("Workspace profile saved.");
      setEditProfileOpen(false);
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to save workspace.");
    } finally {
      setSavingProfile(false);
    }
  };

  const addMember = async (userId: string, role: string) => {
    if (!session || !userId || !canManageWorkspace) return;
    setMemberBusy(`add:${userId}`);
    setError(null);
    setNotice(null);
    try {
      await shayApi.addWorkspaceMember(
        workspaceId,
        { user_id: userId, role },
        session.access_token,
      );
      setAddMemberOpen(false);
      setNotice("Workspace member added.");
      await load();
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to add member.");
    } finally {
      setMemberBusy(null);
    }
  };

  const updateMemberRole = async (userId: string, role: string) => {
    if (!session || !canManageWorkspace || userId === session.user_id) return;
    setMemberBusy(`role:${userId}`);
    setError(null);
    setNotice(null);
    try {
      await shayApi.updateWorkspaceMember(workspaceId, userId, { role }, session.access_token);
      setNotice("Workspace member updated.");
      await load();
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to update member.");
    } finally {
      setMemberBusy(null);
    }
  };

  const removeMember = async (member: ShayWorkspaceMember) => {
    if (!session || !canManageWorkspace || member.user_id === session.user_id) return;
    setMemberBusy(`remove:${member.user_id}`);
    setError(null);
    setNotice(null);
    try {
      await shayApi.removeWorkspaceMember(workspaceId, member.user_id, session.access_token);
      setNotice("Workspace member removed.");
      await load();
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to remove member.");
    } finally {
      setMemberBusy(null);
    }
  };

  const purgeWorkspaceData = async () => {
    if (!canManageWorkspace) {
      setDangerError("Only workspace admins can purge workspace data.");
      return;
    }
    if (!session || !bridge?.aryx_workspace_id) {
      setDangerError("Workspace bridge is not ready yet.");
      return;
    }
    if (!window.confirm(`Purge all Aryx data from "${formatWorkspaceName(workspace?.name)}"?`)) {
      return;
    }
    setPurging(true);
    setDangerError(null);
    setDangerNotice(null);
    try {
      await shayApi.purgeWorkspace(workspaceId, session.access_token);
      setDangerNotice("Workspace data purged.");
    } catch (nextError: unknown) {
      setDangerError(nextError instanceof Error ? nextError.message : "Unable to purge workspace data.");
    } finally {
      setPurging(false);
    }
  };

  const deleteWorkspace = async () => {
    if (!canManageWorkspace) {
      setDangerError("Only workspace admins can delete this workspace.");
      return;
    }
    if (!session) {
      return;
    }
    if (bridge?.aryx_workspace_id === 1) {
      setDangerError("Workspace 1 cannot be deleted.");
      return;
    }
    if (!window.confirm(`Delete workspace "${formatWorkspaceName(workspace?.name)}" permanently?`)) {
      return;
    }
    setDeleting(true);
    setDangerError(null);
    setDangerNotice(null);
    try {
      await shayApi.deleteWorkspace(workspaceId, session.access_token);
      router.replace("/workspaces");
    } catch (nextError: unknown) {
      setDangerError(nextError instanceof Error ? nextError.message : "Unable to delete workspace.");
    } finally {
      setDeleting(false);
    }
  };

  return {
    saveWorkspace,
    addMember,
    updateMemberRole,
    removeMember,
    purgeWorkspaceData,
    deleteWorkspace,
  };
}
