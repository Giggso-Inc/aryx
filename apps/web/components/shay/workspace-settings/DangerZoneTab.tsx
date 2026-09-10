import { AlertTriangle, Loader2 } from "lucide-react";
import { InlineNotice } from "./shared";

export function DangerZoneTab({
  bridgeReady,
  dangerError,
  dangerNotice,
  deleting,
  onDeleteWorkspace,
  onPurgeWorkspace,
  purging,
}: {
  bridgeReady: boolean;
  dangerError: string | null;
  dangerNotice: string | null;
  deleting: boolean;
  onDeleteWorkspace: () => void;
  onPurgeWorkspace: () => void;
  purging: boolean;
}) {
  return (
    <div className="space-y-5">
      {dangerNotice ? <InlineNotice tone="success">{dangerNotice}</InlineNotice> : null}
      {dangerError ? <InlineNotice tone="error">{dangerError}</InlineNotice> : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-[1.5rem] border border-amber-200 bg-[linear-gradient(180deg,rgba(255,250,235,0.95),rgba(255,244,214,0.9))] p-5">
          <div className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-800">
            <AlertTriangle size={14} />
            Purge workspace data
          </div>
          <p className="mt-4 text-sm leading-6 text-amber-900">
            Deletes all entities, relationships, and Aryx graph data for this workspace while keeping the workspace itself.
          </p>
          <button
            type="button"
            onClick={onPurgeWorkspace}
            disabled={purging || !bridgeReady}
            className="focus-ring mt-5 inline-flex items-center gap-2 rounded-2xl border border-amber-300 bg-white px-4 py-2 text-sm font-semibold text-amber-800 hover:bg-amber-50 disabled:opacity-50"
          >
            {purging ? <Loader2 size={15} className="animate-spin" /> : <AlertTriangle size={15} />}
            Purge workspace data
          </button>
        </div>

        <div className="rounded-[1.5rem] border border-rose-200 bg-[linear-gradient(180deg,rgba(255,245,246,0.98),rgba(255,236,239,0.94))] p-5">
          <div className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-rose-800">
            <AlertTriangle size={14} />
            Delete workspace data
          </div>
          <p className="mt-4 text-sm leading-6 text-rose-900">
            Permanently deletes this workspace and all of its data. Workspace 1 remains protected.
          </p>
          <button
            type="button"
            onClick={onDeleteWorkspace}
            disabled={deleting}
            className="focus-ring mt-5 inline-flex items-center gap-2 rounded-2xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
          >
            {deleting ? <Loader2 size={15} className="animate-spin" /> : <AlertTriangle size={15} />}
            Delete workspace data
          </button>
        </div>
      </div>
    </div>
  );
}
