"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle, CheckCircle2, Copy, Globe, KeyRound, Loader2, Plus,
  Settings2, Shield, Trash2, Cpu, RotateCcw,
} from "lucide-react";
import { Header } from "@/components/brand/Header";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import { cn } from "@/lib/cn";
import type { McpToken, McpTokenIssued } from "@/lib/types";

type Tab = "llm" | "mcp" | "ontology" | "danger";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-navy-100 bg-white shadow-soft">
      <div className="border-b border-navy-100 px-5 py-3.5">
        <h2 className="text-[13px] font-bold text-navy-900">{title}</h2>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button
      type="button"
      onClick={copy}
      className="focus-ring inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium text-steel-600 hover:bg-steel-50"
    >
      {copied ? <CheckCircle2 size={11} /> : <Copy size={11} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

// ── MCP Tab ──────────────────────────────────────────────────────────────────

function McpTab() {
  const { workspaceId } = useWorkspace();
  const [tokens, setTokens] = useState<McpToken[]>([]);
  const [newToken, setNewToken] = useState<McpTokenIssued | null>(null);
  const [label, setLabel] = useState("");
  const [issuing, setIssuing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<number | null>(null);

  // Build the MCP endpoint URL for copy-paste snippets
  const mcpUrl = typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:${window.location.port || "8000"}/mcp`
    : "http://localhost:8000/mcp";

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

  const SNIPPETS: Array<{ label: string; lang: string; code: (tok: string) => string }> = [
    {
      label: "Claude Desktop (claude_desktop_config.json)",
      lang: "json",
      code: (tok) => JSON.stringify({
        mcpServers: {
          aryx: {
            command: "npx",
            args: ["-y", "@modelcontextprotocol/server-sse", `${mcpUrl}?token=${tok}`],
          },
        },
      }, null, 2),
    },
    {
      label: "Claude Code (settings.json)",
      lang: "json",
      code: (tok) => JSON.stringify({
        mcpServers: {
          aryx: {
            type: "sse",
            url: `${mcpUrl}?token=${tok}`,
          },
        },
      }, null, 2),
    },
    {
      label: "Cursor (mcp.json)",
      lang: "json",
      code: (tok) => JSON.stringify({
        mcpServers: {
          aryx: {
            url: `${mcpUrl}?token=${tok}`,
            apiKey: tok,
          },
        },
      }, null, 2),
    },
  ];

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

      {/* Token list */}
      <Section title="Active Tokens">
        {loading ? (
          <div className="flex items-center gap-2 text-[13px] text-subtle"><Loader2 size={13} className="animate-spin" />Loading…</div>
        ) : activeTokens.length === 0 ? (
          <p className="text-[13px] text-subtle">No active tokens. Issue one above.</p>
        ) : (
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-navy-50">
                <th className="pb-2 text-left font-semibold text-navy-600">Label</th>
                <th className="pb-2 text-left font-semibold text-navy-600">Prefix</th>
                <th className="pb-2 text-left font-semibold text-navy-600">Issued</th>
                <th className="pb-2 text-right font-semibold text-navy-600" />
              </tr>
            </thead>
            <tbody className="divide-y divide-navy-50">
              {activeTokens.map((t) => (
                <tr key={t.id}>
                  <td className="py-2 text-navy-800">{t.label}</td>
                  <td className="py-2 font-mono text-[11px] text-subtle">{t.prefix}…</td>
                  <td className="py-2 text-subtle">{new Date(t.created_at).toLocaleDateString()}</td>
                  <td className="py-2 text-right">
                    <button
                      type="button"
                      onClick={() => revoke(t.id)}
                      disabled={revoking === t.id}
                      className="focus-ring inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-rose-600 hover:bg-rose-50 disabled:opacity-50"
                    >
                      {revoking === t.id ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* Config snippets */}
      {activeTokens.length > 0 && (
        <Section title="Connection Config">
          <p className="mb-4 text-[12px] text-subtle">
            Use any active token with the config snippets below. MCP endpoint: <code className="rounded bg-navy-50 px-1 text-[11px]">{mcpUrl}</code>
          </p>
          <div className="space-y-3">
            {SNIPPETS.map((s) => (
              <div key={s.label} className="rounded-lg border border-navy-100">
                <div className="flex items-center justify-between border-b border-navy-100 px-3 py-2">
                  <span className="text-[11px] font-medium text-navy-700">{s.label}</span>
                  <CopyButton value={s.code(activeTokens[0].prefix + "…")} />
                </div>
                <pre className="overflow-x-auto rounded-b-lg bg-navy-950 p-3 text-[11px] text-navy-200">
                  {s.code(activeTokens[0].prefix + "…")}
                </pre>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

// ── LLM Tab ──────────────────────────────────────────────────────────────────

function LlmTab() {
  const { workspaceId } = useWorkspace();
  const [config, setConfig] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getObservability(workspaceId).then((d) => {
      setConfig(d.model_config as Record<string, string> ?? {});
    }).catch(() => {}).finally(() => setLoading(false));
  }, [workspaceId]);

  if (loading) return (
    <div className="flex items-center gap-2 text-[13px] text-subtle py-4">
      <Loader2 size={13} className="animate-spin" />Loading…
    </div>
  );

  return (
    <div className="space-y-5">
      <Section title="Current LLM Configuration">
        <p className="mb-4 text-[12px] text-subtle">
          Model configuration is set via environment variables in <code className="rounded bg-navy-50 px-1 text-[11px]">docker-compose.yml</code>. Restart the API container after changing them.
        </p>
        <div className="overflow-hidden rounded-lg border border-navy-100">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-navy-50 bg-navy-50">
                <th className="px-3 py-2 text-left font-semibold text-navy-600">Key</th>
                <th className="px-3 py-2 text-left font-semibold text-navy-600">Value</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-navy-50">
              {Object.entries(config).map(([k, v]) => (
                <tr key={k}>
                  <td className="px-3 py-2 font-mono text-[12px] text-navy-700">{k}</td>
                  <td className="px-3 py-2 text-navy-800">{String(v)}</td>
                </tr>
              ))}
              {Object.keys(config).length === 0 && (
                <tr><td colSpan={2} className="px-3 py-4 text-center text-subtle">No config available</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="mt-4 rounded-lg border border-navy-100 bg-navy-50/40 p-3">
          <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-navy-500">Supported Env Vars</div>
          <div className="grid grid-cols-1 gap-1 text-[11px] font-mono text-navy-700 sm:grid-cols-2">
            {[
              "ARYX_LLM_MENIAL_MODEL", "ARYX_LLM_REASON_MODEL",
              "ARYX_LLM_ENDPOINT", "ARYX_LLM_TIMEOUT",
              "ARYX_PER_DOC_TIMEOUT", "ARYX_DOC_WORKERS",
            ].map((k) => <div key={k}>{k}</div>)}
          </div>
        </div>
      </Section>
    </div>
  );
}

// ── Ontology Tab ─────────────────────────────────────────────────────────────

function OntologyTab() {
  const [enabled, setEnabled] = useState<boolean>(true);
  const [includeProv, setIncludeProv] = useState<boolean>(false);
  const [baseUri, setBaseUri] = useState("");
  const [selectedFormats, setSelectedFormats] = useState<string[]>([]);
  const [availableFormats, setAvailableFormats] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => {
    Promise.allSettled([
      api.getOntologyConfig(),
      api.getOntologyFormats(),
    ]).then(([cfg, fmts]) => {
      if (cfg.status === "fulfilled") {
        setEnabled(cfg.value.enabled ?? true);
        setSelectedFormats(cfg.value.formats ?? []);
        setBaseUri(cfg.value.base_uri ?? "");
      }
      if (fmts.status === "fulfilled") {
        setAvailableFormats(fmts.value.map((f) => f.name));
      }
    }).finally(() => setLoading(false));
  }, []);

  const toggleFormat = (fmt: string) => {
    setSelectedFormats((prev) =>
      prev.includes(fmt) ? prev.filter((f) => f !== fmt) : [...prev, fmt],
    );
  };

  const save = async () => {
    setSaving(true); setError(null); setResult(null);
    try {
      await api.setOntologyConfig({
        enabled,
        formats: selectedFormats,
        base_uri: baseUri || undefined,
        include_provenance: includeProv,
      });
      setResult("Ontology interchange settings saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return (
    <div className="flex items-center gap-2 py-4 text-[13px] text-subtle">
      <Loader2 size={13} className="animate-spin" />Loading…
    </div>
  );

  return (
    <div className="space-y-5">
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          <AlertCircle size={13} /> {error}
        </div>
      )}
      {result && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] text-emerald-700">
          <CheckCircle2 size={13} /> {result}
        </div>
      )}

      <Section title="Ontology Interchange">
        <p className="mb-4 text-[12px] text-subtle">
          Controls whether the workspace ontology can be published to standard RDF/OWL formats
          (Turtle, JSON-LD, RDF-XML, N-Triples) and which formats are available on the Publish tab.
        </p>

        {/* Enable toggle */}
        <label className="mb-5 flex cursor-pointer items-center gap-3">
          <div className="relative">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="sr-only"
            />
            <div className={`h-5 w-9 rounded-full transition-colors ${enabled ? "bg-steel-500" : "bg-navy-200"}`} />
            <div className={`absolute top-0.5 size-4 rounded-full bg-white shadow transition-transform ${enabled ? "translate-x-4" : "translate-x-0.5"}`} />
          </div>
          <span className="text-[13px] font-medium text-navy-800">
            {enabled ? "Interchange enabled" : "Interchange disabled"}
          </span>
        </label>

        {enabled && (
          <>
            {/* Format checkboxes */}
            <div className="mb-5">
              <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-navy-600">
                Enabled formats
              </div>
              {availableFormats.length === 0 ? (
                <div className="flex flex-wrap gap-2">
                  {["turtle", "json-ld", "xml", "n-triples"].map((f) => (
                    <label key={f} className="flex cursor-pointer items-center gap-2 rounded-lg border border-navy-100 px-3 py-1.5 hover:bg-navy-50">
                      <input
                        type="checkbox"
                        checked={selectedFormats.includes(f)}
                        onChange={() => toggleFormat(f)}
                        className="accent-steel-500"
                      />
                      <span className="text-[12px] text-navy-800">{f}</span>
                    </label>
                  ))}
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {availableFormats.map((f) => (
                    <label key={f} className="flex cursor-pointer items-center gap-2 rounded-lg border border-navy-100 px-3 py-1.5 hover:bg-navy-50">
                      <input
                        type="checkbox"
                        checked={selectedFormats.includes(f)}
                        onChange={() => toggleFormat(f)}
                        className="accent-steel-500"
                      />
                      <span className="text-[12px] text-navy-800">{f}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            {/* Base URI */}
            <div className="mb-5">
              <label className="mb-1 block text-[11px] font-bold uppercase tracking-[0.1em] text-navy-600">
                Base URI (optional)
              </label>
              <input
                value={baseUri}
                onChange={(e) => setBaseUri(e.target.value)}
                placeholder="https://example.com/ontology/"
                className="focus-ring w-full rounded-lg border border-navy-100 px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
              />
              <p className="mt-1 text-[11px] text-subtle">
                Namespace prefix for published entities. Defaults to a workspace-specific URI.
              </p>
            </div>

            {/* Include provenance */}
            <label className="mb-5 flex cursor-pointer items-center gap-3">
              <input
                type="checkbox"
                checked={includeProv}
                onChange={(e) => setIncludeProv(e.target.checked)}
                className="accent-steel-500"
              />
              <span className="text-[13px] text-navy-800">Include provenance triples</span>
            </label>
          </>
        )}

        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {saving ? <Loader2 size={13} className="animate-spin" /> : null}
          Save settings
        </button>
      </Section>
    </div>
  );
}

// ── Danger Tab ───────────────────────────────────────────────────────────────

function DangerTab() {
  const { workspaceId, workspaces, refresh, setWorkspaceId } = useWorkspace();
  const [confirmText, setConfirmText] = useState("");
  const [resetting, setResetting] = useState(false);
  const [purging, setPurging] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const active = workspaces.find((w) => w.id === workspaceId);

  const purge = async () => {
    if (!confirm(`Purge all data from "${active?.name}"? Graph & entities will be deleted.`)) return;
    setPurging(true); setError(null); setResult(null);
    try {
      await api.purgeWorkspace(workspaceId);
      setResult(`Workspace "${active?.name}" data purged.`);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Purge failed");
    } finally {
      setPurging(false);
    }
  };

  const deleteWs = async () => {
    if (workspaceId === 1) return;
    if (!confirm(`Delete workspace "${active?.name}" permanently?`)) return;
    setDeleting(true); setError(null); setResult(null);
    try {
      await api.deleteWorkspace(workspaceId);
      await refresh();
      setWorkspaceId(1);
      setResult("Workspace deleted.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  const nuke = async () => {
    if (confirmText !== "NUKE") return;
    setResetting(true); setError(null); setResult(null);
    try {
      await api.nukeAllWorkspaces();
      await refresh();
      setWorkspaceId(1);
      setResult("Factory reset complete. All workspaces cleared.");
      setConfirmText("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reset failed");
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="space-y-5">
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          <AlertCircle size={13} /> {error}
        </div>
      )}
      {result && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] text-emerald-700">
          <CheckCircle2 size={13} /> {result}
        </div>
      )}

      {/* Purge workspace */}
      <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-5">
        <h3 className="mb-1 font-semibold text-amber-900">Purge Workspace Data</h3>
        <p className="mb-4 text-[12px] text-amber-800">
          Deletes all entities, relationships and embeddings from <strong>{active?.name}</strong>. The workspace itself is kept. This cannot be undone.
        </p>
        <button
          type="button"
          onClick={purge}
          disabled={purging}
          className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-[13px] font-semibold text-amber-800 hover:bg-amber-50 disabled:opacity-50"
        >
          {purging ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}
          Purge "{active?.name}"
        </button>
      </div>

      {/* Delete workspace */}
      {workspaceId !== 1 && (
        <div className="rounded-xl border border-rose-200 bg-rose-50/50 p-5">
          <h3 className="mb-1 font-semibold text-rose-900">Delete Workspace</h3>
          <p className="mb-4 text-[12px] text-rose-800">
            Permanently deletes <strong>{active?.name}</strong> and all its data. Workspace 1 cannot be deleted.
          </p>
          <button
            type="button"
            onClick={deleteWs}
            disabled={deleting}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-rose-600 px-3 py-1.5 text-[13px] font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
          >
            {deleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
            Delete "{active?.name}"
          </button>
        </div>
      )}

      {/* Factory reset */}
      <div className="rounded-xl border-2 border-rose-300 bg-rose-50 p-5">
        <h3 className="mb-1 font-bold text-rose-900">Factory Reset</h3>
        <p className="mb-4 text-[12px] text-rose-800">
          <strong>Nukes all workspaces</strong> — every entity, graph edge, embedding and job record is permanently deleted. Only use this to start completely fresh.
        </p>
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <label className="mb-1 block text-[11px] font-medium text-rose-700">
              Type <strong>NUKE</strong> to confirm
            </label>
            <input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="NUKE"
              className="focus-ring w-full rounded-lg border border-rose-200 bg-white px-3 py-2 text-[13px] text-rose-900 focus:border-rose-400"
            />
          </div>
          <button
            type="button"
            onClick={nuke}
            disabled={confirmText !== "NUKE" || resetting}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-rose-700 px-3 py-2 text-[13px] font-bold text-white hover:bg-rose-800 disabled:opacity-50"
          >
            {resetting ? <Loader2 size={13} className="animate-spin" /> : <Shield size={13} />}
            Nuke
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  const [tab, setTab] = useState<Tab>("mcp");

  const tabs: Array<{ id: Tab; label: string; icon: React.ReactNode }> = [
    { id: "llm",      label: "LLM Config",   icon: <Cpu size={14} /> },
    { id: "mcp",      label: "MCP Tokens",   icon: <KeyRound size={14} /> },
    { id: "ontology", label: "Ontology",      icon: <Globe size={14} /> },
    { id: "danger",   label: "Danger Zone",   icon: <Shield size={14} /> },
  ];

  return (
    <div className="flex min-h-screen flex-col">
      <Header workspaceId={workspaceId} onWorkspaceChange={setWorkspaceId} />

      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-8">
        <div className="mb-6">
          <h1 className="font-display text-2xl font-bold text-navy-900">Settings</h1>
          <p className="mt-0.5 text-[13px] text-subtle">LLM configuration, MCP tokens &amp; workspace management</p>
        </div>

        {/* Tabs */}
        <div className="mb-6 flex gap-0.5 rounded-xl bg-navy-50 p-1">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={cn(
                "focus-ring flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-all",
                tab === t.id
                  ? "bg-white text-navy-900 shadow-soft"
                  : "text-navy-600 hover:text-navy-900",
              )}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>

        {tab === "llm" && <LlmTab />}
        {tab === "mcp" && <McpTab />}
        {tab === "ontology" && <OntologyTab />}
        {tab === "danger" && <DangerTab />}
      </main>
    </div>
  );
}
