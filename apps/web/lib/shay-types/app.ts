export interface ShayApp {
  id: string;
  app_name: string;
  app_key: string;
  app_description?: string | null;
  app_image?: string | null;
  is_active: boolean;
  is_public: boolean;
  version?: string | null;
  category?: string | null;
  sub_category?: string | null;
  tags?: unknown[] | null;
  created_at: string;
  updated_at: string;
}

export interface ShayAppList {
  apps: ShayApp[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export interface ShayWorkspaceAppConnection {
  id: string;
  app_id?: string | null;
  workspace_id: string;
  level: string;
  connected_by: string;
  connector?: {
    user_id: string;
    name?: string | null;
    email_id?: string | null;
    avatar_url?: string | null;
  } | null;
  connection_name?: string | null;
  connection_status: string;
  connection_settings?: Record<string, unknown> | null;
  webhook_url?: string | null;
  callback_url?: string | null;
  is_active: boolean;
  auto_sync: boolean;
  sync_interval: number;
  last_sync_at?: string | null;
  sync_status?: string | null;
  error_message?: string | null;
  provider?: string | null;
  provider_account_id?: string | null;
  auth_type?: string | null;
  last_token_refresh?: string | null;
  token_expires_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ShayWorkspaceAppConnectionList {
  connections: ShayWorkspaceAppConnection[];
  total: number;
  page: number;
  size: number;
  pages: number;
}
