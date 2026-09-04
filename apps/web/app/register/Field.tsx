import { Info } from "lucide-react";
import type { ReactNode } from "react";

interface FieldProps {
  label: string;
  required?: boolean;
  icon: ReactNode;
  note?: string;
  children: ReactNode;
}

export function Field({ label, required = false, icon, note, children }: FieldProps) {
  return (
    <label className="block space-y-2">
      <span className="text-sm font-semibold text-navy-900">
        {label} {required ? <span className="text-rose-500">*</span> : null}
      </span>
      <div className="relative">
        <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-4 text-subtle">
          {icon}
        </div>
        {children}
      </div>
      {note ? (
        <p className="flex items-start gap-1.5 text-xs text-blue-700">
          <Info size={14} className="mt-0.5 shrink-0" />
          <span>{note}</span>
        </p>
      ) : null}
    </label>
  );
}
