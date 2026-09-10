import { Plus, X } from "lucide-react";

export function SourcePriorityEditor({
  sources,
  usedByDefault,
  newSource,
  onNewSourceChange,
  onAdd,
  onRemove,
}: {
  sources: string[];
  usedByDefault: boolean;
  newSource: string;
  onNewSourceChange: (value: string) => void;
  onAdd: () => void;
  onRemove: (source: string) => void;
}) {
  return (
    <div className="rounded-lg border border-navy-100 bg-white px-3 py-2.5">
      <label className="block text-[10px] uppercase tracking-wider text-subtle">
        Source priority {!usedByDefault && (
          <span className="text-subtle/60"> · used only by source_priority</span>
        )}
      </label>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {sources.length === 0 && (
          <span className="text-[11px] italic text-subtle">empty</span>
        )}
        {sources.map((s, i) => (
          <span
            key={s}
            className="group inline-flex items-center gap-1 rounded-full border border-navy-100 bg-navy-50/60 pl-2 pr-1 py-0.5 font-mono text-[11px] text-navy-700"
          >
            {i + 1}. {s}
            <button
              type="button"
              onClick={() => onRemove(s)}
              className="focus-ring rounded-full p-0.5 text-subtle hover:bg-white hover:text-rose-500"
            >
              <X size={9} />
            </button>
          </span>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-1.5">
        <input
          value={newSource}
          onChange={(e) => onNewSourceChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onAdd()}
          placeholder="add source… (e.g. crm)"
          className="focus-ring flex-1 rounded-md border border-navy-100 bg-white px-2 py-1 font-mono text-[11px] text-navy-800 focus:border-steel-500"
        />
        <button
          type="button"
          onClick={onAdd}
          disabled={!newSource.trim()}
          className="focus-ring inline-flex size-6 items-center justify-center rounded-md bg-navy-100 text-navy-700 hover:bg-navy-200 disabled:opacity-50"
          aria-label="Add source"
        >
          <Plus size={11} />
        </button>
      </div>
    </div>
  );
}
