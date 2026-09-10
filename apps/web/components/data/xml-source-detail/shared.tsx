import { cn } from "@/lib/cn";

export function StatusPill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700">
      {children}
    </span>
  );
}

export function ActionButton({
  label,
  icon,
  disabled,
  onClick,
  tone = "default",
}: {
  label: string;
  icon: React.ReactNode;
  disabled: boolean;
  onClick: () => void;
  tone?: "default" | "danger";
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "focus-ring inline-flex items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        tone === "danger"
          ? "border-rose-300 bg-white text-rose-600 hover:bg-rose-50"
          : "border-navy-100 bg-white text-navy-800 hover:bg-navy-50",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

export function IconOnlyAction({
  label,
  icon,
  disabled,
  tone = "default",
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  disabled: boolean;
  tone?: "default" | "danger";
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "focus-ring inline-flex size-9 items-center justify-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-35",
        tone === "danger"
          ? "text-rose-500 hover:bg-rose-50 hover:text-rose-600"
          : "text-navy-500 hover:bg-navy-50 hover:text-navy-800",
      )}
    >
      {icon}
    </button>
  );
}
