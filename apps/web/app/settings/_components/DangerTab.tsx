"use client";

import { useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Shield } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";

export function DangerTab() {
  const { refresh, setWorkspaceId } = useWorkspace();
  const [confirmText, setConfirmText] = useState("");
  const [resetting, setResetting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
