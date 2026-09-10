import { FolderPlus, X } from "lucide-react";

export function CreateWorkspaceModal({
  open,
  name,
  description,
  modalError,
  saving,
  onNameChange,
  onDescriptionChange,
  onClose,
  onCreate,
}: {
  open: boolean;
  name: string;
  description: string;
  modalError: string | null;
  saving: boolean;
  onNameChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onClose: () => void;
  onCreate: () => void;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-navy-900/35 px-4">
      <div className="w-full max-w-lg rounded-[2rem] border border-navy-100 bg-white p-6 shadow-soft">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-2xl font-semibold text-navy-900">
              Create a workspace
            </h2>
            <p className="mt-2 text-sm text-subtle">
              Spin up a new Aryx workspace and bridge it into the shared runtime.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="focus-ring rounded-full border border-navy-100 p-2 text-navy-500 hover:bg-navy-50"
            aria-label="Close create workspace dialog"
          >
            <X size={16} />
          </button>
        </div>

        <div className="mt-6 space-y-4">
          <input
            value={name}
            onChange={(event) => onNameChange(event.target.value)}
            placeholder="Workspace name"
            className="focus-ring w-full rounded-2xl border border-navy-100 bg-white px-4 py-3 text-sm text-navy-900"
          />
          <textarea
            value={description}
            onChange={(event) => onDescriptionChange(event.target.value)}
            rows={5}
            placeholder="What will this workspace own across auth, Aryx ingest, and Ask?"
            className="focus-ring w-full resize-none rounded-2xl border border-navy-100 bg-white px-4 py-3 text-sm text-navy-900"
          />
          {modalError ? (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {modalError}
            </div>
          ) : null}
        </div>

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
            onClick={onCreate}
            disabled={!name.trim() || saving}
            className="focus-ring inline-flex items-center gap-2 rounded-2xl bg-navy-800 px-5 py-2.5 text-sm font-semibold text-white shadow-soft hover:bg-navy-700 disabled:opacity-50"
          >
            <FolderPlus size={16} />
            {saving ? "Creating..." : "Create Workspace"}
          </button>
        </div>
      </div>
    </div>
  );
}
