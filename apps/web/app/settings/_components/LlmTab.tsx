"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import { Section } from "./shared";

const LLM_CONFIG_ALLOWLIST = new Set([
  "ARYX_LLM_MENIAL_MODEL", "ARYX_LLM_REASON_MODEL",
  "ARYX_LLM_ENDPOINT", "ARYX_LLM_TIMEOUT",
  "ARYX_PER_DOC_TIMEOUT", "ARYX_DOC_WORKERS", "ARYX_LLM_PROVIDER",
]);

export function LlmTab() {
  const { workspaceId } = useWorkspace();
  const [config, setConfig] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getObservability(workspaceId).then((d) => {
      const raw = d.model_config as Record<string, string> ?? {};
      const filtered = Object.fromEntries(
        Object.entries(raw).filter(([k]) => LLM_CONFIG_ALLOWLIST.has(k)),
      );
      setConfig(filtered);
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
            {[...LLM_CONFIG_ALLOWLIST].map((k) => <div key={k}>{k}</div>)}
          </div>
        </div>
      </Section>
    </div>
  );
}
