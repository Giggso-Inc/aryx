"use client";

import type { RefObject } from "react";
import { MessageList } from "@/components/ask/MessageList";
import type { ChatTurn } from "@/lib/types";

export function AskTranscript({
  transcriptRef,
  loadingThread,
  showEmpty,
  loadingOlder,
  normalizedMessageSearch,
  messageSearch,
  filteredTurns,
  workspaceId,
  conversationId,
  autoScrollTranscript,
  onScrollNearTop,
}: {
  transcriptRef: RefObject<HTMLDivElement>;
  loadingThread: boolean;
  showEmpty: boolean;
  loadingOlder: boolean;
  normalizedMessageSearch: string;
  messageSearch: string;
  filteredTurns: ChatTurn[];
  workspaceId: number;
  conversationId: string;
  autoScrollTranscript: boolean;
  onScrollNearTop: () => void;
}) {
  if (loadingThread) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center text-[12px] text-subtle">
        Loading thread…
      </div>
    );
  }

  if (showEmpty) {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto animate-fade-in">
        <div className="w-full pb-6" />
      </div>
    );
  }

  return (
    <div
      ref={transcriptRef}
      className="min-h-0 flex-1 overflow-y-auto pb-6 pr-1"
      onScroll={(event) => {
        if (event.currentTarget.scrollTop < 48) {
          onScrollNearTop();
        }
      }}
    >
      {loadingOlder && (
        <div className="mb-3 text-center text-[11px] text-subtle">
          Loading older messages…
        </div>
      )}
      {normalizedMessageSearch && filteredTurns.length === 0 ? (
        <div className="py-12 text-center text-[12px] text-subtle" aria-live="polite">
          No messages match “{messageSearch.trim()}”.
        </div>
      ) : (
        <MessageList
          turns={filteredTurns}
          workspaceId={workspaceId}
          conversationId={conversationId}
          autoScroll={autoScrollTranscript && !normalizedMessageSearch}
        />
      )}
    </div>
  );
}
