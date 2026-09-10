import { X } from "lucide-react";
import { cn } from "@/lib/cn";

export function FileList({
  files,
  maxPerFileBytes,
  onRemove,
}: {
  files: File[];
  maxPerFileBytes: number;
  onRemove: (index: number) => void;
}) {
  if (files.length === 0) return null;

  return (
    <ul className="mt-4 w-full max-w-2xl space-y-1.5">
      {files.map((f, i) => {
        const oversize = f.size > maxPerFileBytes;
        return (
          <li
            key={`${f.name}-${i}`}
            className={cn(
              "flex items-center justify-between rounded-lg border px-3 py-2 text-[12.5px]",
              oversize ? "border-rose-200 bg-rose-50/50" : "border-navy-100 bg-white",
            )}
          >
            <span className="truncate text-navy-800">{f.name}</span>
            <span className="ml-3 flex items-center gap-3 shrink-0">
              <span className={cn(
                "font-mono text-[11px]",
                oversize ? "text-rose-600" : "text-subtle",
              )}>
                {(f.size / 1024).toFixed(0)} KB
              </span>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onRemove(i); }}
                className="focus-ring rounded p-1 text-subtle hover:bg-navy-50 hover:text-rose-500"
                aria-label={`Remove ${f.name}`}
              >
                <X size={12} />
              </button>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
