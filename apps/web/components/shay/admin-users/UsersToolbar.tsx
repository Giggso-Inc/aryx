import { Mail, Search } from "lucide-react";
import { INVITATION_STATUS_OPTIONS, USER_ROLE_OPTIONS, USER_STATUS_OPTIONS, type TableTab } from "./types";

export function UsersToolbar({
  tab,
  search,
  roleFilter,
  statusFilter,
  onSearchChange,
  onRoleFilterChange,
  onStatusFilterChange,
  onOpenInviteModal,
}: {
  tab: TableTab;
  search: string;
  roleFilter: string;
  statusFilter: string;
  onSearchChange: (value: string) => void;
  onRoleFilterChange: (value: string) => void;
  onStatusFilterChange: (value: string) => void;
  onOpenInviteModal: () => void;
}) {
  return (
    <section className="rounded-[1.75rem] border border-navy-100 bg-white p-5 shadow-[0_2px_6px_rgba(10,21,48,0.04)] md:p-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center">
        <label className="relative flex-1">
          <Search
            className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-subtle"
            size={16}
          />
          <input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search users or invitations by name or email..."
            className="focus-ring w-full rounded-2xl border border-navy-100 bg-white py-3 pl-11 pr-4 text-sm text-navy-900 placeholder:text-subtle"
          />
        </label>

        <div className="grid gap-3 sm:grid-cols-2 xl:min-w-[340px] xl:grid-cols-2">
          <label className="relative">
            <select
              value={roleFilter}
              onChange={(event) => onRoleFilterChange(event.target.value)}
              className="focus-ring w-full appearance-none rounded-2xl border border-navy-100 bg-white py-3 pl-4 pr-10 text-sm text-navy-900"
            >
              {USER_ROLE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="relative">
            <select
              value={statusFilter}
              onChange={(event) => onStatusFilterChange(event.target.value)}
              className="focus-ring w-full appearance-none rounded-2xl border border-navy-100 bg-white py-3 pl-4 pr-10 text-sm text-navy-900"
            >
              {(tab === "users" ? USER_STATUS_OPTIONS : INVITATION_STATUS_OPTIONS).map(
                (option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ),
              )}
            </select>
          </label>
        </div>

        <button
          type="button"
          onClick={onOpenInviteModal}
          className="focus-ring inline-flex items-center justify-center gap-2 rounded-2xl bg-navy-800 px-5 py-3 text-sm font-semibold text-white hover:bg-navy-700"
        >
          <Mail size={16} />
          Invite Users
        </button>
      </div>
    </section>
  );
}
