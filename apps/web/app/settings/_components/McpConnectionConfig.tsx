"use client";

import { CopyButton, Section } from "./shared";

// Tokens are passed via Authorization header, not URL query params.
// URL query params appear in server logs, browser history, and Referer headers.
function snippets(mcpUrl: string): Array<{ label: string; code: (tok: string) => string }> {
  return [
    {
      label: "Claude Desktop (claude_desktop_config.json)",
      code: (tok) => JSON.stringify({
        mcpServers: {
          aryx: {
            type: "sse",
            url: mcpUrl,
            headers: { "Authorization": `Bearer ${tok}` },
          },
        },
      }, null, 2),
    },
    {
      label: "Claude Code (settings.json)",
      code: (tok) => JSON.stringify({
        mcpServers: {
          aryx: {
            type: "sse",
            url: mcpUrl,
            headers: { "Authorization": `Bearer ${tok}` },
          },
        },
      }, null, 2),
    },
    {
      label: "Cursor (mcp.json)",
      code: (tok) => JSON.stringify({
        mcpServers: {
          aryx: {
            url: mcpUrl,
            apiKey: tok,
          },
        },
      }, null, 2),
    },
  ];
}

export function McpConnectionConfig({ mcpUrl, tokenPrefix }: { mcpUrl: string; tokenPrefix: string }) {
  const displayToken = `${tokenPrefix}…`;
  return (
    <Section title="Connection Config">
      <p className="mb-4 text-[12px] text-subtle">
        Use any active token with the config snippets below. MCP endpoint: <code className="rounded bg-navy-50 px-1 text-[11px]">{mcpUrl}</code>
      </p>
      <div className="space-y-3">
        {snippets(mcpUrl).map((s) => (
          <div key={s.label} className="rounded-lg border border-navy-100">
            <div className="flex items-center justify-between border-b border-navy-100 px-3 py-2">
              <span className="text-[11px] font-medium text-navy-700">{s.label}</span>
              <CopyButton value={s.code(displayToken)} />
            </div>
            <pre className="overflow-x-auto rounded-b-lg bg-navy-950 p-3 text-[11px] text-navy-200">
              {s.code(displayToken)}
            </pre>
          </div>
        ))}
      </div>
    </Section>
  );
}
