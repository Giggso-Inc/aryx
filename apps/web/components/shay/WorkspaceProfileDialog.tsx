"use client";

import { Loader2, Save, X } from "lucide-react";

interface WorkspaceProfileDialogProps {
  description: string;
  name: string;
  onClose: () => void;
  onDescriptionChange: (value: string) => void;
  onNameChange: (value: string) => void;
  onSave: () => void;
  saving: boolean;
  title?: string;
  descriptionText?: string;
  error?: string | null;
}

export function WorkspaceProfileDialog({
  description,
  name,
  onClose,
  onDescriptionChange,
  onNameChange,
  onSave,
  saving,
  title = "Edit workspace profile",
  descriptionText = "Update the workspace name and description from this dialog.",
  error = null,
}: WorkspaceProfileDialogProps) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-navy-900/35 px-4 backdrop-blur-sm">
      <div className="w-full max-w-xl rounded-[2rem] border border-navy-100 bg-white p-6 shadow-soft">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-2xl font-semibold text-navy-900">{title}</h2>
            <p className="mt-2 text-sm text-subtle">{descriptionText}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="focus-ring rounded-full border border-navy-100 p-2 text-navy-500 hover:bg-navy-50"
            aria-label="Close workspace profile dialog"
          >
            <X size={16} />
          </button>
        </div>

        <div className="mt-6 space-y-4">
          <input
            value={name}
            onChange={(event) => onNameChange(event.target.value)}
            placeholder="Workspace name"
            className="focus-ring w-full rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
          />
          <textarea
            value={description}
            onChange={(event) => onDescriptionChange(event.target.value)}
            rows={4}
            placeholder="Workspace description"
            className="focus-ring w-full resize-none rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
          />
          {error ? (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error}
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
            onClick={onSave}
            disabled={saving}
            className="focus-ring inline-flex items-center gap-2 rounded-2xl bg-navy-800 px-5 py-2.5 text-sm font-semibold text-white shadow-soft hover:bg-navy-700 disabled:opacity-50"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
            Save workspace
          </button>
        </div>
      </div>
    </div>
  );
}
