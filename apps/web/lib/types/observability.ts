export interface ObservabilityData {
  jobs: { total: number; complete?: number; running?: number; failed?: number };
  llm: {
    total_calls?: number; total_tokens?: number; avg_latency_ms?: number;
    prompt_tokens?: number; completion_tokens?: number;
  };
  llm_recent: Array<{
    role: string; model: string; prompt_tokens: number;
    completion_tokens: number; latency_ms: number; source: string;
    error?: string; ts: string;
  }>;
  graph: { entities: number; relationships: number };
  model_config: Record<string, unknown>;
  platform: Record<string, unknown>;
}
