import Link from "next/link";
import { ArrowRight } from "lucide-react";

export function Metric({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-subtle">{label}</p>
      <p className="mt-3 text-2xl font-semibold text-navy-900">{value}</p>
      <p className="mt-2 text-sm text-subtle">{note}</p>
    </div>
  );
}

export function ActionCard({
  title,
  description,
  href,
}: {
  title: string;
  description: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="group rounded-[1.5rem] border border-navy-100 bg-canvas p-4 transition-colors hover:border-steel-300"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-navy-900">{title}</h3>
          <p className="mt-2 text-sm text-subtle">{description}</p>
        </div>
        <ArrowRight size={16} className="text-subtle transition-transform group-hover:translate-x-1" />
      </div>
    </Link>
  );
}
