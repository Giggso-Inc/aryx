"use client";

import { Search, X } from "lucide-react";
import { cn } from "@/lib/cn";

interface AskSearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  ariaLabel: string;
  resultLabel?: string;
  disabled?: boolean;
  className?: string;
}

/** Shared search control for the Ask transcript and thread history. */
export function AskSearchInput({
  value,
  onChange,
  placeholder,
  ariaLabel,
  resultLabel,
  disabled = false,
  className,
}: AskSearchInputProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-xl border border-navy-100 bg-white px-3 text-navy-700",
        "focus-within:border-steel-300 focus-within:ring-2 focus-within:ring-steel-100",
        disabled && "bg-navy-50 text-subtle",
        className,
      )}
    >
      <Search size={14} className="shrink-0 text-steel-500" aria-hidden="true" />
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        autoComplete="off"
        spellCheck={false}
        disabled={disabled}
        className="min-w-0 flex-1 bg-transparent text-[12px] text-navy-800 outline-none placeholder:text-subtle disabled:cursor-not-allowed"
      />
      {resultLabel && (
        <span className="shrink-0 text-[10px] text-subtle" aria-live="polite">
          {resultLabel}
        </span>
      )}
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label={`Clear ${ariaLabel.toLowerCase()}`}
          className="focus-ring shrink-0 rounded-md p-1 text-subtle hover:bg-navy-50 hover:text-navy-700"
        >
          <X size={12} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
