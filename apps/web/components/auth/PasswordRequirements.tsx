"use client";

import { CheckCircle2, Circle } from "lucide-react";

export function PasswordRequirements({
  flags,
  labels,
}: {
  flags: readonly boolean[];
  labels: readonly string[];
}) {
  return (
    <div className="rounded-2xl border border-navy-100 bg-canvas/90 p-4">
      <p className="text-sm font-semibold text-navy-900">Password Requirements:</p>
      <div className="mt-3 space-y-2">
        {labels.map((label, index) => (
          <div key={label} className="flex items-center gap-2 text-sm text-subtle">
            {flags[index] ? (
              <CheckCircle2 size={15} className="text-emerald-600" />
            ) : (
              <Circle size={15} className="text-subtle" />
            )}
            <span>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
