import { CheckCircle2, Loader2 } from "lucide-react";

export function Empty() {
  return (
    <div className="rounded-xl border border-dashed border-navy-200 px-5 py-10 text-center">
      <CheckCircle2 size={20} className="mx-auto text-emerald-500" />
      <p className="mt-2 text-[13px] text-navy-700">All caught up.</p>
      <p className="mt-1 text-[11px] text-subtle">
        Aryx has no pending questions for this workspace.
      </p>
    </div>
  );
}

export function Loading() {
  return (
    <div className="flex items-center justify-center py-10 text-subtle">
      <Loader2 size={18} className="animate-spin" />
    </div>
  );
}
