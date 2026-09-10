/**
 * Core state, data loading, and derived values for WorkspaceSettingsPage.
 *
 * Split out of WorkspaceSettingsPage.tsx (2026-09; Raven Style
 * Compliance Plan Phase 8b line-count reduction) — owns everything
 * except the write-path mutation handlers (see useWorkspaceSettingsActions.ts).
 */

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import { workspaceSectionHref } from "@/lib/workspace-route";
import type {
  ShayBridgeWorkspaceMap,
  ShayUser,
  ShayWorkspace,
  ShayWorkspaceMember,
} from "@/lib/shay-types";
import type { DisplayWorkspaceMember, SettingsTab } from "./types";

export function useWorkspaceSettingsState(workspaceId: string) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { session } = useShayAuth();

  const rawTab = searchParams.get("tab");
  const tab: SettingsTab = rawTab === "apps" || rawTab === "danger-zone" ? rawTab : "members";

  const [workspace, setWorkspace] = useState<ShayWorkspace | null>(null);
  const [members, setMembers] = useState<ShayWorkspaceMember[]>([]);
  const [companyUsers, setCompanyUsers] = useState<ShayUser[]>([]);
  const [bridge, setBridge] = useState<ShayBridgeWorkspaceMap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const [draftDescription, setDraftDescription] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [editProfileOpen, setEditProfileOpen] = useState(false);
  const [addMemberOpen, setAddMemberOpen] = useState(false);
  const [memberBusy, setMemberBusy] = useState<string | null>(null);
  const [purging, setPurging] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [dangerNotice, setDangerNotice] = useState<string | null>(null);
  const [dangerError, setDangerError] = useState<string | null>(null);

  const load = async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const nextWorkspace = await shayApi.getWorkspace(workspaceId, session.access_token);
      const resolvedWorkspaceId = nextWorkspace.id;
      const memberList = await shayApi.listWorkspaceMembers(resolvedWorkspaceId, session.access_token);

      if (resolvedWorkspaceId !== workspaceId) {
        const params = searchParams.toString();
        router.replace(
          params
            ? `${workspaceSectionHref(resolvedWorkspaceId, "settings")}?${params}`
            : workspaceSectionHref(resolvedWorkspaceId, "settings"),
        );
      }

      setWorkspace(nextWorkspace);
      setBridge(nextWorkspace.bridge ?? null);
      setDraftName(nextWorkspace.name);
      setDraftDescription(nextWorkspace.description ?? "");
      setMembers(memberList.members);

      try {
        const userList = await shayApi.listCompanyUsers(session.company_id, session.access_token);
        setCompanyUsers(userList.users);
      } catch {
        setCompanyUsers([]);
      }
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to load workspace settings.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [router, searchParams, session?.access_token, session?.company_id, workspaceId]);

  const displayMembers = useMemo(() => {
    const nextMembers = [...members] as DisplayWorkspaceMember[];
    const currentUserId = session?.user_id;
    if (!currentUserId) return nextMembers;

    const alreadyPresent = nextMembers.some((member) => member.user_id === currentUserId);
    if (alreadyPresent) return nextMembers;

    const currentCompanyUser = companyUsers.find((user) => user.id === currentUserId);
    const isWorkspaceOwner =
      workspace?.user_id === currentUserId || workspace?.created_by === currentUserId;

    if (!currentCompanyUser && !isWorkspaceOwner) {
      return nextMembers;
    }

    nextMembers.unshift({
      id: `derived-${currentUserId}`,
      user_id: currentUserId,
      workspace_id: workspaceId,
      level: "workspace",
      role: isWorkspaceOwner ? "admin" : session.role || "member",
      is_active: true,
      name: currentCompanyUser?.name || session.name || "You",
      email: currentCompanyUser?.email_id || session.email_id,
      derived: true,
      derivedLabel: isWorkspaceOwner ? "Workspace owner" : "Current user",
    });
    return nextMembers;
  }, [companyUsers, members, session, workspace, workspaceId]);

  const currentWorkspaceMember = useMemo(() => {
    if (!session?.user_id) return null;
    return displayMembers.find((member) => member.user_id === session.user_id) ?? null;
  }, [displayMembers, session?.user_id]);

  const canManageWorkspace = currentWorkspaceMember?.is_active === true
    && currentWorkspaceMember.role === "admin";
  const activeTab = tab === "danger-zone" && !canManageWorkspace ? "members" : tab;

  const availableUsers = useMemo(() => {
    const memberIds = new Set(displayMembers.map((member) => member.user_id));
    return companyUsers.filter((user) => !memberIds.has(user.id));
  }, [companyUsers, displayMembers]);

  const setTab = (nextTab: SettingsTab) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", nextTab);
    router.replace(`${pathname}?${params.toString()}`);
  };

  return {
    router,
    session,
    workspaceId,
    workspace,
    setWorkspace,
    bridge,
    setBridge,
    loading,
    error,
    setError,
    notice,
    setNotice,
    draftName,
    setDraftName,
    draftDescription,
    setDraftDescription,
    savingProfile,
    setSavingProfile,
    editProfileOpen,
    setEditProfileOpen,
    addMemberOpen,
    setAddMemberOpen,
    memberBusy,
    setMemberBusy,
    purging,
    setPurging,
    deleting,
    setDeleting,
    dangerNotice,
    setDangerNotice,
    dangerError,
    setDangerError,
    load,
    displayMembers,
    canManageWorkspace,
    activeTab,
    availableUsers,
    setTab,
    openAddMemberModal: () => setAddMemberOpen(true),
    closeAddMemberModal: () => setAddMemberOpen(false),
  };
}
