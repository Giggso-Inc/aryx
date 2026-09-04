import { FolderUp, Scale, Weight } from "lucide-react";
import { cn } from "@/lib/cn";
import { TABS, type Tab } from "./tab-config";

export function TabBar({
  tab,
  isDiagram,
  onTabChange,
}: {
  tab: Tab;
  isDiagram: boolean;
  onTabChange: (tab: Tab) => void;
}) {
  return (
    <>
      <div className="border-b border-navy-100 bg-white">
        <div className="workspace-section-shell flex max-w-none flex-wrap items-end gap-0">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => onTabChange(t.id)}
              className={cn(
                "inline-flex items-center gap-2 border-b-2 px-4 py-3 text-[13px] font-medium leading-none transition-colors",
                tab === t.id
                  ? t.activeClass
                  : "border-transparent text-navy-500 hover:text-navy-800",
              )}
            >
              <span className={cn("flex size-4 shrink-0 items-center justify-center", t.iconClass)}>{t.icon}</span>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {!isDiagram && (
        <div className="border-b border-navy-50 bg-navy-50/40 px-5 py-2 text-[11px] text-navy-500">
          Brief → Ingest →
          <span className="inline-flex items-center gap-1.5 align-middle font-semibold text-steel-600">
            <Weight size={11} /> Lightweight
          </span> →
          HITL review →
          <span className="inline-flex items-center gap-1.5 align-middle font-semibold text-purple-600">
            <Scale size={11} /> Heavyweight (Rules + Versions)
          </span> →
          <span className="inline-flex items-center gap-1.5 align-middle font-semibold text-emerald-600">
            <FolderUp size={11} /> Publish
          </span>
        </div>
      )}
    </>
  );
}
