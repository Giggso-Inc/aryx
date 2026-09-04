import { usePathname } from "next/navigation";
import { parseWorkspaceScope, workspaceStartHref } from "@/lib/workspace-route";

export function EmptyState({ onCreate }: { onCreate: () => void }) {
  const pathname = usePathname();
  const { shayWorkspaceId } = parseWorkspaceScope(pathname);

  return (
    <div className="pointer-events-none absolute inset-0 z-[5] flex items-center justify-center">
      <div className="pointer-events-auto max-w-md rounded-2xl border border-dashed border-navy-200 bg-white/80 px-8 py-10 text-center shadow-soft backdrop-blur">
        <h2 className="font-display text-[1.6rem] text-navy-900">
          No data yet.
        </h2>
        <p className="mt-2 text-[13px] text-subtle">
          Start with the guided setup — Aryx will read your data and propose
          the map for you to approve.
        </p>
        <div className="mt-5 flex flex-col items-center gap-2">
          <a
            href={shayWorkspaceId ? workspaceStartHref(shayWorkspaceId) : "/start"}
            className="focus-ring inline-flex items-center gap-2 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700"
          >
            ✨ Start guided setup
          </a>
          <button
            onClick={onCreate}
            className="focus-ring text-[12px] text-subtle hover:text-navy-700"
          >
            I'll add records by hand
          </button>
        </div>
      </div>
    </div>
  );
}
