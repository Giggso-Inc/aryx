import { useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";
import type { IngestQuestion } from "@/lib/types";

export function QuestionCard({
  question, onAnswer,
}: { question: IngestQuestion; onAnswer: (v: string) => Promise<void> }) {
  const [value, setValue] = useState(question.suggested || "");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!value.trim()) return;
    setBusy(true);
    try { await onAnswer(value.trim()); } finally { setBusy(false); }
  };
  return (
    <li className="rounded-xl border border-navy-100 bg-white p-4 shadow-soft">
      <div className="flex items-start gap-2">
        <span className="rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-amber-700">
          {question.kind.replace(/_/g, " ")}
        </span>
      </div>
      <p className="mt-2 text-[13px] leading-relaxed text-navy-800">
        {question.prompt}
      </p>
      {question.options && question.options.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {question.options.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => setValue(opt)}
              className={cn(
                "focus-ring rounded-full border px-3 py-1 text-[11px] font-medium transition-colors",
                value === opt
                  ? "border-steel-500 bg-navy-800 text-white"
                  : "border-navy-100 bg-white text-navy-700 hover:bg-navy-50",
              )}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
      <div className="mt-3 flex items-center gap-2">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="Your answer…"
          className="focus-ring flex-1 rounded-lg border border-navy-100 bg-white px-3 py-1.5 text-[13px] text-navy-800 focus:border-steel-500"
        />
        <button
          onClick={submit}
          disabled={!value.trim() || busy}
          className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
          Answer
        </button>
      </div>
      {question.suggested && (
        <p className="mt-1.5 text-[10px] text-subtle">
          AI suggestion: <span className="font-medium">{question.suggested}</span>
        </p>
      )}
    </li>
  );
}
