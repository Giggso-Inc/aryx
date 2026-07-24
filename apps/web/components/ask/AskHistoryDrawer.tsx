"use client";

import { useEffect, useMemo, useState } from "react";
import { Plus, X } from "lucide-react";
import { api } from "@/lib/api";
import type { AskThreadSummary } from "@/lib/types";
import { AskSearchInput } from "./AskSearchInput";

interface AskHistoryDrawerProps {
  workspaceId: number;
  shayWorkspaceId: string | null;
  selectedThreadId: string | null;
  onClose: () => void;
  onSelectThread: (threadId: string) => void;
  onNewChat: () => void;
}

function relativeTimeLabel(value?: string): string {
  if (!value) return "";
  const time = new Date(value).getTime();
  if (Number.isNaN(time)) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - time) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} ${minutes === 1 ? "min" : "mins"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} ${days === 1 ? "day" : "days"} ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} ${months === 1 ? "month" : "months"} ago`;
  const years = Math.floor(months / 12);
  return `${years} ${years === 1 ? "year" : "years"} ago`;
}

function ThreadList({
  threads,
  selectedThreadId,
  onSelectThread,
}: {
  threads: AskThreadSummary[];
  selectedThreadId: string | null;
  onSelectThread: (threadId: string) => void;
}) {
  return (
    <ul className="space-y-2">
      {threads.map((thread) => (
        <li key={thread.id}>
          <button
            type="button"
            onClick={() => onSelectThread(thread.id)}
            className={`focus-ring w-full rounded-lg border p-3 text-left transition-colors ${
              thread.id === selectedThreadId
                ? "border-steel-300 bg-navy-50"
                : "border-navy-100 bg-white hover:border-steel-300 hover:bg-navy-50"
            }`}
          >
            <span className="line-clamp-2 block text-[12px] font-medium text-navy-800">
              {thread.title}
            </span>
            <span className="mt-2 flex items-center justify-between gap-3 text-[10px] text-subtle">
              <span>{thread.message_count || 0} messages</span>
              <span className="shrink-0">{relativeTimeLabel(thread.updated_at)}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Right-side Ask thread history with title filtering. */
export function AskHistoryDrawer({
  workspaceId,
  shayWorkspaceId,
  selectedThreadId,
  onClose,
  onSelectThread,
  onNewChat,
}: AskHistoryDrawerProps) {
  const [threads, setThreads] = useState<AskThreadSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    if (!shayWorkspaceId) {
      setThreads([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api.listAskThreads(workspaceId, shayWorkspaceId, 100)
      .then((nextThreads) => { if (!cancelled) setThreads(nextThreads); })
      .catch(() => { if (!cancelled) setThreads([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [shayWorkspaceId, workspaceId]);

  const filteredThreads = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLocaleLowerCase();
    if (!normalizedQuery) return threads;
    return threads.filter((thread) =>
      thread.title.toLocaleLowerCase().includes(normalizedQuery),
    );
  }, [searchQuery, threads]);

  const selectThread = (threadId: string) => {
    onSelectThread(threadId);
    onClose();
  };

  return (
    <aside
      aria-label="Ask thread history"
      className="fixed top-[68px] right-0 bottom-0 z-30 flex w-96 flex-col border-l border-navy-100 bg-white shadow-soft animate-rise"
    >
      <div className="flex items-center justify-between border-b border-navy-100 px-4 py-3">
        <h2 className="font-semibold text-navy-900">Ask Threads</h2>
        <div className="flex items-center gap-1">
          <button type="button" onClick={onNewChat}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-100 bg-white px-2.5 py-1.5 text-[11px] font-medium text-navy-600 shadow-sm hover:bg-navy-50">
            <Plus size={11} aria-hidden="true" /> New
          </button>
          <button type="button" onClick={onClose} aria-label="Close ask history"
            className="focus-ring rounded-md p-1 text-subtle hover:bg-navy-50">
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="border-b border-navy-100 px-3 py-3">
        <AskSearchInput
          value={searchQuery}
          onChange={setSearchQuery}
          placeholder="Search ask history..."
          ariaLabel="Search ask history"
          resultLabel={searchQuery.trim() ? `${filteredThreads.length} of ${threads.length}` : undefined}
          className="h-10"
        />
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {loading ? (
          <div className="py-8 text-center text-[12px] text-subtle">Loading…</div>
        ) : threads.length === 0 ? (
          <div className="py-8 text-center text-[12px] text-subtle italic">No threads yet</div>
        ) : filteredThreads.length === 0 ? (
          <div className="py-8 text-center text-[12px] text-subtle">
            No threads match “{searchQuery.trim()}”.
          </div>
        ) : (
          <ThreadList
            threads={filteredThreads}
            selectedThreadId={selectedThreadId}
            onSelectThread={selectThread}
          />
        )}
      </div>
    </aside>
  );
}
