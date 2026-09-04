export function DeleteConfirmModal({
  title,
  message,
  onCancel,
  onConfirm,
}: {
  title: string;
  message: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/45 px-4 py-8"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-confirm-title"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-lg rounded-[1.5rem] border border-navy-100 bg-white p-6 shadow-soft"
        onClick={(event) => event.stopPropagation()}
      >
        <p
          id="delete-confirm-title"
          className="text-lg font-semibold text-navy-900"
        >
          {title}
        </p>
        <p className="mt-3 text-sm leading-6 text-subtle">
          {message}
        </p>
        <p className="mt-2 text-sm text-rose-600">
          This action cannot be undone.
        </p>
        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="focus-ring rounded-full border border-navy-100 bg-white px-4 py-2 text-sm font-semibold text-navy-700 transition-colors hover:bg-navy-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="focus-ring rounded-full bg-rose-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-rose-700"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}
