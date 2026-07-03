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

export interface ShayCompany {
  id: string;
  name: string;
  domain?: string | null;
  description?: string | null;
  is_active: boolean;
  subscription_plan: string;
  max_users: string;
  max_workspaces: string;
  max_storage_gb: string;
  ai_enabled: boolean;
  ai_provider: string;
  ai_webhook_url?: string | null;
  settings?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface ShayUser {
  id: string;
  name: string;
  email_id: string;
  avatar_url?: string | null;
  company_id: string;
  role: string;
  is_active: boolean;
  last_login?: string | null;
  created_datetime: string;
  updated_datetime: string;
}

export interface ShayUserList {
  users: ShayUser[];
  total: number;
  total_active: number;
  total_inactive: number;
  total_admin: number;
  page: number;
  size: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface ShayInvitationInvitedBy {
  userId: string;
  userEmail?: string | null;
  username?: string | null;
  avatar_url?: string | null;
  role?: string | null;
}

export interface ShayInvitation {
  id: string;
  email: string;
  role: string;
  company_id: string;
  invited_by: ShayInvitationInvitedBy;
  status: string;
  message?: string | null;
  created_at: string;
  expires_at: string;
}

export interface ShayInvitationList {
  invitations: ShayInvitation[];
  total: number;
  page: number;
  size: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface ShayWorkspace {
  id: string;
  name: string;
  description?: string | null;
  company_id: string;
  is_active: boolean;
  is_public: boolean;
  ai_enabled: boolean;
  ai_provider: string;
  ai_model: string;
  max_messages: number;
  max_attachments: number;
  workspace_type?: string | null;
  user_id?: string | null;
  created_by?: string | null;
  settings?: Record<string, unknown> | null;
  bridge?: ShayBridgeWorkspaceMap | null;
  created_at: string;
  updated_at: string;
}

export interface ShayWorkspaceList {
  workspaces: ShayWorkspace[];
  total: number;
  page: number;
  size: number;
}

export interface ShayWorkspaceMember {
  id: string;
  user_id: string;
  workspace_id: string;
  level: string;
  role: string;
  is_active: boolean;
  permissions?: Record<string, unknown> | null;
  invited_by?: string | null;
  joined_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  name?: string | null;
  email?: string | null;
}

export interface ShayWorkspaceMemberList {
  members: ShayWorkspaceMember[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

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

export interface ShayDatasource {
  id: string;
  level: string;
  workspace_id?: string | null;
  channel_id?: string | null;
  thread_id?: string | null;
  message_id?: string | null;
  added_by?: string | null;
  name: string;
  filename?: string | null;
  storage_type: string;
  provider?: string | null;
  app_type?: string | null;
  config?: Record<string, unknown> | null;
  datasource_metadata?: Record<string, unknown> | null;
  vault_unique_id?: string | null;
  file_size?: number | null;
  file_type?: string | null;
  file_url?: string | null;
  log_type?: string | null;
  is_active: boolean;
  is_connected: boolean;
  is_processed: boolean;
  processing_status: string;
  error_message?: string | null;
  is_embedding_required: boolean;
  embedding_status: number;
  last_processed_at?: string | null;
  processing_time?: number | null;
  record_count: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ShayDatasourceList {
  items: ShayDatasource[];
  total: number;
  page: number;
  page_size: number;
}

export interface ShayBridgeWorkspaceMap {
  shay_workspace_id: string;
  aryx_workspace_id: number;
  company_id?: string | null;
  sync_state?: Record<string, unknown>;
  created?: boolean;
}

export interface ShayBridgeChatTurn {
  id: number;
  shay_thread_id: string;
  aryx_workspace_id: number;
  question: string;
  answer: string;
  citations: Array<Record<string, unknown>>;
  usage: Record<string, unknown>;
  grounding: Record<string, unknown>;
  created_at: string;
}

export interface ShayBridgeThread {
  shay_thread_id: string;
  aryx_workspace_id: number;
  ask_session_key: string;
  updated_at: string;
  title: string;
  turn_count: number;
}

export interface ShayBridgeAskResponse {
  shay_thread_id: string;
  shay_workspace_id: string;
  aryx_workspace_id: number;
  answer: string;
  terms: string[];
  tools_called: unknown[];
  usage: {
    prompt_tokens?: number;
    completion_tokens?: number;
    latency_ms?: number;
    menial_model?: string;
    answer_model?: string;
  };
  grounding?: {
    citations?: Array<{
      entity_id?: number;
      entity_name?: string;
      entity_type?: string;
      marker?: number;
    }>;
  } | null;
  citations: Array<{
    entity_id?: number;
    entity_name?: string;
    entity_type?: string;
    marker?: number;
  }>;
}
