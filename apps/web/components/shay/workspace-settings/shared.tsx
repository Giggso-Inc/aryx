import { cn } from "@/lib/cn";

export function InlineNotice({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone: "success" | "error";
}) {
  return (
    <div
      className={cn(
        "mt-4 rounded-2xl px-4 py-3 text-sm",
        tone === "success"
          ? "border border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border border-rose-200 bg-rose-50 text-rose-700",
      )}
    >
      {children}
    </div>
  );
}

export function ProfileSummaryField({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-navy-500">
        {label}
      </p>
      <p className="mt-2 break-words text-base text-navy-900">{value}</p>
    </div>
  );
}
