import type { AskThreadMessage, ChatTurn } from "@/lib/types";

export function uid() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(
    bytes,
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join("-");
}

export function askThreadHref(shayWorkspaceId: string, threadId?: string) {
  return threadId
    ? `/workspaces/${shayWorkspaceId}/ask?thread=${encodeURIComponent(threadId)}`
    : `/workspaces/${shayWorkspaceId}/ask`;
}

export function threadMessageToTurn(message: AskThreadMessage): ChatTurn {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    sequenceNumber: message.sequence_number,
    requestId: message.request_id ?? null,
    citations: message.citations,
    usage: message.usage,
    jsonResponse: message.json_response ?? null,
    jsonButtonFlag: message.json_button_flag ?? false,
    beautify: message.beautify ?? "",
    beautifyButtonFlag: message.beautify_button_flag ?? false,
    apiShareButtonFlag: message.api_share_button_flag ?? false,
    sessionData: message.session_data ?? {},
  };
}
