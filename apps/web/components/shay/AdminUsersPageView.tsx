"use client";

import type { ReactNode } from "react";
import {
  Building2,
  CreditCard,
  Globe,
  Mail,
  Search,
  ShieldCheck,
  UserRoundCheck,
  UserRoundX,
  Users2,
  Sparkles,
} from "lucide-react";
import {
  InviteUserModal,
  InvitationsTable,
  LoadingState,
  MetricCard,
  UsersTable,
} from "./AdminUsersPageParts";
import type { CompanyProfileDraft } from "./AdminUsersPage";
import type { ShayCompany, ShayInvitation, ShayUser } from "@/lib/shay-types";
import { cn } from "@/lib/cn";
import type { LucideIcon } from "lucide-react";

type AdminTab = "users" | "subscription" | "company-profile";
type TableTab = "users" | "invitations";

const USER_ROLE_OPTIONS = [
  { value: "all", label: "All Roles" },
  { value: "admin", label: "Admin" },
  { value: "manager", label: "Manager" },
  { value: "user", label: "User" },
];

const USER_STATUS_OPTIONS = [
  { value: "all", label: "All Status" },
  { value: "active", label: "Active" },
  { value: "inactive", label: "Inactive" },
];

const INVITATION_STATUS_OPTIONS = [
  { value: "all", label: "All Status" },
  { value: "pending", label: "Pending" },
  { value: "accepted", label: "Accepted" },
  { value: "expired", label: "Expired" },
];

const SETTINGS_TABS: Array<{
  id: AdminTab;
  label: string;
  icon: LucideIcon;
}> = [
  { id: "users", label: "Users", icon: Users2 },
  { id: "subscription", label: "Subscription", icon: CreditCard },
  { id: "company-profile", label: "Company Profile", icon: Building2 },
];

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

function UsersSection({
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
    </div>
  );
}

function SubscriptionSection({ company }: { company: ShayCompany | null }) {
  const plan = company?.subscription_plan || "Free";
  const maxUsers = company?.max_users || "0";
  const maxWorkspaces = company?.max_workspaces || "0";
  const maxStorage = company?.max_storage_gb || "0";

  return (
    <div className="space-y-6">
      <section className="rounded-[1.75rem] border border-navy-100 bg-[linear-gradient(135deg,_rgba(10,21,48,0.96),_rgba(20,34,69,0.92))] p-6 text-white shadow-soft">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold text-white/85">
              <Sparkles size={13} />
              Current Plan
            </div>
            <h2 className="mt-4 text-3xl font-semibold tracking-tight">
              {formatLabel(plan)}
            </h2>
            <p className="mt-3 max-w-2xl text-sm text-white/75">
              Keep track of your company limits and enabled capabilities from the admin hub.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <FeatureBadge label="AI Enabled" value={company?.ai_enabled ? "Yes" : "No"} />
            <FeatureBadge label="AI Provider" value={formatLabel(company?.ai_provider || "None")} />
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <PlanStatCard
          icon={<Users2 size={18} />}
          title="Max Users"
          value={maxUsers}
          helper="Seats available on this plan"
        />
        <PlanStatCard
          icon={<Building2 size={18} />}
          title="Max Workspaces"
          value={maxWorkspaces}
          helper="Workspace capacity"
        />
        <PlanStatCard
          icon={<CreditCard size={18} />}
          title="Max Storage"
          value={`${maxStorage} GB`}
          helper="Total storage allowance"
        />
        <PlanStatCard
          icon={<ShieldCheck size={18} />}
          title="Status"
          value={company?.is_active ? "Active" : "Inactive"}
          helper="Company account state"
        />
      </section>
    </div>
  );
}

function CompanyProfileSection({
  company,
  savingCompany,
  companyDraft,
  onCompanyDraftChange,
  onSaveCompanyProfile,
}: {
  company: ShayCompany | null;
  savingCompany: boolean;
  companyDraft: CompanyProfileDraft;
  onCompanyDraftChange: (patch: Partial<CompanyProfileDraft>) => void;
  onSaveCompanyProfile: () => void;
}) {
  if (!company) {
    return (
      <div className="rounded-[1.75rem] border border-navy-100 bg-white p-6 shadow-soft">
        <p className="text-sm text-subtle">Company profile is not available yet.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-[1.75rem] border border-navy-100 bg-white p-6 shadow-soft">
        <div className="grid gap-5 md:grid-cols-2">
          <ProfileField
            icon={<Building2 size={14} />}
            label="Company Name"
            value={companyDraft.name}
            placeholder="Giggso.Inc"
            onChange={(value) => onCompanyDraftChange({ name: value })}
          />
          <ProfileField
            icon={<Globe size={14} />}
            label="Company Website"
            value={companyDraft.website}
            placeholder="www.giggso.com"
            onChange={(value) => onCompanyDraftChange({ website: value })}
          />
          <ProfileField
            icon={<Mail size={14} />}
            label="Company Email Address"
            value={companyDraft.emailAddress}
            placeholder="sales@company.com"
            onChange={(value) => onCompanyDraftChange({ emailAddress: value })}
          />
          <div className="md:col-span-2">
            <ProfileTextarea
              icon={<Sparkles size={14} />}
              label="Company Description"
              value={companyDraft.description}
              placeholder="Describe your company, its mission, and key services..."
              onChange={(value) => onCompanyDraftChange({ description: value })}
            />
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end">
          <button
            type="button"
            onClick={onSaveCompanyProfile}
            disabled={savingCompany}
            className="focus-ring inline-flex items-center gap-2 rounded-2xl bg-navy-800 px-5 py-3 text-sm font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
          >
            {savingCompany ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </section>
    </div>
  );
}

function ProfileField({
  icon,
  label,
  value,
  placeholder,
  onChange,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-navy-700">
        <span className="text-subtle">{icon}</span>
        {label}
      </span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="focus-ring w-full rounded-2xl border border-navy-100 bg-white px-4 py-3 text-sm text-navy-900 placeholder:text-subtle"
      />
    </label>
  );
}

function ProfileTextarea({
  icon,
  label,
  value,
  placeholder,
  onChange,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-navy-700">
        <span className="text-subtle">{icon}</span>
        {label}
      </span>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        rows={5}
        className="focus-ring w-full rounded-2xl border border-navy-100 bg-white px-4 py-3 text-sm text-navy-900 placeholder:text-subtle"
      />
    </label>
  );
}

function PlanStatCard({
  icon,
  title,
  value,
  helper,
}: {
  icon: ReactNode;
  title: string;
  value: string;
  helper: string;
}) {
  return (
    <div className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-navy-700">{title}</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-navy-900">{value}</p>
          <p className="mt-2 text-sm text-subtle">{helper}</p>
        </div>
        <div className="flex size-11 items-center justify-center rounded-2xl bg-blue-50 text-blue-700">
          {icon}
        </div>
      </div>
    </div>
  );
}

function FeatureBadge({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/10 px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-white/60">{label}</p>
      <p className="mt-1 text-sm font-medium text-white">{value}</p>
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

function formatLabel(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
