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
