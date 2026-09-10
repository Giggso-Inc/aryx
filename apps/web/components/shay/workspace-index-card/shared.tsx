import type { MouseEvent, ReactNode } from "react";

const numberFormatter = new Intl.NumberFormat("en-US");

export function ActionIcon({
  children,
  label,
  onClick,
  tone = "default",
}: {
  children: ReactNode;
  label: string;
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
  tone?: "default" | "danger";
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className={`focus-ring rounded-full border p-2 transition-colors ${
        tone === "danger"
          ? "border-rose-100 text-rose-600 hover:bg-rose-50"
          : "border-navy-100 text-navy-500 hover:bg-navy-50"
      }`}
    >
      {children}
    </button>
  );
}

export function MetricTile({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: number | null | undefined;
}) {
  return (
    <div className="rounded-[1.35rem] border border-navy-100 bg-[linear-gradient(90deg,_rgba(64,104,168,0.06),_rgba(255,255,255,0.96))] px-4 py-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-steel-700">
          {label}
        </span>
        <span className="text-steel-600">{icon}</span>
      </div>
      <div className="mt-4 text-3xl font-semibold leading-none text-navy-900">
        {formatMetric(value)}
      </div>
    </div>
  );
}

function formatMetric(value: number | null | undefined) {
  if (typeof value !== "number") {
    return "--";
  }
  return numberFormatter.format(value);
}
