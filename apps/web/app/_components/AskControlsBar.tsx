"use client";

import { Clock, Plus } from "lucide-react";
import { AskSearchInput } from "@/components/ask/AskSearchInput";

export function AskControlsBar({
  messageSearch,
  onMessageSearchChange,
  resultCount,
  hasTurns,
  onToggleHistory,
  showNewAsk,
  onNewAsk,
}: {
  messageSearch: string;
  onMessageSearchChange: (value: string) => void;
  resultCount: number | null;
  hasTurns: boolean;
  onToggleHistory: () => void;
  showNewAsk: boolean;
  onNewAsk: () => void;
}) {
  return (
    <section
      aria-label="Ask controls"
      className="mb-4 flex shrink-0 items-center justify-between gap-3 rounded-2xl border border-navy-100 bg-white p-3 shadow-soft"
    >
      <AskSearchInput
        value={messageSearch}
        onChange={onMessageSearchChange}
        placeholder="Search this conversation..."
        ariaLabel="Search this conversation"
        resultLabel={resultCount !== null
          ? `${resultCount} ${resultCount === 1 ? "match" : "matches"}`
          : undefined}
        disabled={!hasTurns}
        className="h-10 min-w-0 flex-1 max-w-96 rounded-xl border-navy-200 bg-navy-50 shadow-none"
      />
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={onToggleHistory}
          className="focus-ring inline-flex h-10 items-center gap-1.5 rounded-xl border border-navy-200 bg-white px-3.5 text-[12px] font-medium text-navy-600 shadow-sm hover:bg-navy-50"
        >
          <Clock size={12} /> History
        </button>
        {showNewAsk && (
          <button
            type="button"
            onClick={onNewAsk}
            className="focus-ring inline-flex h-10 items-center gap-1.5 rounded-xl border border-navy-800 bg-navy-800 px-3.5 text-[12px] font-semibold text-white shadow-sm hover:bg-navy-700"
          >
            <Plus size={12} /> New Ask
          </button>
        )}
      </div>
    </section>
  );
}
