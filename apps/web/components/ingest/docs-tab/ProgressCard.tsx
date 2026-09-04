import { Loader2 } from "lucide-react";

export function ProgressCard({
  step,
  title,
  pct,
  stage,
  fallbackStage,
  barColor,
}: {
  step: number;
  title: string;
  pct: number | null | undefined;
  stage: string | null | undefined;
  fallbackStage: string;
  barColor: string;
}) {
  return (
    <div className="rounded-xl border border-navy-100 bg-white p-5 shadow-soft animate-fade-in">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex size-6 items-center justify-center rounded-full bg-navy-800 text-[11px] font-bold text-white">{step}</span>
        <h3 className="font-semibold text-navy-900">{title}</h3>
        <Loader2 size={14} className="animate-spin text-steel-500 ml-auto" />
      </div>
      {pct != null && (
        <div className="mb-2 h-2 w-full overflow-hidden rounded-full bg-navy-100">
          <div className={`h-full rounded-full ${barColor} transition-all duration-500`} style={{ width: `${pct}%` }} />
        </div>
      )}
      <p className="text-[12px] text-subtle">{stage || fallbackStage}</p>
    </div>
  );
}
