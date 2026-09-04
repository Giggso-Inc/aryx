import type {
  AbResult, AskHistoryTurn, AskResponse, AskThreadMessage, AskThreadResponse,
  AskThreadSummary, ReasonerCheck,
} from "../types";
import { fetchJSON } from "./core";

export const askApi = {
  ask: (question: string, workspaceId: number, history: unknown[] = [], sessionData: Record<string, unknown> = {}) =>
    fetchJSON<AskResponse>("/ask", {
      method: "POST",
      body: JSON.stringify({ question, workspace_id: workspaceId, history, session_data: sessionData }),
    }),

  askThreadMessage: (args: {
    workspaceId: number;
    shayWorkspaceId: string;
    threadId: string;
    requestId: string;
    question: string;
    sessionData?: Record<string, unknown>;
  }) =>
    fetchJSON<AskThreadResponse>("/ask/threads/message", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: args.workspaceId,
        shay_workspace_id: args.shayWorkspaceId,
        thread_id: args.threadId,
        request_id: args.requestId,
        question: args.question,
        session_data: args.sessionData ?? {},
      }),
    }),

  shareConfig: (args: {
    workspaceId: number; conversationId: string; configJson: Record<string, unknown>;
    endpointUrl: string; authHeaderName: string; authHeaderValue: string;
    extraHeaders?: Record<string, string>;
  }) =>
    fetchJSON<{ shared: boolean; partner_response: unknown }>("/share-config", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: args.workspaceId,
        conversation_id: args.conversationId,
        config_json: args.configJson,
        endpoint_url: args.endpointUrl,
        auth_header_name: args.authHeaderName,
        auth_header_value: args.authHeaderValue,
        extra_headers: args.extraHeaders ?? {},
      }),
    }),

  getAskHistory: (workspaceId: number, limit = 50) =>
    fetchJSON<AskHistoryTurn[]>(
      `/ask/history?workspace_id=${workspaceId}&limit=${limit}`,
    ),

  listAskThreads: (workspaceId: number, shayWorkspaceId: string, limit = 50) =>
    fetchJSON<AskThreadSummary[]>(
      `/ask/threads?workspace_id=${workspaceId}&shay_workspace_id=${encodeURIComponent(shayWorkspaceId)}&limit=${limit}`,
    ),

  getAskThreadMessages: (
    workspaceId: number,
    shayWorkspaceId: string,
    threadId: string,
    beforeSequence?: number,
    limit = 50,
  ) =>
    fetchJSON<AskThreadMessage[]>(
      `/ask/threads/${encodeURIComponent(threadId)}/messages?workspace_id=${workspaceId}` +
        `&shay_workspace_id=${encodeURIComponent(shayWorkspaceId)}&limit=${limit}` +
        (beforeSequence ? `&before_sequence=${beforeSequence}` : ""),
    ),

  labAb: (question: string, workspaceId: number) =>
    fetchJSON<AbResult & { error?: string }>("/lab/ab", {
      method: "POST",
      body: JSON.stringify({ question, workspace_id: workspaceId }),
    }),

  labReasoner: (workspaceId: number) =>
    fetchJSON<ReasonerCheck & { error?: string }>(
      `/lab/reasoner?workspace_id=${workspaceId}`,
    ),
};
