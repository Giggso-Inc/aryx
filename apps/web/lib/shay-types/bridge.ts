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
