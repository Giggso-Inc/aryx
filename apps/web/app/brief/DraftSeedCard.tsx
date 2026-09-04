import { Loader2, Sparkles } from "lucide-react";

export function DraftSeedCard({
  seed,
  drafting,
  onSeedChange,
  onDraft,
}: {
  seed: string;
  drafting: boolean;
  onSeedChange: (value: string) => void;
  onDraft: () => void;
}) {
  return (
    <div className="mb-6 rounded-xl border border-navy-100 bg-white p-5 shadow-soft">
      <h2 className="mb-1 text-[13px] font-bold text-navy-900">
        ✨ Start fast — describe it once
      </h2>
      <p className="mb-3 text-[12px] text-subtle">
        Type one sentence and Aryx drafts all five fields. Edit the draft before saving.
      </p>
      <div className="flex gap-2">
        <input
          value={seed}
          onChange={(e) => onSeedChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onDraft()}
          placeholder="e.g. Match support tickets to the right expert agent"
          className="focus-ring flex-1 rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
        />
        <button
          type="button"
          onClick={onDraft}
          disabled={!seed.trim() || drafting}
          className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-4 py-2 text-[13px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {drafting ? (
            <><Loader2 size={13} className="animate-spin" /> Drafting…</>
          ) : (
            <><Sparkles size={13} /> Draft</>
          )}
        </button>
      </div>
    </div>
  );
}
