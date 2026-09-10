import { Mail, UserRoundCheck, UserRoundX, Users2 } from "lucide-react";
import type { ShayInvitation, ShayUser } from "@/lib/shay-types";
import { MetricCard } from "./widgets";
import { UsersListPanel } from "./UsersListPanel";
import { UsersToolbar } from "./UsersToolbar";
import type { TableTab } from "./types";

export function UsersSection({
  users,
  invitations,
  saving,
  tab,
  search,
  roleFilter,
  statusFilter,
  filteredUsers,
  filteredInvitations,
  currentUserId,
  onTableTabChange,
  onOpenInviteModal,
  onSearchChange,
  onRoleFilterChange,
  onStatusFilterChange,
  onUpdateUser,
  onDeleteUser,
  onDeleteInvitation,
  onShowAllUsers,
  onShowActiveUsers,
  onShowInactiveUsers,
  onShowPendingInvitations,
}: {
  users: ShayUser[];
  invitations: ShayInvitation[];
  saving: boolean;
  tab: TableTab;
  search: string;
  roleFilter: string;
  statusFilter: string;
  filteredUsers: ShayUser[];
  filteredInvitations: ShayInvitation[];
  currentUserId?: string | null;
  onTableTabChange: (tab: TableTab) => void;
  onOpenInviteModal: () => void;
  onSearchChange: (value: string) => void;
  onRoleFilterChange: (value: string) => void;
  onStatusFilterChange: (value: string) => void;
  onUpdateUser: (userId: string, payload: { role?: string; is_active?: boolean }) => void;
  onDeleteUser: (user: ShayUser) => void;
  onDeleteInvitation: (email: string) => void;
  onShowAllUsers: () => void;
  onShowActiveUsers: () => void;
  onShowInactiveUsers: () => void;
  onShowPendingInvitations: () => void;
}) {
  return (
    <div className="space-y-6">
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          tone="blue"
          title="Total Users"
          value={users.length}
          helper="All company members"
          icon={<Users2 size={18} />}
          onClick={onShowAllUsers}
        />
        <MetricCard
          tone="green"
          title="Active Users"
          value={users.filter((user) => user.is_active).length}
          helper="Currently active"
          icon={<UserRoundCheck size={18} />}
          onClick={onShowActiveUsers}
        />
        <MetricCard
          tone="red"
          title="Inactive Users"
          value={users.filter((user) => !user.is_active).length}
          helper="Disabled accounts"
          icon={<UserRoundX size={18} />}
          onClick={onShowInactiveUsers}
        />
        <MetricCard
          tone="slate"
          title="Pending Invitations"
          value={invitations.length}
          helper="Awaiting response"
          icon={<Mail size={18} />}
          onClick={onShowPendingInvitations}
        />
      </section>

      <UsersToolbar
        tab={tab}
        search={search}
        roleFilter={roleFilter}
        statusFilter={statusFilter}
        onSearchChange={onSearchChange}
        onRoleFilterChange={onRoleFilterChange}
        onStatusFilterChange={onStatusFilterChange}
        onOpenInviteModal={onOpenInviteModal}
      />

      <UsersListPanel
        users={users}
        invitations={invitations}
        saving={saving}
        tab={tab}
        filteredUsers={filteredUsers}
        filteredInvitations={filteredInvitations}
        currentUserId={currentUserId}
        onTableTabChange={onTableTabChange}
        onUpdateUser={onUpdateUser}
        onDeleteUser={onDeleteUser}
        onDeleteInvitation={onDeleteInvitation}
      />
    </div>
  );
}
