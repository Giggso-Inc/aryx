"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AuthGuard } from "./AuthGuard";
import { ShayPageShell } from "./ShayPageShell";
import { AdminUsersPageView } from "./AdminUsersPageView";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import type { ShayCompany, ShayInvitation, ShayUser } from "@/lib/shay-types";

type AdminTab = "users" | "subscription" | "company-profile";
type TableTab = "users" | "invitations";
type TabFeedback = Partial<Record<AdminTab, string | null>>;

export interface CompanyProfileDraft {
  name: string;
  website: string;
  emailAddress: string;
  description: string;
}

function readSetting(settings: Record<string, unknown> | null | undefined, ...keys: string[]) {
  if (!settings) return "";
  for (const key of keys) {
    const value = settings[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return "";
}

function buildCompanyDraft(company: ShayCompany): CompanyProfileDraft {
  return {
    name: company.name,
    website:
      readSetting(company.settings, "website", "companyWebsite", "company_website") ||
      company.domain ||
      "",
    emailAddress: readSetting(
      company.settings,
      "companyEmailAddress",
      "company_email_address",
      "contactEmail",
      "contact_email",
    ),
    description: company.description ?? readSetting(company.settings, "description"),
  };
}

export function AdminUsersPage() {
  const { session, profile } = useShayAuth();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [company, setCompany] = useState<ShayCompany | null>(null);
  const [users, setUsers] = useState<ShayUser[]>([]);
  const [invitations, setInvitations] = useState<ShayInvitation[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingCompany, setSavingCompany] = useState(false);
  const [errorsByTab, setErrorsByTab] = useState<TabFeedback>({});
  const [noticesByTab, setNoticesByTab] = useState<TabFeedback>({});
  const [inviteError, setInviteError] = useState<string | null>(null);
  const tabParam = searchParams.get("tab");
  const tab: AdminTab =
    tabParam === "subscription" || tabParam === "company-profile" ? tabParam : "users";
  const [tableTab, setTableTab] = useState<TableTab>("users");
  const [showInviteComposer, setShowInviteComposer] = useState(false);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [companyDraft, setCompanyDraft] = useState<CompanyProfileDraft>({
    name: "",
    website: "",
    emailAddress: "",
    description: "",
  });

  const setTabError = (targetTab: AdminTab, message: string | null) => {
    setErrorsByTab((current) => ({ ...current, [targetTab]: message }));
  };

  const setTabNotice = (targetTab: AdminTab, message: string | null) => {
    setNoticesByTab((current) => ({ ...current, [targetTab]: message }));
  };

  const load = async () => {
    if (!session) return;
    setLoading(true);
    setTabError("users", null);
    try {
      const [companyList, userList, invitationList] = await Promise.all([
        shayApi.getMyCompany(session.access_token),
        shayApi.listCompanyUsers(session.company_id, session.access_token),
        shayApi.listCompanyInvitations(session.company_id, session.access_token, {
          page: 1,
          size: 100,
          sort_by: "created_at",
          sort_order: "desc",
        }),
      ]);
      setCompany(companyList);
      setCompanyDraft(buildCompanyDraft(companyList));
      setUsers(userList.users);
      setInvitations(invitationList.invitations);
    } catch (nextError: unknown) {
      setTabError("users", nextError instanceof Error ? nextError.message : "Unable to load company users.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [session?.access_token, session?.company_id]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }
    const activeNotice = noticesByTab[tab];
    const activeError = errorsByTab[tab];
    if (!activeNotice && !activeError) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      if (activeNotice) {
        setTabNotice(tab, null);
      }
      if (activeError) {
        setTabError(tab, null);
      }
    }, 4000);

    return () => window.clearTimeout(timer);
  }, [errorsByTab, noticesByTab, tab]);

  const setTab = (nextTab: AdminTab) => {
    const params = new URLSearchParams(searchParams.toString());
    if (nextTab === "users") {
      params.delete("tab");
    } else {
      params.set("tab", nextTab);
    }
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname);
  };

  const openInviteModal = () => {
    setInviteError(null);
    setShowInviteComposer(true);
  };

  const setUserTableState = (nextTableTab: TableTab, nextStatusFilter: string) => {
    setTableTab(nextTableTab);
    setStatusFilter(nextStatusFilter);
  };

  const filteredUsers = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return users.filter((user) => {
      const matchesSearch =
        !needle ||
        user.name.toLowerCase().includes(needle) ||
        user.email_id.toLowerCase().includes(needle);
      const matchesRole = roleFilter === "all" || user.role === roleFilter;
      const matchesStatus =
        statusFilter === "all" ||
        (statusFilter === "active" ? user.is_active : !user.is_active);
      return matchesSearch && matchesRole && matchesStatus;
    });
  }, [roleFilter, search, statusFilter, users]);

  const filteredInvitations = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return invitations.filter((invitation) => {
      const matchesSearch =
        !needle ||
        invitation.email.toLowerCase().includes(needle) ||
        (invitation.invited_by.username ?? "").toLowerCase().includes(needle) ||
        (invitation.invited_by.userEmail ?? "").toLowerCase().includes(needle);
      const matchesRole = roleFilter === "all" || invitation.role === roleFilter;
      const matchesStatus =
        statusFilter === "all" || invitation.status.toLowerCase() === statusFilter;
      return matchesSearch && matchesRole && matchesStatus;
    });
  }, [invitations, roleFilter, search, statusFilter]);

  const inviteUsers = async (invites: Array<{ email: string; role: string }>) => {
    if (!session || !profile?.id || invites.length === 0) {
      setInviteError("Your account is still loading. Please try again in a moment.");
      return;
    }
    setSaving(true);
    setInviteError(null);
    setTabNotice("users", null);
    setTabError("users", null);
    try {
      const result = await shayApi.bulkInviteUsers(
        {
          users: invites.map((invite) => ({
            email: invite.email,
            company_id: session.company_id,
            role: invite.role,
          })),
          user_id: profile.id,
          platform_name: "Aryx",
        },
        session.access_token,
      );
      setShowInviteComposer(false);
      setInviteError(null);
      setUserTableState("invitations", "pending");
      setTabNotice("users", result.message || (invites.length === 1 ? "Invitation sent." : "Invitations sent."));
      await load();
    } catch (nextError: unknown) {
      setInviteError(nextError instanceof Error ? nextError.message : "Unable to invite user.");
    } finally {
      setSaving(false);
    }
  };

  const updateUser = async (userId: string, payload: { role?: string; is_active?: boolean }) => {
    if (!session) return;
    setSaving(true);
    setTabError("users", null);
    setTabNotice("users", null);
    try {
      await shayApi.updateCompanyUser(session.company_id, userId, payload, session.access_token);
      setTabNotice("users", "User updated.");
      await load();
    } catch (nextError: unknown) {
      setTabError("users", nextError instanceof Error ? nextError.message : "Unable to update user.");
    } finally {
      setSaving(false);
    }
  };

  const deleteUser = async (user: ShayUser) => {
    if (!session) return;
    if (!window.confirm(`Delete ${user.name || user.email_id} from this company?`)) return;
    setSaving(true);
    setTabError("users", null);
    setTabNotice("users", null);
    try {
      await shayApi.deleteCompanyUser(session.company_id, user.id, session.access_token);
      setTabNotice("users", "User deleted.");
      await load();
    } catch (nextError: unknown) {
      setTabError("users", nextError instanceof Error ? nextError.message : "Unable to delete user.");
    } finally {
      setSaving(false);
    }
  };

  const deleteInvitation = async (email: string) => {
    if (!session) return;
    if (!window.confirm(`Delete pending invitations for ${email}?`)) return;
    setSaving(true);
    setTabError("users", null);
    setTabNotice("users", null);
    try {
      const result = await shayApi.deletePendingInvitation(
        session.company_id,
        email,
        session.access_token,
      );
      setUserTableState("invitations", "pending");
      setTabNotice("users", result.message);
      await load();
    } catch (nextError: unknown) {
      setTabError("users", nextError instanceof Error ? nextError.message : "Unable to delete invitation.");
    } finally {
      setSaving(false);
    }
  };

  const saveCompanyProfile = async () => {
    if (!session || !company) return;
    setSavingCompany(true);
    setTabError("company-profile", null);
    setTabNotice("company-profile", null);
    try {
      const nextSettings: Record<string, unknown> = {
        ...(company.settings ?? {}),
      };

      if (companyDraft.website.trim()) nextSettings.website = companyDraft.website.trim();
      if (companyDraft.emailAddress.trim()) {
        nextSettings.companyEmailAddress = companyDraft.emailAddress.trim();
      }
      if (companyDraft.description.trim()) nextSettings.description = companyDraft.description.trim();

      const updated = await shayApi.updateCompany(
        company.id,
        {
          name: companyDraft.name.trim() || company.name,
          description: companyDraft.description.trim() || undefined,
          settings: nextSettings,
        },
        session.access_token,
      );

      setCompany(updated);
      setCompanyDraft(buildCompanyDraft(updated));
      setTabNotice("company-profile", "Company profile updated.");
    } catch (nextError: unknown) {
      setTabError("company-profile", nextError instanceof Error ? nextError.message : "Unable to save company profile.");
    } finally {
      setSavingCompany(false);
    }
  };

  return (
    <AuthGuard>
      <ShayPageShell
        showHero={false}
        title="Admin Hub"
        description="Manage company users and invitations."
      >
        <AdminUsersPageView
          company={company}
          users={users}
          invitations={invitations}
          loading={loading}
          saving={saving}
          savingCompany={savingCompany}
          error={errorsByTab[tab] ?? null}
          notice={noticesByTab[tab] ?? null}
          tab={tab}
          tableTab={tableTab}
          showInviteComposer={showInviteComposer}
          search={search}
          roleFilter={roleFilter}
          statusFilter={statusFilter}
          companyDraft={companyDraft}
          filteredUsers={filteredUsers}
          filteredInvitations={filteredInvitations}
          currentUserId={session.user_id}
          onTabChange={setTab}
          onTableTabChange={setTableTab}
          onOpenInviteModal={openInviteModal}
          onCloseInviteModal={() => {
            setShowInviteComposer(false);
            setInviteError(null);
          }}
          onSearchChange={setSearch}
          onRoleFilterChange={setRoleFilter}
          onStatusFilterChange={setStatusFilter}
          onCompanyDraftChange={(patch) =>
            setCompanyDraft((current) => ({ ...current, ...patch }))
          }
          onSaveCompanyProfile={saveCompanyProfile}
          onSendInvites={inviteUsers}
          inviteError={inviteError}
          onUpdateUser={updateUser}
          onDeleteUser={deleteUser}
          onDeleteInvitation={deleteInvitation}
          onShowAllUsers={() => setUserTableState("users", "all")}
          onShowActiveUsers={() => setUserTableState("users", "active")}
          onShowInactiveUsers={() => setUserTableState("users", "inactive")}
          onShowPendingInvitations={() => setUserTableState("invitations", "pending")}
        />
      </ShayPageShell>
    </AuthGuard>
  );
}
