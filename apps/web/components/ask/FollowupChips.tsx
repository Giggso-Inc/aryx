"use client";

import { cn } from "@/lib/cn";

interface Props {
  prompts: string[];
  onPick: (text: string) => void;
  className?: string;
}

/** Tappable follow-up prompts shown beneath the latest assistant message
 *  or as starter suggestions on an empty chat. */
export function FollowupChips({ prompts, onPick, className }: Props) {
  if (!prompts.length) return null;
  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
      {prompts.map((p) => (
        <button
          key={p}
          type="button"
          onClick={() => onPick(p)}
          className="focus-ring rounded-full border border-steel-200 bg-steel-50/80 px-4 py-2 text-sm font-medium text-navy-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] transition-colors hover:border-steel-400 hover:bg-steel-100"
        >
          {p}
        </button>
      ))}
    </div>
  );
}
