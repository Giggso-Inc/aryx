"use client";

import { useState } from "react";
import { CheckCircle2, Copy } from "lucide-react";

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-navy-100 bg-white shadow-soft">
      <div className="border-b border-navy-100 px-5 py-3.5">
        <h2 className="text-[13px] font-bold text-navy-900">{title}</h2>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

export function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button
      type="button"
      onClick={copy}
      className="focus-ring inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium text-steel-600 hover:bg-steel-50"
    >
      {copied ? <CheckCircle2 size={11} /> : <Copy size={11} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}
