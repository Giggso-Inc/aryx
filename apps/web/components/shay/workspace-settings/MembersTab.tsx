import { UserPlus } from "lucide-react";
import { cn } from "@/lib/cn";
import { getAvatarInitial } from "@/lib/avatar";
import type { ShayUser, ShayWorkspaceMember } from "@/lib/shay-types";
import { AddMemberModal } from "./AddMemberModal";
import { MEMBER_ROLES, roleLabel, type DisplayWorkspaceMember } from "./types";

function memberInitials(member: ShayWorkspaceMember) {
  return getAvatarInitial(member.name, member.email, member.user_id);
}

export function MembersTab({
  addMemberOpen,
  availableUsers,
  canManageMembers,
  currentUserId,
  memberBusy,
  members,
  onAddMember,
  onCloseModal,
  onOpenModal,
  onRemoveMember,
  onUpdateMemberRole,
}: {
  addMemberOpen: boolean;
  availableUsers: ShayUser[];
  canManageMembers: boolean;
  currentUserId?: string | null;
  memberBusy: string | null;
  members: DisplayWorkspaceMember[];
  onAddMember: (userId: string, role: string) => void;
  onCloseModal: () => void;
  onOpenModal: () => void;
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

      <AddMemberModal
        open={addMemberOpen}
        availableUsers={availableUsers}
        memberBusy={memberBusy}
        onAddMember={onAddMember}
        onClose={onCloseModal}
      />
    </div>
  );
}
