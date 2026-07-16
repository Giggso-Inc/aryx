"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Clock, Plus, X } from "lucide-react";
import { Header } from "@/components/brand/Header";
import { Composer } from "@/components/ask/Composer";
import { MessageList } from "@/components/ask/MessageList";
import { FollowupChips } from "@/components/ask/FollowupChips";
import { WorkspacePeek } from "@/components/ask/WorkspacePeek";
import { api } from "@/lib/api";
import { streamReveal } from "@/lib/stream";
import { useWorkspace } from "@/lib/workspace";
import { parseWorkspaceScope, workspaceStartHref } from "@/lib/workspace-route";
import type { AskThreadMessage, AskThreadSummary, ChatTurn, Citation } from "@/lib/types";

const FOLLOWUPS = [
  "What else do we know about that Customer?",
  "Show me the underlying records",
  "What's missing or weak in this data?",
];

function uid() {
  return globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2, 10);
}

function askThreadHref(shayWorkspaceId: string, threadId?: string) {
  return threadId
    ? `/workspaces/${shayWorkspaceId}/ask?thread=${encodeURIComponent(threadId)}`
    : `/workspaces/${shayWorkspaceId}/ask`;
}

function relativeTimeLabel(value?: string) {
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

function threadMessageToTurn(message: AskThreadMessage): ChatTurn {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    sequenceNumber: message.sequence_number,
    requestId: message.request_id ?? null,
    citations: message.citations,
    usage: message.usage,
    jsonResponse: message.json_response ?? null,
    jsonButtonFlag: message.json_button_flag ?? false,
    beautify: message.beautify ?? "",
    beautifyButtonFlag: message.beautify_button_flag ?? false,
    apiShareButtonFlag: message.api_share_button_flag ?? false,
    sessionData: message.session_data ?? {},
  };
}

