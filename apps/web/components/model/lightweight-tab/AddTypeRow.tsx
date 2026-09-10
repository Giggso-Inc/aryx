import { Loader2, Plus } from "lucide-react";

export function AddTypeRow({
  value, onChange, onAdd, busy,
}: { value: string; onChange: (v: string) => void; onAdd: () => void; busy: boolean }) {
  return (
    <div className="flex items-center gap-2 rounded-xl border border-dashed border-navy-200 p-3">
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onAdd()}
        placeholder="Add new type (e.g. Contract)"
        className="focus-ring flex-1 rounded-lg border border-navy-100 px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
      />
      <button
        type="button"
        onClick={onAdd}
        disabled={!value.trim() || busy}
        className="focus-ring inline-flex items-center gap-1 rounded-lg bg-navy-800 px-3 py-2 text-[12px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
      >
        {busy ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
        Add type
      </button>
    </div>
  );
}
