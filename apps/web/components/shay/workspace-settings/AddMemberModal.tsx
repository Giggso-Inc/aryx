"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Search, X } from "lucide-react";
import { getAvatarInitial } from "@/lib/avatar";
import type { ShayUser } from "@/lib/shay-types";
import { MEMBER_ROLES } from "./types";

export function AddMemberModal({
  open,
  availableUsers,
  memberBusy,
  onAddMember,
  onClose,
}: {
  open: boolean;
  availableUsers: ShayUser[];
  memberBusy: string | null;
  onAddMember: (userId: string, role: string) => void;
  onClose: () => void;
}) {
  const [userSearch, setUserSearch] = useState("");
  const [pendingRoles, setPendingRoles] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) {
      setUserSearch("");
      setPendingRoles({});
    }
  }, [open]);

  const filteredAvailableUsers = useMemo(() => {
    const needle = userSearch.trim().toLowerCase();
    if (!needle) {
      return availableUsers;
    }
    return availableUsers.filter((user) => {
      const name = user.name.toLowerCase();
      const email = user.email_id.toLowerCase();
      return name.includes(needle) || email.includes(needle);
    });
  }, [availableUsers, userSearch]);

  const roleForUser = (userId: string) => pendingRoles[userId] ?? "member";

  const setRoleForUser = (userId: string, role: string) => {
    setPendingRoles((current) => ({ ...current, [userId]: role }));
  };

  if (!open) return null;

  return (
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
            onClick={onClose}
            className="focus-ring rounded-full border border-navy-100 p-2 text-navy-500 hover:bg-navy-50"
            aria-label="Close add member dialog"
          >
            <X size={16} />
          </button>
        </div>

        <div className="mt-6 space-y-4">
          <label className="relative block">
            <Search
              className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-subtle"
              size={16}
            />
            <input
              value={userSearch}
              onChange={(event) => setUserSearch(event.target.value)}
              placeholder="Search company users by name or email..."
              className="focus-ring w-full rounded-2xl border border-navy-100 bg-white py-3 pl-11 pr-4 text-sm text-navy-900 placeholder:text-subtle"
            />
          </label>

          <div className="space-y-3">
            {availableUsers.length === 0 ? (
              <div className="rounded-[1.25rem] border border-navy-100 bg-canvas px-4 py-6 text-center text-sm text-subtle">
                Everyone in the company is already part of this workspace.
              </div>
            ) : filteredAvailableUsers.length === 0 ? (
              <div className="rounded-[1.25rem] border border-navy-100 bg-canvas px-4 py-6 text-center text-sm text-subtle">
                No company users match "{userSearch.trim()}".
              </div>
            ) : (
              <>
                <p className="text-sm font-medium text-navy-800">Found users</p>
                <div className="max-h-72 space-y-3 overflow-y-auto pr-1">
                  {filteredAvailableUsers.map((user) => {
                    const pendingRole = roleForUser(user.id);
                    const addingThisUser = memberBusy === `add:${user.id}`;
                    const addDisabled = Boolean(memberBusy) && !addingThisUser;
                    return (
                      <div
                        key={user.id}
                        className="rounded-[1.25rem] border border-navy-100 bg-white px-4 py-4 shadow-sm"
                      >
                        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                          <div className="flex min-w-0 items-center gap-3">
                            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-[linear-gradient(135deg,#173068,#3271d6)] text-sm font-semibold text-white">
                              {getAvatarInitial(user.name, user.email_id, user.id)}
                            </div>
                            <div className="min-w-0">
                              <p className="truncate text-sm font-semibold text-navy-900">
                                {user.name}
                              </p>
                              <p className="mt-1 truncate text-sm text-subtle">
                                {user.email_id}
                              </p>
                            </div>
                          </div>

                          <div className="flex items-center gap-3 md:shrink-0">
                            <select
                              value={pendingRole}
                              onChange={(event) => setRoleForUser(user.id, event.target.value)}
                              disabled={Boolean(memberBusy)}
                              className="focus-ring min-w-[132px] rounded-xl border border-navy-100 bg-white px-3 py-2.5 text-sm text-navy-900"
                            >
                              {MEMBER_ROLES.map((role) => (
                                <option key={role.value} value={role.value}>
                                  {role.label}
                                </option>
                              ))}
                            </select>
                            <button
                              type="button"
                              onClick={() => void onAddMember(user.id, pendingRole)}
                              disabled={addDisabled}
                              className="focus-ring inline-flex min-w-[90px] items-center justify-center gap-2 rounded-xl bg-navy-800 px-4 py-2.5 text-sm font-semibold text-white shadow-soft hover:bg-navy-700 disabled:opacity-50"
                            >
                              {addingThisUser ? (
                                <Loader2 size={15} className="animate-spin" />
                              ) : (
                                <Plus size={15} />
                              )}
                              Add
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="focus-ring rounded-2xl border border-navy-100 px-4 py-2.5 text-sm font-medium text-navy-700 hover:bg-navy-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
