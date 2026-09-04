"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Loader2, Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { McpToken, McpTokenIssued } from "@/lib/types";
import { CopyButton, Section } from "./shared";
import { McpConnectionConfig } from "./McpConnectionConfig";
import { McpTokenList } from "./McpTokenList";

export function McpTab() {
  const [tokens, setTokens] = useState<McpToken[]>([]);
  const [newToken, setNewToken] = useState<McpTokenIssued | null>(null);
  const [label, setLabel] = useState("");
  const [issuing, setIssuing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<number | null>(null);

  // Build the MCP endpoint URL for copy-paste snippets.
  // Use NEXT_PUBLIC_MCP_URL set at build time for production deployments.
  // window.location.port is empty on standard ports (80/443), so never
  // derive the MCP port from it — use the known default (8765) instead.
  const mcpUrl = process.env.NEXT_PUBLIC_MCP_URL
    ?? (typeof window !== "undefined"
      ? `${window.location.protocol}//${window.location.hostname}:8765/mcp`
      : "http://localhost:8765/mcp");

  const load = useCallback(async () => {
    try {
      const list = await api.listMcpTokens();
      setTokens(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const issue = async () => {
    setIssuing(true); setError(null); setNewToken(null);
    try {
      const t = await api.issueMcpToken(label || "unnamed");
      setNewToken(t);
      setLabel("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Issue failed");
    } finally {
      setIssuing(false);
    }
  };

  const revoke = async (id: number) => {
    setRevoking(id);
    try {
      await api.revokeMcpToken(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Revoke failed");
    } finally {
      setRevoking(null);
    }
  };

  const activeTokens = tokens.filter((t) => !t.revoked_at);

  return (
    <div className="space-y-5">
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          <AlertCircle size={13} />
          {error}
        </div>
      )}

      {/* Issue new token */}
      <Section title="Issue Bearer Token">
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <label className="mb-1 block text-[11px] font-medium text-navy-600">Label (optional)</label>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && issue()}
              placeholder="e.g. Claude Desktop — dev laptop"
              className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
            />
          </div>
          <button
            type="button"
            onClick={issue}
            disabled={issuing}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-3 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
          >
            {issuing ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
            Issue
          </button>
        </div>
        {newToken && (
          <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[11px] font-semibold text-emerald-700">Token issued — copy now, shown once</span>
              <CopyButton value={newToken.token} />
            </div>
            <code className="block break-all font-mono text-[11px] text-emerald-800">{newToken.token}</code>
          </div>
        )}
      </Section>

      <McpTokenList
        loading={loading}
        activeTokens={activeTokens}
        revoking={revoking}
        onRevoke={revoke}
      />

      {activeTokens.length > 0 && (
        <McpConnectionConfig mcpUrl={mcpUrl} tokenPrefix={activeTokens[0].prefix} />
      )}
    </div>
  );
}
