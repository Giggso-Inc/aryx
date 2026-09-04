import type { IngestQuestion } from "@/lib/types";

export function QuestionCard({
  q, onAnswer,
}: { q: IngestQuestion; onAnswer: (v: string) => void }) {
  const opts = q.options && q.options.length > 0
    ? q.options : ["Same", "Different", "Skip for now"];
  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50/60 p-4 shadow-soft">
      <div className="inline-block rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-800">
        A question for you
      </div>
      <div className="mt-2 text-[14px] text-navy-900">{q.prompt}</div>
      <div className="mt-3 flex flex-wrap gap-2">
        {opts.map((o) => (
          <button
            key={o}
            onClick={() => onAnswer(o)}
            className="focus-ring rounded-full border border-amber-300 bg-white px-3.5 py-1.5 text-[12px] font-medium text-amber-900 hover:bg-amber-100"
          >
            {o}
          </button>
        ))}
      </div>
    </div>
  );
}
