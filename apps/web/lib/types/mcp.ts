export interface McpToken {
  id: number;
  label: string;
  prefix: string;
  created_at: string;
  revoked_at?: string | null;
}

export interface McpTokenIssued extends McpToken {
  token: string;
}
