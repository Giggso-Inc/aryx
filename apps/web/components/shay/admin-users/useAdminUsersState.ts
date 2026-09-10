/**
 * Core state, data loading, tab/filter state for AdminUsersPage.
 *
 * Split out of useAdminUsersPage.ts (2026-09; Raven Style Compliance
 * Plan Phase 8b line-count reduction) — owns everything except the
 * write-path mutation handlers (see useAdminUsersActions.ts).
 */

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { buildCompanyDraft, type CompanyProfileDraft } from "./company-draft";
import type { AdminTab, TableTab } from "./types";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import type { ShayCompany, ShayInvitation, ShayUser } from "@/lib/shay-types";

export type TabFeedback = Partial<Record<AdminTab, string | null>>;

export function useAdminUsersState() {
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

  return {
    session,
    profile,
    company,
    setCompany,
    users,
    invitations,
    loading,
    saving,
    setSaving,
    savingCompany,
    setSavingCompany,
    errorsByTab,
    noticesByTab,
    inviteError,
    setInviteError,
    tab,
    tableTab,
    setTableTab,
    showInviteComposer,
    setShowInviteComposer,
    search,
    roleFilter,
    statusFilter,
    companyDraft,
    setCompanyDraft,
    filteredUsers,
    filteredInvitations,
    setTab,
    setSearch,
    setRoleFilter,
    setStatusFilter,
    setTabError,
    setTabNotice,
    load,
    openInviteModal,
    setUserTableState,
  };
}
