import type { ShayProfile, ShaySession } from "../shay-types";
import { requestJSON, resolvePlatformUrl, query } from "./http";
import { SHAY_BASE } from "./constants";

export const authApi = {
  login: (email_id: string, password: string) =>
    requestJSON<ShaySession>(SHAY_BASE, "/user-auth/login", {
      method: "POST",
      body: JSON.stringify({ email_id, password, encrypted: false }),
    }),

  forgotPassword: (payload: {
    email_id: string;
    base_url: string;
    app_name?: string;
    template_id?: string;
  }) =>
    requestJSON<{ message: string; email_sent: boolean; reset_link?: string | null }>(
      SHAY_BASE,
      "/user-auth/forgot-password",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  resetPassword: (payload: {
    token: string;
    new_password: string;
    confirm_new_password: string;
    encrypted: boolean;
  }) =>
    requestJSON<{ message: string; success: boolean }>(
      SHAY_BASE,
      "/user-auth/reset-password",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  register: (payload: {
    email_id: string;
    password: string;
    name?: string;
    company_id?: string;
    invite_id?: string;
    encrypted_param?: string;
    role?: string;
    }) =>
    requestJSON<ShaySession>(SHAY_BASE, "/user-auth/register", {
      method: "POST",
      body: JSON.stringify({ ...payload, encrypted: false }),
    }),

  decryptRegistrationInvite: (encryptedParam: string) =>
    requestJSON<{
      email_id: string;
      invite_id: string;
      company_id: string;
      role: string;
    }>(
      SHAY_BASE,
      `/user-auth/decrypt-registration${query({ e: encryptedParam })}`,
      {
        method: "GET",
      },
    ),

  autoLogin: (email: string, password: string) =>
    requestJSON<ShaySession>(
      SHAY_BASE,
      `/public/autoLogin?email=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`,
      {
        method: "POST",
      },
    ),

  verifyEmail: (token: string) =>
    requestJSON<ShaySession>(SHAY_BASE, "/public/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  companySignup: (payload: {
    name: string;
    domain?: string;
    contactEmail: string;
    userName: string;
    industry?: string;
    password: string;
    planId?: string;
  }) =>
    requestJSON<{ success: boolean; message: string }>(
      SHAY_BASE,
      "/public/companies",
      {
        method: "POST",
        body: JSON.stringify({
          ...payload,
          encrypted: false,
          platformName: "Aryx",
          platformUrl: resolvePlatformUrl(),
        }),
      },
    ),

  initiateSso: (provider: string, redirectUri: string, inviteId?: string) =>
    requestJSON<{ authorization_url: string; state: string }>(
      SHAY_BASE,
      `/sso/${provider}/initiate${query({ redirect_uri: redirectUri, invite_id: inviteId })}`,
    ),

  getProfile: (token: string) =>
    requestJSON<ShayProfile>(SHAY_BASE, "/user-auth/profile", undefined, token),
};
