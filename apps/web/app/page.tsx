"use client";

import { useEffect, useState } from "react";
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

// Starters tuned for the demo workspace (Customer · Site · Device · Agent · Ticket).
// Each names a specific kind of record or a known field so term extraction
// always has a noun to lock onto.
const STARTERS = [
  "Show me 5 Customers",
  "Which Agents have resolved the most Tickets?",
  "What firmware versions appear most often on Devices?",
  "Tell me about the Customer NetOps Atlantic",
];

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
    <div className="fixed inset-y-0 right-0 z-30 flex w-96 flex-col border-l border-navy-100 bg-white shadow-soft animate-rise">
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
          <ul className="space-y-2">
            {history.map((h) => (
              <li key={h.id}
                className="cursor-pointer rounded-xl border border-navy-100 p-3 hover:bg-navy-50"
                onClick={() => { onReplay(h.question); onClose(); }}>
                <p className="text-[12px] font-medium text-navy-800 line-clamp-2">{h.question}</p>
                <p className="mt-1 text-[11px] text-subtle line-clamp-2">{h.answer}</p>
                <p className="mt-1 text-[10px] text-subtle">{new Date(h.ts).toLocaleString()}</p>
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
      const resp = await api.ask(q, workspaceId);
      // Lightweight citation extraction — V1: derive from terms.
      const citations: Citation[] = (resp.terms || [])
        .slice(0, 5)
        .map((label, i) => ({ entity_id: i, label }));

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
                }
              : t,
          ),
        );
        setBusy(false);
      }, totalMs);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setTurns((prev) =>
        prev.map((t) =>
          t.id === assistantId
            ? {
                ...t,
                content: `Couldn't reach the API — ${message}`,
                streaming: false,
              }
            : t,
        ),
      );
      setBusy(false);
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
          onReplay={(q) => { setInput(q); }}
        />
      )}

      <div className="app-shell-offset flex flex-1">
        <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-4 py-10 lg:px-5">
          <div className="mb-2 flex justify-end">
            <button
              type="button"
              onClick={() => setShowHistory((v) => !v)}
              className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-100 bg-white px-2.5 py-1 text-[12px] text-navy-600 hover:bg-navy-50"
            >
              <Clock size={12} /> History
            </button>
          </div>
          {empty ? (
            <div className="flex flex-1 flex-col items-center justify-center text-center animate-fade-in">
              <h1 className="font-display text-[2.6rem] leading-tight text-navy-900">
                Ask your knowledge graph.
              </h1>
              <p className="mt-4 max-w-md text-[15px] text-subtle">
                Questions naming a specific kind of record or an entity work
                best. Try one of these to see how citations work.
              </p>
              <div className="mt-8 w-full">
                <WorkspacePeek workspaceId={workspaceId} />
              </div>
              <div className="mt-2 w-full max-w-prose">
                <FollowupChips
                  prompts={STARTERS}
                  onPick={(p) => send(p)}
                  className="justify-center"
                />
              </div>
            </div>
          ) : (
            <div className="flex-1">
              <WorkspacePeek workspaceId={workspaceId} />
              <MessageList turns={turns} />
              {!busy && (
                <div className="mt-6 pl-12">
                  <FollowupChips prompts={FOLLOWUPS} onPick={(p) => send(p)} />
                </div>
              )}
            </div>
          )}

          <div className="sticky bottom-6 mt-8">
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
              Answers are grounded in the workspace's resolved entities.
              Provenance shown beneath each response.
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