function HistoryDrawer({
  workspaceId,
  shayWorkspaceId,
  selectedThreadId,
  onClose,
  onSelectThread,
  onNewChat,
}: {
  workspaceId: number;
  shayWorkspaceId: string | null;
  selectedThreadId: string | null;
  onClose: () => void;
  onSelectThread: (threadId: string) => void;
  onNewChat: () => void;
}) {
  const [threads, setThreads] = useState<AskThreadSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!shayWorkspaceId) {
      setThreads([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    api.listAskThreads(workspaceId, shayWorkspaceId, 100)
      .then(setThreads)
      .catch(() => setThreads([]))
      .finally(() => setLoading(false));
  }, [shayWorkspaceId, workspaceId]);

  return (
    <div className="fixed top-[68px] right-0 bottom-0 z-30 flex w-96 flex-col border-l border-navy-100 bg-white shadow-soft animate-rise">
      <div className="flex items-center justify-between border-b border-navy-100 px-4 py-3">
        <h2 className="font-semibold text-navy-900">Ask Threads</h2>
        <div className="flex items-center gap-1">
          <button type="button" onClick={onNewChat}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-100 bg-white px-2.5 py-1.5 text-[11px] font-medium text-navy-600 shadow-sm hover:bg-navy-50">
            <Plus size={11} /> New
          </button>
          <button type="button" onClick={onClose}
            className="focus-ring rounded-md p-1 text-subtle hover:bg-navy-50">
            <X size={14} />
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {loading ? (
          <div className="py-8 text-center text-[12px] text-subtle">Loading…</div>
        ) : threads.length === 0 ? (
          <div className="py-8 text-center text-[12px] text-subtle italic">No threads yet</div>
        ) : (
          <ul className="space-y-2">
            {threads.map((thread) => (
              <li key={thread.id}
                className={`cursor-pointer rounded-lg border p-3 transition-colors ${
                  thread.id === selectedThreadId
                    ? "border-steel-300 bg-navy-50"
                    : "border-navy-100 bg-white hover:border-steel-300 hover:bg-navy-50"
                }`}
                onClick={() => { onSelectThread(thread.id); onClose(); }}>
                <p className="text-[12px] font-medium text-navy-800 line-clamp-2">{thread.title}</p>
                <div className="mt-2 flex items-center justify-between gap-3 text-[10px] text-subtle">
                  <span>{thread.message_count || 0} messages</span>
                  <span className="shrink-0">{relativeTimeLabel(thread.updated_at)}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function HomePage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { workspaceId } = useWorkspace();
  const { shayWorkspaceId } = parseWorkspaceScope(pathname);
  const selectedThreadId = searchParams.get("thread");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [loadingThread, setLoadingThread] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [hasOlderMessages, setHasOlderMessages] = useState(false);
  const [oldestSequence, setOldestSequence] = useState<number | null>(null);
  const [autoScrollTranscript, setAutoScrollTranscript] = useState(true);
  // CPQ session state — echoed back to the API on every turn so the engine
  // can continue the guided configuration without a server-side session store.
  const [sessionData, setSessionData] = useState<Record<string, unknown>>({});
  // Stable id for the lifetime of this chat — correlates Share-button posts
  // to /share-config with the conversation they came from.
  const conversationIdRef = useRef(uid());
  // Cancels an in-flight recovery poll when the component unmounts or a new
  // question is submitted before the previous recovery finishes.
  const cancelRecoveryRef = useRef(false);
  const activeThreadRef = useRef<string | null>(selectedThreadId);
  const optimisticThreadRef = useRef<string | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  useEffect(() => () => { cancelRecoveryRef.current = true; }, []);

  useEffect(() => {
    activeThreadRef.current = selectedThreadId;
    if (!shayWorkspaceId) return;
    if (!selectedThreadId) {
      setTurns([]);
      setSessionData({});
      return;
    }
    if (selectedThreadId === optimisticThreadRef.current) {
      setLoadingThread(false);
      return;
    }

    let cancelled = false;
    setLoadingThread(true);
    api.getAskThreadMessages(workspaceId, shayWorkspaceId, selectedThreadId, undefined, 50)
      .then((messages) => {
        if (cancelled) return;
        const nextTurns = messages.map(threadMessageToTurn);
        setTurns(nextTurns);
        setOldestSequence(messages[0]?.sequence_number ?? null);
        setHasOlderMessages(messages.length === 50);
        setAutoScrollTranscript(true);
        const lastSession = [...nextTurns]
          .reverse()
          .find((turn) => turn.role === "assistant" && turn.sessionData)?.sessionData;
        setSessionData(lastSession ?? {});
      })
      .catch(() => {
        if (!cancelled) setTurns([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingThread(false);
      });
    return () => { cancelled = true; };
  }, [selectedThreadId, shayWorkspaceId, workspaceId]);

  // First-run redirect: empty workspace → guided setup. "Empty" means
  // zero records, regardless of whether stub types exist.
  const [isEmptyWorkspace, setIsEmptyWorkspace] =
    useState<boolean | null>(null);
  useEffect(() => {
    api.getEntityGraph(workspaceId).then((d) => {
      const isEmpty = (d.entities || []).length === 0;
      setIsEmptyWorkspace(isEmpty);
      if (isEmpty && turns.length === 0) {
        router.replace(shayWorkspaceId ? workspaceStartHref(shayWorkspaceId) : "/start");
      }
    }).catch(() => setIsEmptyWorkspace(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router, shayWorkspaceId, turns.length, workspaceId]);

  const send = async (question?: string) => {
    const q = (question ?? input).trim();
    if (!q || busy) return;
    setAutoScrollTranscript(true);

    // Stamp submit time (with 5 s clock-skew buffer) so the recovery poll
    // never surfaces a stale answer from a prior identical question.
    const requestStartMs = Date.now() - 5_000;
    // Cancel any previous recovery poll that is still looping.
    cancelRecoveryRef.current = true;
    // Allow the new poll loop to run.
    cancelRecoveryRef.current = false;

    setInput("");
    setBusy(true);
    setAutoScrollTranscript(true);
    const requestId = uid();

    const userTurn: ChatTurn = { id: uid(), role: "user", content: q };
    const assistantId = uid();
    const placeholder: ChatTurn = {
      id: assistantId,
      role: "assistant",
      content: "",
      streaming: true,
    };
    setTurns((t) => [...t, userTurn, placeholder]);

    try {
      // Build conversation history from completed turns (exclude in-flight placeholder).
      const history = turns
        .filter((t) => t.role === "user" || (t.content && !t.streaming))
        .slice(-8)
        .map((t) => ({ role: t.role, text: t.content }));
      const threadId = shayWorkspaceId
        ? (selectedThreadId || activeThreadRef.current || uid())
        : "";
      if (shayWorkspaceId && !selectedThreadId) {
        activeThreadRef.current = threadId;
        optimisticThreadRef.current = threadId;
        router.replace(askThreadHref(shayWorkspaceId, threadId));
      }
      const resp = shayWorkspaceId
        ? await api.askThreadMessage({
            workspaceId,
            shayWorkspaceId,
            threadId,
            requestId,
            question: q,
            sessionData,
          })
        : await api.ask(q, workspaceId, history, sessionData);
      const citations: Citation[] =
        resp.citations ??
        (resp.terms || [])
          .slice(0, 5)
          .map((label, i) => ({ entity_id: i, label }));
      const responseRequestId =
        "request_id" in resp && typeof resp.request_id === "string"
          ? resp.request_id
          : requestId;

      // Persist CPQ session state so the next turn continues the configuration.
      if (resp.session_data && Object.keys(resp.session_data).length > 0) {
        setSessionData(resp.session_data);
      }

      streamReveal(resp.answer, (full) => {
        setTurns((prev) =>
          prev.map((t) =>
            t.id === assistantId ? { ...t, content: full } : t,
          ),
        );
      }, { msPerChunk: 18, chunkSize: 5 });

      // After reveal finishes (text length / chunk_size * ms), finalise.
      const totalMs = Math.ceil(resp.answer.length / 5) * 18 + 250;
      setTimeout(() => {
        setTurns((prev) =>
          prev.map((t) =>
            t.id === assistantId
              ? {
                  ...t,
                  content: resp.answer,
                  requestId: responseRequestId,
                  citations,
                  usage: resp.usage,
                  streaming: false,
                  jsonResponse: resp.json_response ?? null,
                  jsonButtonFlag: resp.json_button_flag ?? false,
                  beautify: resp.beautify ?? "",
                  beautifyRows: resp.beautify_rows ?? [],
                  beautifyButtonFlag: resp.beautify_button_flag ?? false,
                  apiShareButtonFlag: resp.api_share_button_flag ?? false,
                  sessionData: resp.session_data ?? {},
                }
              : t,
          ),
        );
        if (threadId === optimisticThreadRef.current) {
          optimisticThreadRef.current = null;
        }
        setBusy(false);
      }, totalMs);
    } catch (err: unknown) {
      if (shayWorkspaceId && activeThreadRef.current === optimisticThreadRef.current) {
        optimisticThreadRef.current = null;
      }
      const message = err instanceof Error ? err.message : String(err);

      // 502 / fetch-failed: TCP connection dropped after the LLM finished but before
      // the response reached the browser. FastAPI already persisted the answer to
      // ask_history — poll for it rather than immediately surfacing the error.
      // Skip recovery when the device is offline (those polls would also fail).
      const isFetchFailed =
        message.includes("fetch failed") ||
        message.includes("502") ||
        message.includes("Bad Gateway");
      const isOnline = typeof navigator === "undefined" || navigator.onLine;

      if (isFetchFailed && isOnline) {
        setTurns((prev) =>
          prev.map((t) =>
            t.id === assistantId
              ? { ...t, content: "Still processing — recovering your answer…", streaming: true }
              : t,
          ),
        );

        let recovered = false;
        // Two-phase poll: fast (20 × 3 s = 60 s) for typical cases, then slow
        // (56 × 15 s = 840 s) to cover the full 900 s headersTimeout window.
        const schedule = [
          ...Array(20).fill(3_000),
          ...Array(56).fill(15_000),
        ];
        for (const interval of schedule) {
          if (recovered || cancelRecoveryRef.current) break;
          await new Promise((r) => setTimeout(r, interval));
          if (cancelRecoveryRef.current) break;
          try {
            const match = shayWorkspaceId && activeThreadRef.current
              ? (await api.getAskThreadMessages(
                  workspaceId,
                  shayWorkspaceId,
                  activeThreadRef.current,
                  undefined,
                  50,
                )).find(
                  (h) =>
                    h.role === "assistant" &&
                    h.request_id === requestId &&
                    h.content &&
                    new Date(h.created_at ?? 0).getTime() >= requestStartMs,
                )
              : (await api.getAskHistory(workspaceId, 50)).find(
                  (h) =>
                    h.question.trim().toLowerCase() === q.trim().toLowerCase() &&
                    h.answer &&
                    new Date(h.ts).getTime() >= requestStartMs,
                );
            if (match) {
              recovered = true;
              const recoveredAnswer = "content" in match ? match.content : match.answer;
              // History entries don't carry terms, so citations aren't available
              // for recovered answers — the answer itself is still complete.
              const recoveryCitations: Citation[] = [];
              streamReveal(recoveredAnswer, (full) => {
                setTurns((prev) =>
                  prev.map((t) => (t.id === assistantId ? { ...t, content: full } : t)),
                );
              }, { msPerChunk: 18, chunkSize: 5 });
              const totalMs = Math.ceil(recoveredAnswer.length / 5) * 18 + 250;
              setTimeout(() => {
                if (cancelRecoveryRef.current) return;
                setTurns((prev) =>
                  prev.map((t) =>
                    t.id === assistantId
                      ? {
                          ...t,
                          content: recoveredAnswer,
                          requestId,
                          citations: recoveryCitations,
                          streaming: false,
                        }
                      : t,
                  ),
                );
                setBusy(false);
              }, totalMs);
            }
          } catch {
            // poll error — keep retrying
          }
        }

        if (!recovered && !cancelRecoveryRef.current) {
          setTurns((prev) =>
            prev.map((t) =>
              t.id === assistantId
                ? { ...t, content: `Couldn't reach the API — ${message}`, streaming: false }
                : t,
            ),
          );
          setBusy(false);
        }
      } else {
        setTurns((prev) =>
          prev.map((t) =>
            t.id === assistantId
              ? { ...t, content: `Couldn't reach the API — ${message}`, streaming: false }
              : t,
          ),
        );
        setBusy(false);
      }
    }
  };

  const loadOlderMessages = async () => {
    if (!selectedThreadId || !oldestSequence || loadingOlder || !hasOlderMessages) return;
    const transcript = transcriptRef.current;
    const previousScrollHeight = transcript?.scrollHeight ?? 0;
    const previousScrollTop = transcript?.scrollTop ?? 0;
    setLoadingOlder(true);
    setAutoScrollTranscript(false);
    try {
      if (!shayWorkspaceId) return;
      const older = await api.getAskThreadMessages(
        workspaceId,
        shayWorkspaceId,
        selectedThreadId,
        oldestSequence,
        50,
      );
      if (older.length > 0) {
        setTurns((prev) => [...older.map(threadMessageToTurn), ...prev]);
        setOldestSequence(older[0]?.sequence_number ?? oldestSequence);
        window.requestAnimationFrame(() => {
          if (!transcript) return;
          transcript.scrollTop =
            transcript.scrollHeight - previousScrollHeight + previousScrollTop;
        });
      }
      setHasOlderMessages(older.length === 50);
    } finally {
      setLoadingOlder(false);
    }
  };

  const empty = turns.length === 0;
  const showEmpty = empty && !loadingThread;

  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      {showHistory && (
        <HistoryDrawer
          workspaceId={workspaceId}
          shayWorkspaceId={shayWorkspaceId}
          selectedThreadId={selectedThreadId}
          onClose={() => setShowHistory(false)}
          onSelectThread={(threadId) => {
            if (shayWorkspaceId) router.push(askThreadHref(shayWorkspaceId, threadId));
          }}
          onNewChat={() => {
            if (shayWorkspaceId) router.push(askThreadHref(shayWorkspaceId));
            setTurns([]);
            setSessionData({});
            setShowHistory(false);
          }}
        />
      )}

      <div className="app-shell-offset flex min-h-0 flex-1">
        <main className="workspace-section-shell flex h-[calc(100dvh-68px)] min-h-[calc(100vh-68px)] flex-1 flex-col overflow-hidden pt-4 pb-6">
          <div className="mb-4 flex shrink-0 items-start gap-3">
            <WorkspacePeek workspaceId={workspaceId} className="mb-0 min-w-0 flex-1" />
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={() => setShowHistory((v) => !v)}
                className="focus-ring inline-flex h-[52px] items-center gap-1.5 rounded-2xl border border-navy-100 bg-white px-4 text-[12px] font-medium text-navy-600 shadow-soft hover:bg-navy-50"
              >
                <Clock size={12} /> History
              </button>
              {shayWorkspaceId && selectedThreadId && (
                <button
                  type="button"
                  onClick={() => {
                    router.push(askThreadHref(shayWorkspaceId));
                    setTurns([]);
                    setInput("");
                    setSessionData({});
                  }}
                  className="focus-ring inline-flex h-[52px] items-center gap-1.5 rounded-2xl border border-navy-800 bg-navy-800 px-4 text-[12px] font-semibold text-white shadow-soft hover:bg-navy-700"
                >
                  <Plus size={12} /> New Ask
                </button>
              )}
            </div>
          </div>

          {loadingThread ? (
            <div className="flex min-h-0 flex-1 items-center justify-center text-[12px] text-subtle">
              Loading thread…
            </div>
          ) : showEmpty ? (
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto animate-fade-in">
              <div className="w-full pb-6" />
            </div>
          ) : (
            <div
              ref={transcriptRef}
              className="min-h-0 flex-1 overflow-y-auto pb-6 pr-1"
              onScroll={(event) => {
                if (event.currentTarget.scrollTop < 48) {
                  void loadOlderMessages();
                }
              }}
            >
              {loadingOlder && (
                <div className="mb-3 text-center text-[11px] text-subtle">
                  Loading older messages…
                </div>
              )}
              <MessageList
                turns={turns}
                workspaceId={workspaceId}
                conversationId={conversationIdRef.current}
                autoScroll={autoScrollTranscript}
              />
              {!busy && (
                <div className="mt-6 pl-12">
                  <FollowupChips prompts={FOLLOWUPS} onPick={(p) => send(p)} />
                </div>
              )}
            </div>
          )}

          <div className="shrink-0 border-t border-transparent bg-canvas/95 pt-4 backdrop-blur supports-[backdrop-filter]:bg-canvas/88">
            <Composer
              value={input}
              onChange={setInput}
              onSubmit={() => send()}
              busy={busy}
              disabled={isEmptyWorkspace === true}
              placeholder={
                isEmptyWorkspace === true
                  ? "This workspace is empty — onboard data first to ask questions."
                  : turns.length === 0
                    ? "Ask Aryx about your knowledge graph…  (⌘K to focus)"
                    : "Continue the conversation…"
              }
            />
            <p className="mt-2 text-center text-[11px] text-subtle">
              Answers are grounded in the workspace&apos;s resolved entities.
              Provenance shown beneath each response.
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
