export interface ShaySession {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user_id: string;
  email_id: string;
  name?: string | null;
  avatar_url?: string | null;
  role: string;
  company_id: string;
  company_name?: string | null;
  default_workspace_id?: string | null;
}

export interface ShayProfile {
  id: string;
  name: string;
  email_id: string;
  avatar_url?: string | null;
  role: string;
  company_id: string;
  is_active: boolean;
  is_verified: boolean;
  oauth_provider: string;
  preferences?: Record<string, unknown> | null;
  last_login?: string | null;
  created_datetime: string;
  updated_datetime: string;
}
