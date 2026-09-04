import type { ShayInvitationList, ShayUserList } from "../shay-types";
import { requestJSON, cachedRequestJSON, invalidateShayCache, query } from "./http";
import { SHAY_BASE } from "./constants";

export const companyUsersApi = {
  listCompanyUsers: (companyId: string, token: string) =>
    cachedRequestJSON<ShayUserList>(
      `company-users:${companyId}`,
      10_000,
      SHAY_BASE,
      `/users/company/${companyId}/users`,
      token,
    ),

  listCompanyInvitations: (
    companyId: string,
    token: string,
    params?: {
      page?: number;
      size?: number;
      search?: string;
      role?: string;
      sort_by?: "email" | "created_at";
      sort_order?: "asc" | "desc";
    },
    ) =>
    requestJSON<ShayInvitationList>(
      SHAY_BASE,
      `/companies/${companyId}/invitations${query(params ?? {})}`,
      undefined,
      token,
    ),

  updateCompanyUser: (
    companyId: string,
    userId: string,
    payload: { role?: string; is_active?: boolean; name?: string; avatar_url?: string },
    token: string,
  ) =>
    requestJSON(
      SHAY_BASE,
      `/users/company/${companyId}/users/${userId}`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
      token,
    ).then((result) => {
      invalidateShayCache(`company-users:${companyId}`);
      return result;
    }),

  deleteCompanyUser: (companyId: string, userId: string, token: string) =>
    requestJSON<{ success?: boolean; message?: string }>(
      SHAY_BASE,
      `/users/company/${companyId}/users/${userId}`,
      {
        method: "DELETE",
      },
      token,
    ).then((result) => {
      invalidateShayCache(`company-users:${companyId}`);
      return result;
    }),

  inviteUser: (
    payload: {
      email: string;
      company_id: string;
      role: string;
      user_id?: string;
      platform_name?: string;
    },
    token: string,
  ) =>
    requestJSON(
      SHAY_BASE,
      "/user-auth/invite",
      {
        method: "POST",
        body: JSON.stringify({ ...payload }),
      },
      token,
    ),

  inviteCompanyUser: (
    companyId: string,
    payload: { email: string; role: string; message?: string | null },
    token: string,
  ) =>
    requestJSON(
      SHAY_BASE,
      `/companies/${companyId}/invite`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
      token,
    ),

  bulkInviteUsers: (
    payload: {
      users: Array<{ email: string; company_id: string; role: string }>;
      template_id?: string;
      user_id?: string;
      platform_name?: string;
    },
    token: string,
  ) =>
    requestJSON<{
      message: string;
      total_invited: number;
      successful_invitations: Array<{
        message: string;
        invite_id: string;
        email_id: string;
        registration_link: string;
        expires_at: string;
      }>;
      failed_invitations: Array<Record<string, unknown>>;
    }>(
      SHAY_BASE,
      "/user-auth/bulk-invite",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
      token,
    ).then((result) => {
      const companyId = payload.users[0]?.company_id;
      if (companyId) {
        invalidateShayCache(`company-users:${companyId}`);
      }
      return result;
    }),

  deletePendingInvitation: (companyId: string, email: string, token: string) =>
    requestJSON<{ message: string; deleted_count: number; email: string; company_id: string }>(
      SHAY_BASE,
      `/users/company/${companyId}/pendingInvitedUsers/${encodeURIComponent(email)}`,
      {
        method: "DELETE",
      },
      token,
    ).then((result) => {
      invalidateShayCache(`company-users:${companyId}`);
      return result;
    }),
};
