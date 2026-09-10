"use client";

import { AuthGuard } from "./AuthGuard";
import { ShayPageShell } from "./ShayPageShell";
import { AdminUsersPageView } from "./AdminUsersPageView";
import { useAdminUsersPage } from "./admin-users/useAdminUsersPage";

export function AdminUsersPage() {
  const s = useAdminUsersPage();

  return (
    <AuthGuard>
      <ShayPageShell
        showHero={false}
        title="Admin Hub"
        description="Manage company users and invitations."
        contentWidth="wide"
      >
        <AdminUsersPageView
          company={s.company}
          users={s.users}
          invitations={s.invitations}
          loading={s.loading}
          saving={s.saving}
          savingCompany={s.savingCompany}
          error={s.errorsByTab[s.tab] ?? null}
          notice={s.noticesByTab[s.tab] ?? null}
          tab={s.tab}
          tableTab={s.tableTab}
          showInviteComposer={s.showInviteComposer}
          search={s.search}
          roleFilter={s.roleFilter}
          statusFilter={s.statusFilter}
          companyDraft={s.companyDraft}
          filteredUsers={s.filteredUsers}
          filteredInvitations={s.filteredInvitations}
          currentUserId={s.session?.user_id ?? null}
          onTabChange={s.setTab}
          onTableTabChange={s.setTableTab}
          onOpenInviteModal={s.openInviteModal}
          onCloseInviteModal={s.closeInviteModal}
          onSearchChange={s.setSearch}
          onRoleFilterChange={s.setRoleFilter}
          onStatusFilterChange={s.setStatusFilter}
          onCompanyDraftChange={(patch) =>
            s.setCompanyDraft((current) => ({ ...current, ...patch }))
          }
          onSaveCompanyProfile={s.saveCompanyProfile}
          onSendInvites={s.inviteUsers}
          inviteError={s.inviteError}
          onUpdateUser={s.updateUser}
          onDeleteUser={s.deleteUser}
          onDeleteInvitation={s.deleteInvitation}
          onShowAllUsers={() => s.setUserTableState("users", "all")}
          onShowActiveUsers={() => s.setUserTableState("users", "active")}
          onShowInactiveUsers={() => s.setUserTableState("users", "inactive")}
          onShowPendingInvitations={() => s.setUserTableState("invitations", "pending")}
        />
      </ShayPageShell>
    </AuthGuard>
  );
}
