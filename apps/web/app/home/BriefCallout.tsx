import Link from "next/link";
import { ArrowRight, Database } from "lucide-react";

export function BriefCallout({ briefHref }: { briefHref: string }) {
  return (
    <div className="mt-8 flex items-start gap-4 rounded-xl border border-steel-200 bg-steel-50 p-5">
      <Database size={20} className="mt-0.5 shrink-0 text-steel-600" />
      <div>
        <h3 className="text-[13px] font-semibold text-navy-900">
          Ground your workspace with a Brief
        </h3>
        <p className="mt-1 text-[12px] text-subtle">
          A brief tells Aryx what domain, aim, and entity types matter most —
          improving extraction quality significantly.
        </p>
        <Link
          href={briefHref}
          className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-steel-600 hover:text-steel-800"
        >
          Edit brief <ArrowRight size={11} />
        </Link>
      </div>
    </div>
  );
}
