"use client";

import { useEffect, useMemo, useState } from "react";
import { PencilLine } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/cn";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import { workspaceSectionHref } from "@/lib/workspace-route";
import { formatWorkspaceName } from "@/lib/workspace-name";
import type {
  ShayBridgeWorkspaceMap,
  ShayUser,
  ShayWorkspace,
  ShayWorkspaceMember,
} from "@/lib/shay-types";
import { AuthGuard } from "./AuthGuard";
import { ShayPageShell } from "./ShayPageShell";
import { WorkspaceProfileDialog } from "./WorkspaceProfileDialog";
import { AppsTab } from "./workspace-settings/AppsTab";
import { DangerZoneTab } from "./workspace-settings/DangerZoneTab";
import { MembersTab } from "./workspace-settings/MembersTab";
import { InlineNotice, ProfileSummaryField } from "./workspace-settings/shared";
import {
  SETTINGS_TABS,
  type DisplayWorkspaceMember,
  type SettingsTab,
} from "./workspace-settings/types";

export function WorkspaceSettingsPage({ workspaceId }: { workspaceId: string }) {
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

  const openAddMemberModal = () => {
    setAddMemberOpen(true);
  };

  const closeAddMemberModal = () => {
    setAddMemberOpen(false);
  };

  const setTab = (nextTab: SettingsTab) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", nextTab);
    router.replace(`${pathname}?${params.toString()}`);
  };

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
      setBridge(updated.bridge ?? null);
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

  return (
    <AuthGuard>
      <ShayPageShell
        eyebrow="Workspace settings"
        title="Workspace settings"
        description="Manage workspace access and maintenance actions while keeping the Aryx workspace mapping aligned."
        showHero={false}
        contentCard={false}
        contentWidth="detail"
      >
        {loading ? (
          <div className="rounded-[1.5rem] border border-navy-100 bg-white px-5 py-12 text-center text-sm text-subtle shadow-soft">
            Loading workspace settings...
          </div>
        ) : (
          <div className="space-y-6">
            <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
              <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                <div className="flex w-full flex-col gap-5 lg:flex-row lg:items-start">
                  <div className="grid flex-1 gap-5 md:grid-cols-2">
                    <ProfileSummaryField
                      label="Workspace name"
                      value={formatWorkspaceName(workspace?.name)}
                    />
                    <ProfileSummaryField
                      label="Workspace description"
                      value={workspace?.description || "No description added yet."}
                    />
                  </div>

                  {canManageWorkspace ? (
                    <button
                      type="button"
                      onClick={() => setEditProfileOpen(true)}
                      className="focus-ring inline-flex items-center justify-center gap-2 self-start rounded-full border border-navy-200 bg-white px-4 py-2 text-sm font-semibold text-navy-800 hover:bg-navy-50 lg:ml-auto"
                    >
                      <PencilLine size={15} />
                      Edit workspace
                    </button>
                  ) : null}
                </div>
              </div>

              {notice ? <InlineNotice tone="success">{notice}</InlineNotice> : null}
              {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
            </section>

            <section className="overflow-hidden rounded-[1.5rem] border border-navy-100 bg-white shadow-soft">
              <div className="border-b border-navy-100 bg-white">
                <div className="flex flex-wrap items-end gap-0 px-5">
                  {SETTINGS_TABS
                    .filter((item) => item.id !== "danger-zone" || canManageWorkspace)
                    .map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setTab(item.id)}
                      className={cn(
                        "border-b-2 px-4 py-3 text-sm font-medium transition-colors",
                        activeTab === item.id
                          ? "border-navy-800 text-navy-900"
                          : "border-transparent text-navy-500 hover:text-navy-800",
                      )}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="px-5 py-5">
                {activeTab === "members" ? (
                  <MembersTab
                    addMemberOpen={addMemberOpen}
                    availableUsers={availableUsers}
                    canManageMembers={canManageWorkspace}
                    currentUserId={session?.user_id ?? null}
                    memberBusy={memberBusy}
                    members={displayMembers}
                    onAddMember={addMember}
                    onCloseModal={closeAddMemberModal}
                    onOpenModal={openAddMemberModal}
                    onRemoveMember={removeMember}
                    onUpdateMemberRole={updateMemberRole}
                  />
                ) : null}

                {activeTab === "apps" ? <AppsTab /> : null}

                {activeTab === "danger-zone" ? (
                  <DangerZoneTab
                    bridgeReady={Boolean(bridge?.aryx_workspace_id)}
                    dangerError={dangerError}
                    dangerNotice={dangerNotice}
                    deleting={deleting}
                    onDeleteWorkspace={deleteWorkspace}
                    onPurgeWorkspace={purgeWorkspaceData}
                    purging={purging}
                  />
                ) : null}
              </div>
            </section>
          </div>
        )}
        {editProfileOpen ? (
          <WorkspaceProfileDialog
            description={draftDescription}
            name={draftName}
            onClose={() => setEditProfileOpen(false)}
            onDescriptionChange={setDraftDescription}
            onNameChange={setDraftName}
            onSave={saveWorkspace}
            saving={savingProfile}
          />
        ) : null}
      </ShayPageShell>
    </AuthGuard>
  );
}
