import { Trash2, UserCheck, UserX, Users2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { getAvatarInitial } from "@/lib/avatar";
import type { ShayUser } from "@/lib/shay-types";
import { EmptyState, RoleBadge } from "./shared";

export function UsersTable({
  users,
  currentUserId,
  onRoleChange,
  onToggle,
  onDelete,
  saving,
}: {
  users: ShayUser[];
  currentUserId?: string | null;
  onRoleChange: (userId: string, role: string) => void;
  onToggle: (user: ShayUser) => void;
  onDelete: (user: ShayUser) => void;
  saving: boolean;
}) {
  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-[1.5rem] border border-navy-100">
        <div className="grid grid-cols-[minmax(0,1.9fr)_minmax(0,1.4fr)_120px_120px_160px_96px] gap-4 border-b border-navy-100 bg-canvas px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle">
          <span>Name</span>
          <span>Email</span>
          <span>Role</span>
          <span>Status</span>
          <span>Last login</span>
          <span>Actions</span>
        </div>
        <div className="divide-y divide-navy-100 bg-white">
          {users.length === 0 ? (
            <EmptyState
              icon={<Users2 size={18} />}
              title="No matching users"
              body="Adjust the search or filters to reveal the company members."
            />
          ) : (
            users.map((user) => {
              const isSelf = currentUserId === user.id;
              return (
                <div
                  key={user.id}
                  className="grid grid-cols-1 gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1.9fr)_minmax(0,1.4fr)_120px_120px_160px_96px] lg:items-center"
                >
                  <UserCell user={user} />
                  <div className="min-w-0">
                    <p className="truncate text-sm text-navy-900">{user.email_id}</p>
                  </div>
                  <div>
                    {isSelf ? (
                      <RoleBadge role={user.role} />
                    ) : (
                      <select
                        value={user.role}
                        onChange={(event) => onRoleChange(user.id, event.target.value)}
                        disabled={saving}
                        className="focus-ring w-full rounded-full border border-navy-100 bg-white px-3 py-2 text-sm text-navy-900 disabled:opacity-60"
                      >
                        <option value="user">User</option>
                        <option value="manager">Manager</option>
                        <option value="admin">Admin</option>
                      </select>
                    )}
                  </div>
                  <div>
                    <StatusBadge active={user.is_active} />
                  </div>
                  <div className="text-sm text-navy-700">
                    {user.last_login ? new Date(user.last_login).toLocaleString() : "Never"}
                  </div>
                  <div className="flex items-center gap-2">
                    {isSelf ? (
                      <span className="rounded-full bg-navy-50 px-3 py-1 text-xs font-semibold text-navy-700">
                        You
                      </span>
                    ) : (
                      <>
                        <button
                          type="button"
                          onClick={() => onToggle(user)}
                          disabled={saving}
                          className="focus-ring inline-flex size-9 items-center justify-center rounded-xl border border-navy-100 bg-white text-navy-700 hover:bg-navy-50 disabled:opacity-60"
                          aria-label={user.is_active ? "Deactivate user" : "Reactivate user"}
                        >
                          {user.is_active ? <UserX size={15} /> : <UserCheck size={15} />}
                        </button>
                        <button
                          type="button"
                          onClick={() => onDelete(user)}
                          disabled={saving}
                          className="focus-ring inline-flex size-9 items-center justify-center rounded-xl border border-rose-200 bg-white text-rose-600 hover:bg-rose-50 disabled:opacity-60"
                          aria-label="Delete user"
                          title="Delete user"
                        >
                          <Trash2 size={15} />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

function UserCell({ user }: { user: ShayUser }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <Avatar name={user.name} email={user.email_id} />
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-navy-900">{user.name}</p>
        <p className="mt-1 text-xs text-subtle">
          {user.is_active ? "Team member" : "Inactive"}
        </p>
      </div>
    </div>
  );
}

function Avatar({ name, email }: { name: string; email: string }) {
  return (
    <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-navy-800 text-sm font-semibold text-white">
      {getAvatarInitial(name, email)}
    </div>
  );
}

function StatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-3 py-1 text-xs font-medium",
        active ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-700",
      )}
    >
      {active ? "Active" : "Inactive"}
    </span>
  );
}
