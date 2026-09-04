"use client";

import { cn } from "@/lib/cn";
import type { CompanyProfileDraft } from "./admin-users/company-draft";
import type { ShayCompany, ShayInvitation, ShayUser } from "@/lib/shay-types";
import { InviteUserModal } from "./admin-users/InviteUserModal";
import { CompanyProfileSection } from "./admin-users/CompanyProfileSection";
import { SubscriptionSection } from "./admin-users/SubscriptionSection";
import { UsersSection } from "./admin-users/UsersSection";
import { LoadingState } from "./admin-users/widgets";
import { SETTINGS_TABS, type AdminTab, type TableTab } from "./admin-users/types";

interface AdminUsersPageViewProps {
  company: ShayCompany | null;
  users: ShayUser[];
  invitations: ShayInvitation[];
  loading: boolean;
  saving: boolean;
  savingCompany: boolean;
  error: string | null;
  notice: string | null;
  tab: AdminTab;
  tableTab: TableTab;
  showInviteComposer: boolean;
  search: string;
  roleFilter: string;
  statusFilter: string;
  companyDraft: CompanyProfileDraft;
  filteredUsers: ShayUser[];
  filteredInvitations: ShayInvitation[];
  currentUserId?: string | null;
  onTabChange: (tab: AdminTab) => void;
  onTableTabChange: (tab: TableTab) => void;
  onOpenInviteModal: () => void;
  onCloseInviteModal: () => void;
  onSearchChange: (value: string) => void;
  onRoleFilterChange: (value: string) => void;
  onStatusFilterChange: (value: string) => void;
  onCompanyDraftChange: (patch: Partial<CompanyProfileDraft>) => void;
  onSaveCompanyProfile: () => void;
  onSendInvites: (invites: Array<{ email: string; role: string }>) => void;
  inviteError: string | null;
  onUpdateUser: (userId: string, payload: { role?: string; is_active?: boolean }) => void;
  onDeleteUser: (user: ShayUser) => void;
  onDeleteInvitation: (email: string) => void;
  onShowAllUsers: () => void;
  onShowActiveUsers: () => void;
  onShowInactiveUsers: () => void;
  onShowPendingInvitations: () => void;
}

export function AdminUsersPageView({
  company,
  users,
  invitations,
  loading,
  saving,
  savingCompany,
  error,
  notice,
  tab,
  tableTab,
  showInviteComposer,
  search,
  roleFilter,
  statusFilter,
  companyDraft,
  filteredUsers,
  filteredInvitations,
  currentUserId,
  onTabChange,
  onTableTabChange,
  onOpenInviteModal,
  onCloseInviteModal,
  onSearchChange,
  onRoleFilterChange,
  onStatusFilterChange,
  onCompanyDraftChange,
  onSaveCompanyProfile,
  onSendInvites,
  inviteError,
  onUpdateUser,
  onDeleteUser,
  onDeleteInvitation,
  onShowAllUsers,
  onShowActiveUsers,
  onShowInactiveUsers,
  onShowPendingInvitations,
}: AdminUsersPageViewProps) {
  return (
    <div className="space-y-6 animate-fade-in">
      <div className="border-b border-navy-100 bg-white">
        <div className="flex flex-wrap items-end gap-0 px-5">
          {SETTINGS_TABS.map(({ id, label, icon: Icon }) => {
            const active = tab === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => onTabChange(id)}
                className={cn(
                  "border-b-2 px-4 py-3 text-sm font-medium transition-colors",
                  active
                    ? "border-navy-800 text-navy-900"
                    : "border-transparent text-navy-500 hover:text-navy-800",
                )}
              >
                <span className="inline-flex items-center gap-2">
                  <Icon size={16} />
                  {label}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {loading ? (
        <LoadingState />
      ) : (
        <>
          {error ? <Alert message={error} tone="error" /> : null}
          {notice ? <Alert message={notice} tone="success" /> : null}

          {tab === "users" ? (
            <UsersSection
              users={users}
              invitations={invitations}
              saving={saving}
              tab={tableTab}
              search={search}
              roleFilter={roleFilter}
              statusFilter={statusFilter}
              filteredUsers={filteredUsers}
              filteredInvitations={filteredInvitations}
              currentUserId={currentUserId}
              onTableTabChange={onTableTabChange}
              onOpenInviteModal={onOpenInviteModal}
              onSearchChange={onSearchChange}
              onRoleFilterChange={onRoleFilterChange}
              onStatusFilterChange={onStatusFilterChange}
              onUpdateUser={onUpdateUser}
              onDeleteUser={onDeleteUser}
              onDeleteInvitation={onDeleteInvitation}
              onShowAllUsers={onShowAllUsers}
              onShowActiveUsers={onShowActiveUsers}
              onShowInactiveUsers={onShowInactiveUsers}
              onShowPendingInvitations={onShowPendingInvitations}
            />
          ) : null}

          {tab === "subscription" ? <SubscriptionSection company={company} /> : null}

          {tab === "company-profile" ? (
            <CompanyProfileSection
              company={company}
              savingCompany={savingCompany}
              companyDraft={companyDraft}
              onCompanyDraftChange={onCompanyDraftChange}
              onSaveCompanyProfile={onSaveCompanyProfile}
            />
          ) : null}
        </>
      )}

      <InviteUserModal
        open={showInviteComposer}
        onClose={onCloseInviteModal}
        onSendInvites={onSendInvites}
        errorMessage={inviteError}
      />
    </div>
  );
}

function Alert({ message, tone }: { message: string; tone: "error" | "success" }) {
  return (
    <div
      className={cn(
        "mb-4 rounded-2xl border px-4 py-3 text-sm",
        tone === "error"
          ? "border-rose-200 bg-rose-50 text-rose-700"
          : "border-emerald-200 bg-emerald-50 text-emerald-700",
      )}
    >
      {message}
    </div>
  );
}
