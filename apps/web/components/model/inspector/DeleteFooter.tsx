import { Trash2 } from "lucide-react";

export function DeleteFooter({
  typeName,
  confirming,
  busy,
  onConfirm,
  onDelete,
  onCancel,
}: {
  typeName: string;
  confirming: boolean;
  busy: boolean;
  onConfirm: () => void;
  onDelete: () => void;
  onCancel: () => void;
}) {
  return (
    <footer className="border-t border-navy-100 bg-navy-50/40 px-5 py-3">
      {confirming ? (
        <div className="space-y-2">
          <p className="text-[11px] text-rose-700">
            About to delete the type. Records of this type stay in the
            graph but are no longer schema-registered.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onDelete}
              disabled={busy}
              className="focus-ring inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-rose-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-rose-500 disabled:opacity-60"
            >
              <Trash2 size={12} /> Delete {typeName}
            </button>
            <button
              type="button"
              onClick={onCancel}
              className="focus-ring rounded-lg border border-navy-100 bg-white px-3 py-1.5 text-[12px] font-medium text-navy-700 hover:bg-navy-50"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={onConfirm}
          className="focus-ring inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-[12px] font-medium text-rose-600 hover:bg-rose-50"
        >
          <Trash2 size={12} /> Delete this type
        </button>
      )}
    </footer>
  );
}
