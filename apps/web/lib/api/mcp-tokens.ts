import type { McpToken, McpTokenIssued } from "../types";
import { fetchJSON } from "./core";

export const mcpTokensApi = {
  listMcpTokens: () =>
    fetchJSON<McpToken[]>("/admin/mcp/tokens"),

  issueMcpToken: (label: string) =>
    fetchJSON<McpTokenIssued>("/admin/mcp/tokens", {
      method: "POST",
      body: JSON.stringify({ label }),
    }),

  revokeMcpToken: (tokenId: number) =>
    fetchJSON<{ status: string }>(`/admin/mcp/tokens/${tokenId}`, {
      method: "DELETE",
    }),
};
