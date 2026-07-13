"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Clock, Download, X } from "lucide-react";
import { Header } from "@/components/brand/Header";
import { Composer } from "@/components/ask/Composer";
import { MessageList } from "@/components/ask/MessageList";
import { FollowupChips } from "@/components/ask/FollowupChips";
import { WorkspacePeek } from "@/components/ask/WorkspacePeek";
import { api } from "@/lib/api";
import { streamReveal } from "@/lib/stream";
import { useWorkspace } from "@/lib/workspace";
import { parseWorkspaceScope, workspaceStartHref } from "@/lib/workspace-route";
import type { AskHistoryTurn, ChatTurn, Citation } from "@/lib/types";

const FOLLOWUPS = [
  "What else do we know about that Customer?",
  "Show me the underlying records",
  "What's missing or weak in this data?",
];

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

function HistoryDrawer({
  workspaceId,
  onClose,
  onReplay,
}: {
  workspaceId: number;
  onClose: () => void;
  onReplay: (q: string) => void;
}) {
  const [history, setHistory] = useState<AskHistoryTurn[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getAskHistory(workspaceId, 50)
      .then(setHistory)
      .catch(() => setHistory([]))
      .finally(() => setLoading(false));
  }, [workspaceId]);

  const downloadCsv = () => {
    const rows = [["question", "answer", "ts"], ...history.map((h) => [
      `"${h.question.replace(/"/g, '""')}"`,
      `"${h.answer.replace(/"/g, '""')}"`,
      h.ts,
    ])];
    const blob = new Blob([rows.map((r) => r.join(",")).join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `aryx-history-ws${workspaceId}.csv`;
    a.click();
  };

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(history, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `aryx-history-ws${workspaceId}.json`;
    a.click();
  };

  return (
    <div className="fixed top-[68px] right-0 bottom-0 z-30 flex w-96 flex-col border-l border-navy-100 bg-white shadow-soft animate-rise">
      <div className="flex items-center justify-between border-b border-navy-100 px-4 py-3">
        <h2 className="font-semibold text-navy-900">Ask History</h2>
        <div className="flex items-center gap-1">
          <button type="button" onClick={downloadCsv}
            className="focus-ring flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-navy-600 hover:bg-navy-50">
            <Download size={11} /> CSV
          </button>
          <button type="button" onClick={downloadJson}
            className="focus-ring flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-navy-600 hover:bg-navy-50">
            <Download size={11} /> JSON
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
        ) : history.length === 0 ? (
          <div className="py-8 text-center text-[12px] text-subtle italic">No history yet</div>
        ) : (
          <ul className="space-y-3">
            {history.map((h) => (
              <li key={h.id}
                className="cursor-pointer rounded-xl border border-navy-100 bg-white p-3 hover:border-steel-300 hover:bg-navy-50 transition-colors"
                onClick={() => { onReplay(h.question); onClose(); }}>
                {/* Question */}
                <div className="flex items-start gap-2">
                  <span className="mt-0.5 shrink-0 rounded-full bg-navy-800 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">Q</span>
                  <p className="text-[12px] font-medium text-navy-800 line-clamp-2">{h.question}</p>
                </div>
                {/* Answer */}
                {h.answer && (
                  <div className="mt-2 flex items-start gap-2">
                    <span className="mt-0.5 shrink-0 rounded-full bg-steel-100 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-steel-600">A</span>
                    <p className="text-[11px] text-navy-600 line-clamp-3">{h.answer}</p>
                  </div>
                )}
                <p className="mt-2 text-[10px] text-subtle">{new Date(h.ts).toLocaleString()}</p>
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
  const { workspaceId } = useWorkspace();
  const { shayWorkspaceId } = parseWorkspaceScope(pathname);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  // CPQ session state — echoed back to the API on every turn so the engine
  // can continue the guided configuration without a server-side session store.
  const [sessionData, setSessionData] = useState<Record<string, unknown>>({});
  // Stable id for the lifetime of this chat — correlates Share-button posts
  // to /share-config with the conversation they came from.
  const conversationIdRef = useRef(uid());
  // Cancels an in-flight recovery poll when the component unmounts or a new
  // question is submitted before the previous recovery finishes.
  const cancelRecoveryRef = useRef(false);
  useEffect(() => () => { cancelRecoveryRef.current = true; }, []);

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

    // Stamp submit time (with 5 s clock-skew buffer) so the recovery poll
    // never surfaces a stale answer from a prior identical question.
    const requestStartMs = Date.now() - 5_000;
    // Cancel any previous recovery poll that is still looping.
    cancelRecoveryRef.current = true;
    // Allow the new poll loop to run.
    cancelRecoveryRef.current = false;

    setInput("");
    setBusy(true);

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
      const resp = await api.ask(q, workspaceId, history, sessionData);
      // Lightweight citation extraction — V1: derive from terms.
      const citations: Citation[] = (resp.terms || [])
        .slice(0, 5)
        .map((label, i) => ({ entity_id: i, label }));

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
                  citations,
                  usage: resp.usage,
                  streaming: false,
                  jsonResponse: resp.json_response ?? null,
                  jsonButtonFlag: resp.json_button_flag ?? false,
                  beautify: resp.beautify ?? "",
                  beautifyButtonFlag: resp.beautify_button_flag ?? false,
                  apiShareButtonFlag: resp.api_share_button_flag ?? false,
                }
              : t,
          ),
        );
        setBusy(false);
      }, totalMs);
    } catch (err: unknown) {
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
            const history = await api.getAskHistory(workspaceId, 50);
            const match = history.find(
              (h) =>
                h.question.trim().toLowerCase() === q.trim().toLowerCase() &&
                h.answer &&
                new Date(h.ts).getTime() >= requestStartMs,
            );
            if (match) {
              recovered = true;
              // History entries don't carry terms, so citations aren't available
              // for recovered answers — the answer itself is still complete.
              const recoveryCitations: Citation[] = [];
              streamReveal(match.answer, (full) => {
                setTurns((prev) =>
                  prev.map((t) => (t.id === assistantId ? { ...t, content: full } : t)),
                );
              }, { msPerChunk: 18, chunkSize: 5 });
              const totalMs = Math.ceil(match.answer.length / 5) * 18 + 250;
              setTimeout(() => {
                if (cancelRecoveryRef.current) return;
                setTurns((prev) =>
                  prev.map((t) =>
                    t.id === assistantId
                      ? { ...t, content: match.answer, citations: recoveryCitations, streaming: false }
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

  const empty = turns.length === 0;

  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      {showHistory && (
        <HistoryDrawer
          workspaceId={workspaceId}
          onClose={() => setShowHistory(false)}
          onReplay={(q) => { setInput(q); send(q); }}
        />
      )}

      <div className="app-shell-offset flex min-h-0 flex-1">
        <main className="workspace-section-shell flex h-[calc(100dvh-68px)] min-h-[calc(100vh-68px)] flex-1 flex-col overflow-hidden pt-4 pb-6">
          <div className="mb-2 flex shrink-0 justify-end">
            <button
              type="button"
              onClick={() => setShowHistory((v) => !v)}
              className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-100 bg-white px-2.5 py-1 text-[12px] text-navy-600 hover:bg-navy-50"
            >
              <Clock size={12} /> History
            </button>
          </div>

          {empty ? (
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto animate-fade-in">
              <div className="w-full pb-6">
                <WorkspacePeek workspaceId={workspaceId} />
              </div>
            </div>
          ) : (
            <div className="min-h-0 flex-1 overflow-y-auto pb-6 pr-1">
              <WorkspacePeek workspaceId={workspaceId} />
              <MessageList
                turns={turns}
                workspaceId={workspaceId}
                conversationId={conversationIdRef.current}
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
