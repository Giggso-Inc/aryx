import type { ChatTurn } from "@/lib/types";

export function UsageMeta({ turn }: { turn: ChatTurn }) {
  if (!turn.fromHistory) return null;

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="inline-flex items-center gap-1.5 rounded-full border border-steel-200 bg-white px-2.5 py-1 text-[11px] font-medium text-navy-700 shadow-sm">
        <span className="size-1.5 rounded-full bg-steel-500" />
        <span>Recovered from history</span>
      </span>
    </div>
  );
}
