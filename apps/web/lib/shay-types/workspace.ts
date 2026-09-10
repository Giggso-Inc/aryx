import type { ShayBridgeWorkspaceMap } from "./bridge";

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
