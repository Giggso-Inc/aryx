"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Loader2, PencilLine, Plus, UserPlus, Users2, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { cn } from "@/lib/cn";
import { getAvatarInitial } from "@/lib/avatar";
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

type SettingsTab = "members" | "apps" | "danger-zone";

const MEMBER_ROLES = [
  { value: "admin", label: "Admin" },
  { value: "member", label: "Member" },
  { value: "viewer", label: "Viewer" },
] as const;

const SETTINGS_TABS: Array<{ id: SettingsTab; label: string }> = [
  { id: "members", label: "Members" },
  { id: "apps", label: "Apps" },
  { id: "danger-zone", label: "Danger Zone" },
];

type DisplayWorkspaceMember = ShayWorkspaceMember & {
  derived?: boolean;
  derivedLabel?: string;
};

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
  const [memberUserId, setMemberUserId] = useState("");
  const [memberRole, setMemberRole] = useState("member");
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

  const addMember = async () => {
    if (!session || !memberUserId || !canManageWorkspace) return;
    setMemberBusy("add");
    setError(null);
    setNotice(null);
    try {
      await shayApi.addWorkspaceMember(
        workspaceId,
        { user_id: memberUserId, role: memberRole },
        session.access_token,
      );
      setMemberUserId("");
      setMemberRole("member");
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
                    memberRole={memberRole}
                    memberUserId={memberUserId}
                    members={displayMembers}
                    onAddMember={addMember}
                    onCloseModal={() => setAddMemberOpen(false)}
                    onOpenModal={() => setAddMemberOpen(true)}
                    onMemberRoleChange={setMemberRole}
                    onMemberUserChange={setMemberUserId}
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
                    workspaceName={workspace?.name}
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

function MembersTab({
  addMemberOpen,
  availableUsers,
  canManageMembers,
  currentUserId,
  memberBusy,
  memberRole,
  memberUserId,
  members,
  onAddMember,
  onCloseModal,
  onOpenModal,
  onMemberRoleChange,
  onMemberUserChange,
  onRemoveMember,
  onUpdateMemberRole,
}: {
  addMemberOpen: boolean;
  availableUsers: ShayUser[];
  canManageMembers: boolean;
  currentUserId?: string | null;
  memberBusy: string | null;
  memberRole: string;
  memberUserId: string;
  members: DisplayWorkspaceMember[];
  onAddMember: () => void;
  onCloseModal: () => void;
  onOpenModal: () => void;
  onMemberRoleChange: (value: string) => void;
  onMemberUserChange: (value: string) => void;
  onRemoveMember: (member: ShayWorkspaceMember) => void;
  onUpdateMemberRole: (userId: string, role: string) => void;
}) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-xl font-semibold text-navy-900">Workspace members</h3>
          <p className="mt-2 text-sm text-subtle">
            Manage who has access to this workspace with a tile-based member view.
          </p>
        </div>
        {canManageMembers ? (
          <button
            type="button"
            onClick={onOpenModal}
            className="focus-ring inline-flex items-center gap-2 rounded-2xl bg-navy-800 px-4 py-2.5 text-sm font-semibold text-white shadow-soft hover:bg-navy-700"
          >
            <UserPlus size={15} />
            Add member
          </button>
        ) : null}
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {members.map((member) => {
          const busy = memberBusy?.includes(member.user_id);
          const isSelf = currentUserId === member.user_id;
          const canManageThisMember = canManageMembers && !isSelf && !member.derived;
          return (
            <article
              key={member.id}
              className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-[0_18px_35px_rgba(10,21,48,0.06)]"
            >
              <div className="flex flex-col items-center text-center">
                <div className="flex h-20 w-20 items-center justify-center rounded-full bg-[linear-gradient(135deg,#173068,#3271d6)] text-2xl font-semibold text-white">
                  {memberInitials(member)}
                </div>
                <p className="mt-4 text-base font-semibold text-navy-900">
                  {member.name || member.email || member.user_id}
                </p>
                <p className="mt-1 text-sm text-subtle">{member.email || member.user_id}</p>
                <span
                  className={cn(
                    "mt-3 rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]",
                    member.derived
                      ? "bg-blue-50 text-blue-700"
                      : member.is_active
                      ? "bg-emerald-50 text-emerald-700"
                      : "bg-slate-100 text-slate-500",
                  )}
                >
                  {member.derived ? member.derivedLabel || "Current user" : member.is_active ? "Active" : "Inactive"}
                </span>
              </div>

              <div className="mt-5 space-y-3">
                {canManageThisMember ? (
                  <select
                    value={member.role}
                    onChange={(event) => void onUpdateMemberRole(member.user_id, event.target.value)}
                    disabled={Boolean(busy)}
                    className="focus-ring w-full rounded-2xl border border-navy-100 bg-white px-4 py-3 text-sm text-navy-900"
                  >
                    {MEMBER_ROLES.map((role) => (
                      <option key={role.value} value={role.value}>
                        {role.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="rounded-2xl border border-navy-100 bg-canvas px-4 py-3 text-sm font-medium text-navy-800">
                    {roleLabel(member.role)}
                  </div>
                )}

                {canManageThisMember ? (
                  <button
                    type="button"
                    onClick={() => void onRemoveMember(member)}
                    disabled={Boolean(busy)}
                    className="focus-ring w-full rounded-2xl border border-rose-200 px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                  >
                    {busy && memberBusy?.startsWith("remove:") ? "Removing..." : "Remove"}
                  </button>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>

      <p className="text-sm text-subtle">Showing {members.length} of {members.length} members</p>

      {addMemberOpen ? (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-navy-900/35 px-4 backdrop-blur-sm">
          <div className="w-full max-w-xl rounded-[2rem] border border-navy-100 bg-white p-6 shadow-soft">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-2xl font-semibold text-navy-900">Add members</h2>
                <p className="mt-2 text-sm text-subtle">
                  Add people from your company roster to this workspace.
                </p>
              </div>
              <button
                type="button"
                onClick={onCloseModal}
                className="focus-ring rounded-full border border-navy-100 p-2 text-navy-500 hover:bg-navy-50"
                aria-label="Close add member dialog"
              >
                <X size={16} />
              </button>
            </div>

            <div className="mt-6 grid gap-4 md:grid-cols-[minmax(0,1fr)_180px]">
              <select
                value={memberUserId}
                onChange={(event) => onMemberUserChange(event.target.value)}
                className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
              >
                <option value="">Select company user</option>
                {availableUsers.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.name} ({user.email_id})
                  </option>
                ))}
              </select>
              <select
                value={memberRole}
                onChange={(event) => onMemberRoleChange(event.target.value)}
                className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
              >
                {MEMBER_ROLES.map((role) => (
                  <option key={role.value} value={role.value}>
                    {role.label}
                  </option>
                ))}
              </select>
            </div>

            {availableUsers.length === 0 ? (
              <div className="mt-4 rounded-2xl border border-navy-100 bg-canvas px-4 py-3 text-sm text-subtle">
                Everyone in the company is already part of this workspace.
              </div>
            ) : null}

            <div className="mt-6 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={onCloseModal}
                className="focus-ring rounded-2xl border border-navy-100 px-4 py-2.5 text-sm font-medium text-navy-700 hover:bg-navy-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={onAddMember}
                disabled={!memberUserId || memberBusy === "add" || availableUsers.length === 0}
                className="focus-ring inline-flex items-center gap-2 rounded-2xl bg-navy-800 px-5 py-2.5 text-sm font-semibold text-white shadow-soft hover:bg-navy-700 disabled:opacity-50"
              >
                {memberBusy === "add" ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
                Add member
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function AppsTab() {
  return (
    <div className="rounded-[1.5rem] border border-dashed border-navy-200 bg-[radial-gradient(circle_at_top_left,_rgba(50,113,214,0.08),_transparent_42%),linear-gradient(180deg,_#ffffff,_#f7f9fd)] px-6 py-12 text-center">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-navy-900 text-white">
        <Users2 size={22} />
      </div>
      <h3 className="mt-5 text-2xl font-semibold text-navy-900">Apps are coming soon</h3>
      <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-subtle">
        Workspace app connections will land here next. This tab is reserved for install state,
        permissions, and app-specific workspace controls.
      </p>
    </div>
  );
}

function DangerZoneTab({
  bridgeReady,
  dangerError,
  dangerNotice,
  deleting,
  onDeleteWorkspace,
  onPurgeWorkspace,
  purging,
  workspaceName,
}: {
  bridgeReady: boolean;
  dangerError: string | null;
  dangerNotice: string | null;
  deleting: boolean;
  onDeleteWorkspace: () => void;
  onPurgeWorkspace: () => void;
  purging: boolean;
  workspaceName?: string | null;
}) {
  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-xl font-semibold text-rose-900">Danger zone</h3>
        <p className="mt-2 text-sm text-subtle">
          Destructive workspace actions for {formatWorkspaceName(workspaceName)} live here.
        </p>
      </div>

      {dangerNotice ? <InlineNotice tone="success">{dangerNotice}</InlineNotice> : null}
      {dangerError ? <InlineNotice tone="error">{dangerError}</InlineNotice> : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-[1.5rem] border border-amber-200 bg-[linear-gradient(180deg,rgba(255,250,235,0.95),rgba(255,244,214,0.9))] p-5">
          <div className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-800">
            <AlertTriangle size={14} />
            Purge workspace data
          </div>
          <p className="mt-4 text-sm leading-6 text-amber-900">
            Deletes all entities, relationships, and Aryx graph data for this workspace while keeping the workspace itself.
          </p>
          <button
            type="button"
            onClick={onPurgeWorkspace}
            disabled={purging || !bridgeReady}
            className="focus-ring mt-5 inline-flex items-center gap-2 rounded-2xl border border-amber-300 bg-white px-4 py-2 text-sm font-semibold text-amber-800 hover:bg-amber-50 disabled:opacity-50"
          >
            {purging ? <Loader2 size={15} className="animate-spin" /> : <AlertTriangle size={15} />}
            Purge workspace data
          </button>
        </div>

        <div className="rounded-[1.5rem] border border-rose-200 bg-[linear-gradient(180deg,rgba(255,245,246,0.98),rgba(255,236,239,0.94))] p-5">
          <div className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-rose-800">
            <AlertTriangle size={14} />
            Delete workspace data
          </div>
          <p className="mt-4 text-sm leading-6 text-rose-900">
            Permanently deletes this workspace and all of its data. Workspace 1 remains protected.
          </p>
          <button
            type="button"
            onClick={onDeleteWorkspace}
            disabled={deleting}
            className="focus-ring mt-5 inline-flex items-center gap-2 rounded-2xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
          >
            {deleting ? <Loader2 size={15} className="animate-spin" /> : <AlertTriangle size={15} />}
            Delete workspace data
          </button>
        </div>
      </div>
    </div>
  );
}

function InlineNotice({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone: "success" | "error";
}) {
  return (
    <div
      className={cn(
        "mt-4 rounded-2xl px-4 py-3 text-sm",
        tone === "success"
          ? "border border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border border-rose-200 bg-rose-50 text-rose-700",
      )}
    >
      {children}
    </div>
  );
}

function ProfileSummaryField({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-navy-500">
        {label}
      </p>
      <p className="mt-2 break-words text-base text-navy-900">{value}</p>
    </div>
  );
}

function memberInitials(member: ShayWorkspaceMember) {
  return getAvatarInitial(member.name, member.email, member.user_id);
}

function roleLabel(role: string) {
  return MEMBER_ROLES.find((option) => option.value === role)?.label ?? role;
}
