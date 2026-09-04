"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Bot, ExternalLink } from "lucide-react";
import { Composer } from "@/components/ask/Composer";
import { MessageList } from "@/components/ask/MessageList";
import { shayApi } from "@/lib/shay-api";
import { streamReveal } from "@/lib/stream";
import { workspaceSectionHref } from "@/lib/workspace-route";
import { formatWorkspaceName } from "@/lib/workspace-name";
import type { ChatTurn } from "@/lib/types";
import { SessionSidebar } from "./shay-chat-surface/SessionSidebar";
import { toCitations, toUsage, uid } from "./shay-chat-surface/helpers";

export function ShayChatSurface({
  workspaceId,
  threadId,
  workspaceName,
}: {
  workspaceId: string;
  threadId: string;
  workspaceName?: string;
}) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    shayApi.getBridgeHistory(threadId)
      .then((history) => {
        if (!active) return;
        const nextTurns: ChatTurn[] = [];
        history.forEach((item) => {
          nextTurns.push({
            id: `${item.id}-q`,
            role: "user",
            content: item.question,
          });
          nextTurns.push({
            id: `${item.id}-a`,
            role: "assistant",
            content: item.answer,
            citations: toCitations(
              (item.citations as Array<{
                entity_id?: number;
                entity_name?: string;
                entity_type?: string;
                marker?: number;
              }>) ?? [],
            ),
            usage: toUsage(item.usage),
          });
        });
        setTurns(nextTurns);
      })
      .catch((nextError: unknown) => {
        if (!active) return;
        setError(nextError instanceof Error ? nextError.message : "Unable to load ask history.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [threadId]);

  const subtitle = useMemo(() => {
    if (!workspaceName) return "Merged chat session backed by Aryx Ask.";
    return `${formatWorkspaceName(workspaceName)} chat session backed by Aryx Ask and shared citations.`;
  }, [workspaceName]);

  const send = async () => {
    const question = input.trim();
    if (!question || busy) return;
    setBusy(true);
    setInput("");
    setError(null);

    const userTurn: ChatTurn = { id: uid(), role: "user", content: question };
    const assistantId = uid();
    setTurns((current) => [
      ...current,
      userTurn,
      { id: assistantId, role: "assistant", content: "", streaming: true },
    ]);

    try {
      const answer = await shayApi.askBridge({
        shay_workspace_id: workspaceId,
        shay_thread_id: threadId,
        question,
      });
      const citations = toCitations(answer.citations || answer.grounding?.citations || []);
      streamReveal(answer.answer, (full) => {
        setTurns((current) => current.map((turn) => (
          turn.id === assistantId ? { ...turn, content: full } : turn
        )));
      }, { msPerChunk: 18, chunkSize: 6 });
      const totalMs = Math.ceil(answer.answer.length / 6) * 18 + 250;
      setTimeout(() => {
        setTurns((current) => current.map((turn) => (
          turn.id === assistantId
            ? {
                ...turn,
                content: answer.answer,
                citations,
                usage: toUsage(answer.usage),
                streaming: false,
              }
            : turn
        )));
        setBusy(false);
      }, totalMs);
    } catch (nextError: unknown) {
      const message = nextError instanceof Error ? nextError.message : "Unable to reach Aryx Ask.";
      setTurns((current) => current.map((turn) => (
        turn.id === assistantId
          ? { ...turn, content: message, streaming: false }
          : turn
      )));
      setBusy(false);
      setError(message);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div className="space-y-5 rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-navy-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-navy-700">
              <Bot size={13} />
              Aryx Ask
            </div>
            <h2 className="mt-3 text-2xl font-semibold text-navy-900">
              Conversation {threadId.slice(0, 8)}
            </h2>
            <p className="mt-2 text-sm text-subtle">{subtitle}</p>
          </div>
          <Link
            href={workspaceSectionHref(workspaceId, "ask")}
            className="inline-flex items-center gap-1 rounded-full border border-navy-100 px-3 py-1.5 text-xs font-medium text-navy-700 hover:bg-navy-50"
          >
            Open Aryx Ask
            <ExternalLink size={12} />
          </Link>
        </div>
        {loading ? (
          <div className="rounded-2xl border border-dashed border-navy-100 bg-canvas px-4 py-10 text-center text-sm text-subtle">
            Loading mapped chat history...
          </div>
        ) : (
          <>
            {turns.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-navy-100 bg-canvas px-4 py-10 text-center text-sm text-subtle">
                Start the first conversation for this Aryx Ask session.
              </div>
            ) : (
              <MessageList turns={turns} />
            )}
            <Composer
              value={input}
              onChange={setInput}
              onSubmit={send}
              busy={busy}
              placeholder="Ask about this workspace, its data sources, or the graph behind them..."
            />
          </>
        )}
        {error ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {error}
          </div>
        ) : null}
      </div>
      <SessionSidebar workspaceId={workspaceId} workspaceName={workspaceName} threadId={threadId} />
    </div>
  );
}
