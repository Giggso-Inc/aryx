import type { Citation, Usage } from "@/lib/types";

export function uid() {
  return Math.random().toString(36).slice(2, 10);
}

export function toCitations(items: Array<{
  entity_id?: number;
  entity_name?: string;
  entity_type?: string;
  marker?: number;
}>): Citation[] {
  return items.map((item, index) => ({
    entity_id: item.entity_id ?? index,
    label: item.entity_name ?? `Source ${index + 1}`,
    type: item.entity_type,
  }));
}

export function toUsage(value: unknown): Usage | undefined {
  if (!value || typeof value !== "object") return undefined;
  const usage = value as Record<string, unknown>;
  const promptTokens = usage.prompt_tokens;
  const completionTokens = usage.completion_tokens;
  const latencyMs = usage.latency_ms;
  if (
    typeof promptTokens !== "number"
    || typeof completionTokens !== "number"
    || typeof latencyMs !== "number"
  ) {
    return undefined;
  }
  return {
    prompt_tokens: promptTokens,
    completion_tokens: completionTokens,
    latency_ms: latencyMs,
    menial_model: typeof usage.menial_model === "string" ? usage.menial_model : undefined,
    answer_model: typeof usage.answer_model === "string" ? usage.answer_model : undefined,
  };
}
