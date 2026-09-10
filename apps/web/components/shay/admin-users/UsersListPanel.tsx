import type { ShayInvitation, ShayUser } from "@/lib/shay-types";
import { InvitationsTable } from "./InvitationsTable";
import { UsersTable } from "./UsersTable";
import type { TableTab } from "./types";

export function UsersListPanel({
  users,
  invitations,
  saving,
  tab,
  filteredUsers,
  filteredInvitations,
  currentUserId,
  onTableTabChange,
  onUpdateUser,
  onDeleteUser,
  onDeleteInvitation,
}: {
  users: ShayUser[];
  invitations: ShayInvitation[];
  saving: boolean;
  tab: TableTab;
  filteredUsers: ShayUser[];
  filteredInvitations: ShayInvitation[];
  currentUserId?: string | null;
  onTableTabChange: (tab: TableTab) => void;
  onUpdateUser: (userId: string, payload: { role?: string; is_active?: boolean }) => void;
  onDeleteUser: (user: ShayUser) => void;
  onDeleteInvitation: (email: string) => void;
}) {
  return (
    <section className="space-y-4">
      <div className="flex flex-col gap-4 border-b border-navy-100 pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-navy-900">
            {tab === "users" ? "Users" : "Pending Invitations"}
          </h2>
          <p className="mt-1 text-sm text-subtle">
            {tab === "users"
              ? `${filteredUsers.length} visible of ${users.length} users`
              : `${filteredInvitations.length} visible of ${invitations.length} invitations`}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {tab === "users" ? (
            <button
              type="button"
              onClick={() => onTableTabChange("invitations")}
              className="focus-ring inline-flex items-center gap-2 rounded-full border border-navy-100 bg-white px-4 py-2 text-sm font-semibold text-navy-800 hover:bg-navy-50"
            >
              View Pending Invitations
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onTableTabChange("users")}
              className="focus-ring inline-flex items-center gap-2 rounded-full border border-navy-100 bg-white px-4 py-2 text-sm font-semibold text-navy-800 hover:bg-navy-50"
            >
              View Users
            </button>
          )}
        </div>
      </div>

      {tab === "users" ? (
        <UsersTable
          users={filteredUsers}
          currentUserId={currentUserId}
          onRoleChange={(userId, role) => onUpdateUser(userId, { role })}
          onToggle={(user) => onUpdateUser(user.id, { is_active: !user.is_active })}
          onDelete={onDeleteUser}
          saving={saving}
        />
      ) : (
        <InvitationsTable
          invitations={filteredInvitations}
          onDelete={onDeleteInvitation}
          saving={saving}
        />
      )}
    </section>
  );
}
