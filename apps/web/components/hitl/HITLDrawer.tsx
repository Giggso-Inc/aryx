"use client";

import { useCallback, useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, MessageSquareWarning } from "lucide-react";
import { api } from "@/lib/api";
import type { IngestQuestion } from "@/lib/types";
import { QuestionCard } from "./hitl-drawer/QuestionCard";
import { Empty, Loading } from "./hitl-drawer/states";

interface Props {
  open: boolean;
  workspaceId: number;
  onClose: () => void;
  onAnswered?: () => void;
}

/** Side drawer listing pending HITL ingest questions. Answer here unblocks
 *  the pipeline. Cards expand inline; suggested answer pre-fills. */
export function HITLDrawer({ open, workspaceId, onClose, onAnswered }: Props) {
  const [items, setItems] = useState<IngestQuestion[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getIngestQuestions(workspaceId, "pending");
      setItems(data);
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => { if (open) load(); }, [open, load]);

  const answer = async (q: IngestQuestion, value: string) => {
    await api.answerIngestQuestion(q.id, value, "ui");
    onAnswered?.();
    load();
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-30 bg-navy-950/20 backdrop-blur-sm"
          />
          <motion.aside
            initial={{ x: 480, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 480, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="fixed right-0 top-0 z-40 flex h-screen w-[440px] flex-col border-l border-navy-100 bg-white shadow-soft"
          >
            <header className="flex items-center justify-between border-b border-navy-100 px-5 py-4">
              <div className="flex items-center gap-2">
                <MessageSquareWarning size={16} className="text-amber-500" />
                <h2 className="font-display text-[1.1rem] text-navy-900">
                  Questions for you
                </h2>
                {items.length > 0 && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
                    {items.length}
                  </span>
                )}
              </div>
              <button
                onClick={onClose}
                className="focus-ring rounded-lg p-1 text-subtle hover:bg-navy-50"
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </header>
            <p className="border-b border-navy-100 px-5 py-3 text-[12px] text-subtle">
              Aryx pauses ingest when it needs a human call. Answer here to
              unblock the pipeline.
            </p>
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {loading ? (
                <Loading />
              ) : items.length === 0 ? (
                <Empty />
              ) : (
                <ul className="space-y-3">
                  {items.map((q) => (
                    <QuestionCard
                      key={q.id}
                      question={q}
                      onAnswer={(v) => answer(q, v)}
                    />
                  ))}
                </ul>
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
