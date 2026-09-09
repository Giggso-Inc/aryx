/**
 * Write-path mutation handlers for AdminUsersPage (invite/update/delete
 * users + invitations, save company profile).
 *
 * Split out of useAdminUsersPage.ts (2026-09; Raven Style Compliance
 * Plan Phase 8b line-count reduction). Takes the useAdminUsersState()
 * return value so both hooks share one source of truth for state.
 */

import { buildCompanyDraft } from "./company-draft";
import type { useAdminUsersState } from "./useAdminUsersState";
import { shayApi } from "@/lib/shay-api";
import type { ShayUser } from "@/lib/shay-types";

export function useAdminUsersActions(state: ReturnType<typeof useAdminUsersState>) {
  const {
    session, profile, company, setCompany, companyDraft, setCompanyDraft,
    setSaving, setSavingCompany, setInviteError, setTabError, setTabNotice,
    setShowInviteComposer, setUserTableState, load,
  } = state;

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

  return { inviteUsers, updateUser, deleteUser, deleteInvitation, saveCompanyProfile };
}
