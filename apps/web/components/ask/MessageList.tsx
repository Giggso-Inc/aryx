"use client";

import { useEffect, useRef, useState } from "react";
import { Braces, Sparkles, User, Wand2, Share2 } from "lucide-react";
import { motion } from "framer-motion";
import { cn } from "@/lib/cn";
import { Citations } from "./Citation";
import { Markdown } from "./Markdown";
import { ShareConfigDialog } from "./ShareConfigDialog";
import type { ChatTurn } from "@/lib/types";

interface Props {
  turns: ChatTurn[];
  // Optional: only the live Aryx Ask page (numeric workspace id) can safely
  // fire the Share button. Read-only surfaces (e.g. the Shay bridge history
  // view) omit these — JSON/Beautify still render, Share stays hidden.
  workspaceId?: number;
  conversationId?: string;
}

type SharePanel = "json" | "beautify" | null;

/** JSON / Beautify / Share buttons — driven entirely by flags the backend
 * already computed from session state; clicking JSON or Beautify just reveals
 * data already in the response. Share opens a dialog where the destination
 * endpoint + auth are supplied per share (no button here ever triggers
 * another LLM call). */
function CpqActions({ turn, workspaceId, conversationId }: {
  turn: ChatTurn; workspaceId?: number; conversationId?: string;
}) {
  const [panel, setPanel] = useState<SharePanel>(null);
  const [shareOpen, setShareOpen] = useState(false);

  const canShare = Boolean(turn.apiShareButtonFlag && workspaceId !== undefined && conversationId);
  if (!turn.jsonButtonFlag && !turn.beautifyButtonFlag && !canShare) {
    return null;
  }

  return (
    <div className="mt-2">
      <div className="flex flex-wrap gap-2">
        {turn.jsonButtonFlag && (
          <button
            type="button"
            onClick={() => setPanel((p) => (p === "json" ? null : "json"))}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-100 bg-white px-2.5 py-1 text-[12px] text-navy-600 hover:bg-navy-50"
          >
            <Braces size={12} /> JSON
          </button>
        )}
        {turn.beautifyButtonFlag && (
          <button
            type="button"
            onClick={() => setPanel((p) => (p === "beautify" ? null : "beautify"))}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-100 bg-white px-2.5 py-1 text-[12px] text-navy-600 hover:bg-navy-50"
          >
            <Wand2 size={12} /> Beautify
          </button>
        )}
        {canShare && (
          <button
            type="button"
            onClick={() => setShareOpen(true)}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-navy-100 bg-white px-2.5 py-1 text-[12px] text-navy-600 hover:bg-navy-50"
          >
            <Share2 size={12} /> Share
          </button>
        )}
      </div>
      {panel === "json" && (
        <pre className="mt-2 max-w-prose overflow-x-auto rounded-xl border border-navy-100 bg-navy-50 p-3 text-[12px]">
          {JSON.stringify(turn.jsonResponse ?? {}, null, 2)}
        </pre>
      )}
      {panel === "beautify" && (
        <pre className="mt-2 max-w-prose overflow-x-auto rounded-xl border border-navy-100 bg-navy-50 p-3 text-[12px]">
          {turn.beautify}
        </pre>
      )}
      {canShare && (
        <ShareConfigDialog
          open={shareOpen}
          workspaceId={workspaceId!}
          conversationId={conversationId!}
          configJson={turn.jsonResponse ?? {}}
          onClose={() => setShareOpen(false)}
        />
      )}
    </div>
  );
}

/** Conversation transcript — alternating user / assistant turns. */
export function MessageList({ turns, workspaceId, conversationId }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, turns[turns.length - 1]?.content]);

  const usageLabel = (turn: ChatTurn) => {
    if (!turn.usage) return null;
    const parts = [
      turn.usage.answer_model,
      `${(turn.usage.latency_ms / 1000).toFixed(1)}s`,
      `${turn.usage.prompt_tokens + turn.usage.completion_tokens} tokens`,
    ].filter(Boolean);
    return parts.join(" · ");
  };

  return (
    <div className="flex flex-col gap-7">
      {turns.map((t) => (
        <motion.div
          key={t.id}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
          className={cn(
            "flex gap-4",
            t.role === "user" ? "flex-row-reverse" : "flex-row",
          )}
        >
          <div
            className={cn(
              "flex size-8 shrink-0 items-center justify-center rounded-full",
              t.role === "user"
                ? "bg-navy-800 text-white"
                : "bg-navy-50 text-steel-500",
            )}
          >
            {t.role === "user" ? <User size={15} /> : <Sparkles size={15} />}
          </div>
          <div
            className={cn(
              "max-w-prose",
              t.role === "user" ? "text-right" : "text-left",
            )}
          >
            <div
              className={cn(
                "inline-block rounded-2xl px-4 py-3 text-[15px] leading-relaxed",
                t.role === "user"
                  ? "bg-navy-800 text-white"
                  : "bg-white text-ink shadow-soft border border-navy-100",
                t.streaming && "caret",
              )}
            >
              {t.content ? (
                t.role === "assistant"
                  ? <Markdown>{t.content}</Markdown>
                  : t.content
              ) : (
                <span className="text-subtle italic">Thinking…</span>
              )}
            </div>
            {t.role === "assistant" && (
              <>
                {t.citations && <Citations citations={t.citations} />}
                <CpqActions turn={t} workspaceId={workspaceId} conversationId={conversationId} />
                {usageLabel(t) && (
                  <div className="mt-2 text-[11px] text-subtle">
                    {usageLabel(t)}
                  </div>
                )}
              </>
            )}
          </div>
        </motion.div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
