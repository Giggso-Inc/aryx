"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Header } from "@/components/brand/Header";
import { AskHistoryDrawer } from "@/components/ask/AskHistoryDrawer";
import { Composer } from "@/components/ask/Composer";
import { api } from "@/lib/api";
import { askThreadHref, threadMessageToTurn, uid } from "@/lib/ask-page-utils";
import { streamReveal } from "@/lib/stream";
import { useWorkspace } from "@/lib/workspace";
import { parseWorkspaceScope, workspaceStartHref } from "@/lib/workspace-route";
import type { ChatTurn, Citation, Usage } from "@/lib/types";
import { AskControlsBar } from "./_components/AskControlsBar";
import { AskTranscript } from "./_components/AskTranscript";

export default function HomePage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { workspaceId } = useWorkspace();
  const { shayWorkspaceId } = parseWorkspaceScope(pathname);
  const selectedThreadId = searchParams.get("thread");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [messageSearch, setMessageSearch] = useState("");
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
  // React state updates are asynchronous, so busy alone cannot reject two
  // submit events fired in the same render. This ref is the synchronous gate.
  const sendInFlightRef = useRef(false);
  const activeThreadRef = useRef<string | null>(selectedThreadId);
  const optimisticThreadRef = useRef<string | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  useEffect(() => () => { cancelRecoveryRef.current = true; }, []);

  useEffect(() => { setMessageSearch(""); }, [selectedThreadId]);

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

  const finishSend = () => {
    sendInFlightRef.current = false;
    setBusy(false);
  };

  const send = async (question?: string) => {
    const q = (question ?? input).trim();
    if (!q || busy || sendInFlightRef.current) return;
    sendInFlightRef.current = true;
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
        finishSend();
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
              // This answer was never seen in the live response (the connection
              // dropped before it arrived) — it's being read back out of
              // ask_history/thread-messages, not freshly computed, so surface
              // both the real usage (when the store has it) and a visible
              // "recovered from history" marker rather than presenting it as
              // if it were a normal live turn.
              const recoveredUsage: Usage | undefined =
                "content" in match
                  ? match.usage
                  : match.prompt_tokens !== undefined ||
                      match.completion_tokens !== undefined ||
                      match.answer_model
                    ? {
                        prompt_tokens: match.prompt_tokens ?? 0,
                        completion_tokens: match.completion_tokens ?? 0,
                        latency_ms: match.latency_ms ?? 0,
                        answer_model: match.answer_model,
                      }
                    : undefined;
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
                          usage: recoveredUsage,
                          fromHistory: true,
                          streaming: false,
                        }
                      : t,
                  ),
                );
                finishSend();
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
          finishSend();
        }
      } else {
        setTurns((prev) =>
          prev.map((t) =>
            t.id === assistantId
              ? { ...t, content: `Couldn't reach the API — ${message}`, streaming: false }
              : t,
          ),
        );
        finishSend();
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
  const normalizedMessageSearch = messageSearch.trim().toLocaleLowerCase();
  const filteredTurns = useMemo(() => {
    if (!normalizedMessageSearch) return turns;
    return turns.filter((turn) =>
      turn.content.toLocaleLowerCase().includes(normalizedMessageSearch),
    );
  }, [normalizedMessageSearch, turns]);

  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      {showHistory && (
        <AskHistoryDrawer
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
            setMessageSearch("");
            setSessionData({});
            setShowHistory(false);
          }}
        />
      )}

      <div className="app-shell-offset flex min-h-0 flex-1">
        <main className="workspace-section-shell flex h-[calc(100dvh-68px)] min-h-[calc(100vh-68px)] flex-1 flex-col overflow-hidden pt-4 pb-6">
          <AskControlsBar
            messageSearch={messageSearch}
            onMessageSearchChange={setMessageSearch}
            resultCount={normalizedMessageSearch ? filteredTurns.length : null}
            hasTurns={turns.length > 0}
            onToggleHistory={() => setShowHistory((v) => !v)}
            showNewAsk={!!(shayWorkspaceId && selectedThreadId)}
            onNewAsk={() => {
              if (!shayWorkspaceId) return;
              router.push(askThreadHref(shayWorkspaceId));
              setTurns([]);
              setInput("");
              setMessageSearch("");
              setSessionData({});
            }}
          />

          <AskTranscript
            transcriptRef={transcriptRef}
            loadingThread={loadingThread}
            showEmpty={showEmpty}
            loadingOlder={loadingOlder}
            normalizedMessageSearch={normalizedMessageSearch}
            messageSearch={messageSearch}
            filteredTurns={filteredTurns}
            workspaceId={workspaceId}
            conversationId={conversationIdRef.current}
            autoScrollTranscript={autoScrollTranscript}
            onScrollNearTop={() => void loadOlderMessages()}
          />

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
