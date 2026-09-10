import { X } from "lucide-react";
import type { ShayWorkspace } from "@/lib/shay-types";

export function DeleteWorkspaceModal({
  workspace,
  deleteError,
  deleting,
  onClose,
  onConfirm,
}: {
  workspace: ShayWorkspace | null;
  deleteError: string | null;
  deleting: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  if (!workspace) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-navy-900/35 px-4">
      <div className="w-full max-w-md rounded-[2rem] border border-navy-100 bg-white p-6 shadow-soft">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-2xl font-semibold text-navy-900">
              Delete workspace
            </h2>
            <p className="mt-2 text-sm text-subtle">
              Delete <span className="font-semibold text-navy-900">{workspace.name}</span> from the workspace list.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="focus-ring rounded-full border border-navy-100 p-2 text-navy-500 hover:bg-navy-50"
            aria-label="Close delete workspace dialog"
          >
            <X size={16} />
          </button>
        </div>

        <p className="mt-5 text-sm text-subtle">
          This action removes the workspace and cannot be undone from this screen.
        </p>

        {deleteError ? (
          <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {deleteError}
          </div>
        ) : null}

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="focus-ring rounded-2xl border border-navy-100 px-4 py-2.5 text-sm font-medium text-navy-700 hover:bg-navy-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={deleting}
            className="focus-ring rounded-2xl bg-rose-600 px-5 py-2.5 text-sm font-semibold text-white shadow-soft hover:bg-rose-700 disabled:opacity-50"
          >
            {deleting ? "Deleting..." : "Delete Workspace"}
          </button>
        </div>
      </div>
    </div>
  );
}
