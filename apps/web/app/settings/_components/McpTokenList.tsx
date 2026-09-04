"use client";

import { Loader2, Trash2 } from "lucide-react";
import type { McpToken } from "@/lib/types";
import { Section } from "./shared";

export function McpTokenList({
  loading,
  activeTokens,
  revoking,
  onRevoke,
}: {
  loading: boolean;
  activeTokens: McpToken[];
  revoking: number | null;
  onRevoke: (id: number) => void;
}) {
  return (
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
                    onClick={() => onRevoke(t.id)}
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
  );
}
