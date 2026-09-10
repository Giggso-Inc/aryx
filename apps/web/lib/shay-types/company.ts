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
