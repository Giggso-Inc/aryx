import Link from "next/link";
import { MessageSquareText, Upload, Zap } from "lucide-react";

export function Hero({
  workspaceBadge,
  askHref,
  ingestHref,
}: {
  workspaceBadge: string;
  askHref: string;
  ingestHref: string;
}) {
  return (
    <div className="mb-10 rounded-2xl bg-navy-900 px-8 py-10 text-white">
      <div className="mb-3 flex items-center gap-2">
        <Zap size={18} className="text-steel-300" />
        <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-steel-300">
          {workspaceBadge}
        </span>
      </div>
      <h1 className="font-display text-[2.2rem] font-bold leading-tight">
        A Fortress of Structured Knowledge
      </h1>
      <p className="mt-3 max-w-xl text-[15px] text-navy-200">
        Turn messy enterprise data into a single knowledge graph you can query
        in plain English and explore visually.
      </p>
      <div className="mt-6 flex gap-3">
        <Link
          href={askHref}
          className="inline-flex items-center gap-1.5 rounded-lg bg-white px-4 py-2 text-[13px] font-semibold text-navy-900 hover:bg-navy-50"
        >
          <MessageSquareText size={14} /> Ask a question
        </Link>
        <Link
          href={ingestHref}
          className="inline-flex items-center gap-1.5 rounded-lg border border-navy-600 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-800"
        >
          <Upload size={14} /> Ingest data
        </Link>
      </div>
    </div>
  );
}
