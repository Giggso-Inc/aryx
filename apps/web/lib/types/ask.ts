import type { Grounding } from "./lab";

export interface Citation {
  /** Entity id grounding a claim in the answer. */
  entity_id: number;
  /** Display label (entity name). */
  label: string;
  /** Optional entity type (Customer, Ticket, etc.) */
  type?: string;
}

export interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  menial_model?: string;
  answer_model?: string;
}

export interface AskResponse {
  answer: string;
  terms: string[];
  tools_called: unknown[];
  usage: Usage;
  citations?: Citation[];
  grounding?: Grounding | null;
  session_data?: Record<string, unknown>;
  cpq_payload?: Record<string, unknown> | null;
  // CPQ action buttons — populated once the guided config has enough
  // substance (3+ answered attrs, or past the configuring stage). No
  // second LLM call: these are projections of session state the engine
  // already computed this turn.
  json_response?: Record<string, unknown> | null;
  json_button_flag?: boolean;
  beautify?: string;
  beautify_rows?: { label: string; value: string }[];
  beautify_button_flag?: boolean;
  api_share?: Record<string, unknown> | null;
  api_share_button_flag?: boolean;
}

export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  content: string;
  sequenceNumber?: number;
  requestId?: string | null;
  citations?: Citation[];
  usage?: Usage;
  streaming?: boolean;
  jsonResponse?: Record<string, unknown> | null;
  jsonButtonFlag?: boolean;
  beautify?: string;
  beautifyRows?: { label: string; value: string }[];
  beautifyButtonFlag?: boolean;
  apiShareButtonFlag?: boolean;
  sessionData?: Record<string, unknown>;
  fromHistory?: boolean;
}

export interface AskThreadSummary {
  id: string;
  title: string;
  message_count: number;
  updated_at?: string;
}

export interface AskThreadMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sequence_number?: number;
  request_id?: string | null;
  created_at?: string;
  citations?: Citation[];
  usage?: Usage;
  json_response?: Record<string, unknown> | null;
  json_button_flag?: boolean;
  beautify?: string;
  beautify_button_flag?: boolean;
  api_share_button_flag?: boolean;
  session_data?: Record<string, unknown>;
}

export interface AskThreadResponse extends AskResponse {
  thread_id: string;
  request_id: string;
  replayed?: boolean;
  persistence_error?: string | null;
}

export interface AskHistoryTurn {
  id: number;
  workspace_id: number;
  question: string;
  answer: string;
  model?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  answer_model?: string;
  latency_ms?: number;
  ts: string;
}
