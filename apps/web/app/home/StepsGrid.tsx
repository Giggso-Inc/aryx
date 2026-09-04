import Link from "next/link";
import { ArrowRight, MessageSquareText, Share2, Upload } from "lucide-react";

const STEPS = [
  {
    num: 1,
    title: "Ingest",
    icon: <Upload size={18} />,
    body: "Drop files or connect a database. Aryx reads the rows, resolves duplicates, and writes entities into the knowledge graph.",
  },
  {
    num: 2,
    title: "Ask",
    icon: <MessageSquareText size={18} />,
    body: "Type a company, ticket, or keyword. Aryx traverses the graph and shows every connected entity, relationships, and provenance.",
  },
  {
    num: 3,
    title: "Graph",
    icon: <Share2 size={18} />,
    body: "See the whole picture as an interactive canvas. Filter by type, follow relationships, and click any node to explore neighbours.",
  },
];

export function StepsGrid({
  ingestHref,
  askHref,
  graphHref,
}: {
  ingestHref: string;
  askHref: string;
  graphHref: string;
}) {
  return (
    <>
      <div className="mb-4">
        <h2 className="font-display text-[1.3rem] font-bold text-navy-900">
          How to use Aryx
        </h2>
        <p className="mt-1 text-[13px] text-subtle">
          Use the nav above to move through Ingest → Ask → Graph in order.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {STEPS.map((s) => (
          <Link
            key={s.num}
            href={s.title === "Ingest" ? ingestHref : s.title === "Ask" ? askHref : graphHref}
            className="group rounded-xl border border-navy-100 bg-white p-5 shadow-soft transition-shadow hover:shadow-md"
          >
            <div className="mb-3 flex items-center gap-2">
              <span className="flex size-7 items-center justify-center rounded-full bg-navy-100 text-[12px] font-bold text-navy-700">
                {s.num}
              </span>
              <span className="text-[13px] font-semibold text-navy-800">
                {s.icon && (
                  <span className="mr-1 inline-block align-text-bottom text-navy-600">
                    {s.icon}
                  </span>
                )}
                {s.title}
              </span>
            </div>
            <p className="text-[12px] text-subtle">{s.body}</p>
            <div className="mt-3 flex items-center gap-1 text-[11px] font-medium text-steel-600 opacity-0 transition-opacity group-hover:opacity-100">
              Go <ArrowRight size={11} />
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
