import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function LoadingState() {
  return (
    <div className="rounded-[1.75rem] border border-navy-100 bg-white px-5 py-12 text-center text-sm text-subtle shadow-soft">
      Loading company users...
    </div>
  );
}

export function MetricCard({
  tone,
  title,
  value,
  helper,
  icon,
  onClick,
}: {
  tone: "blue" | "green" | "red" | "slate";
  title: string;
  value: number;
  helper: string;
  icon: ReactNode;
  onClick?: () => void;
}) {
  const toneClasses = {
    blue: "text-blue-700 bg-blue-100",
    green: "text-emerald-700 bg-emerald-100",
    red: "text-rose-700 bg-rose-100",
    slate: "text-slate-700 bg-slate-100",
  }[tone];

  const titleClass = {
    blue: "text-blue-700",
    green: "text-emerald-700",
    red: "text-rose-700",
    slate: "text-slate-700",
  }[tone];

  const classes = cn(
    "rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-[0_2px_6px_rgba(10,21,48,0.04)] transition-colors",
    onClick ? "focus-ring cursor-pointer hover:border-steel-300 hover:bg-canvas/70" : "",
  );

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={classes}>
        <div className="flex items-start justify-between gap-4">
          <div className="text-left">
            <p className={cn("text-sm font-medium", titleClass)}>{title}</p>
            <p className="mt-2 text-4xl font-semibold tracking-tight text-navy-900">{value}</p>
            <p className="mt-2 text-sm text-subtle">{helper}</p>
          </div>
          <div className={cn("flex size-11 items-center justify-center rounded-2xl", toneClasses)}>
            {icon}
          </div>
        </div>
      </button>
    );
  }

  return (
    <div className={classes}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className={cn("text-sm font-medium", titleClass)}>{title}</p>
          <p className="mt-2 text-4xl font-semibold tracking-tight text-navy-900">{value}</p>
          <p className="mt-2 text-sm text-subtle">{helper}</p>
        </div>
        <div className={cn("flex size-11 items-center justify-center rounded-2xl", toneClasses)}>
          {icon}
        </div>
      </div>
    </div>
  );
}
