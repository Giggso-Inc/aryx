"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { MailPlus, Trash2 } from "lucide-react";

type InviteRow = {
  id: string;
  email: string;
  role: string;
};

function createInviteRow(): InviteRow {
  return {
    id: globalThis.crypto?.randomUUID?.() ?? `invite-${Date.now()}-${Math.random()}`,
    email: "",
    role: "user",
  };
}

export function InviteUserModal({
  open,
  onClose,
  onSendInvites,
  errorMessage,
}: {
  open: boolean;
  onClose: () => void;
  onSendInvites: (invites: Array<{ email: string; role: string }>) => void;
  errorMessage: string | null;
}) {
  const [invites, setInvites] = useState<InviteRow[]>([createInviteRow()]);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (open) {
      setInvites([createInviteRow()]);
    }
  }, [open]);

  useEffect(() => {
    if (!open || typeof document === "undefined") {
      return undefined;
    }

    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = originalOverflow;
    };
  }, [open]);

  if (!open || !mounted) return null;

  const updateInvite = (id: string, patch: Partial<Pick<InviteRow, "email" | "role">>) => {
    setInvites((current) =>
      current.map((invite) => (invite.id === id ? { ...invite, ...patch } : invite)),
    );
  };

  const addInvite = () => {
    setInvites((current) => [...current, createInviteRow()]);
  };

  const removeInvite = (id: string) => {
    setInvites((current) => (current.length > 1 ? current.filter((invite) => invite.id !== id) : current));
  };

  const canSend = invites.some((invite) => invite.email.trim());

  const handleSend = () => {
    const payload = invites
      .map((invite) => ({ email: invite.email.trim(), role: invite.role }))
      .filter((invite) => invite.email);
    if (payload.length === 0) return;
    onSendInvites(payload);
  };

  return createPortal(
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-navy-950/60 px-4 py-6 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="invite-users-title"
      aria-describedby="invite-users-description"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-[1.75rem] border border-navy-100 bg-white p-6 shadow-[0_24px_80px_rgba(10,21,48,0.24)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-blue-100 text-blue-700">
              <MailPlus size={18} />
            </div>
            <div>
              <h3 id="invite-users-title" className="text-2xl font-semibold text-navy-900">
                Invite Users
              </h3>
              <p id="invite-users-description" className="mt-1 text-sm text-subtle">
                Send invitation emails to multiple users at once.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="focus-ring inline-flex size-9 items-center justify-center rounded-xl border border-navy-100 bg-white text-navy-700 hover:bg-navy-50"
            aria-label="Close invite dialog"
          >
            ×
          </button>
        </div>

        {errorMessage ? (
          <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {errorMessage}
          </div>
        ) : null}

        <div className="mt-5">
          <div className="mt-4 space-y-3">
            {invites.map((invite, index) => (
              <div
                key={invite.id}
                className="rounded-[1.5rem] border border-navy-100 bg-canvas/70 p-4"
              >
                <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
                  <label className="flex-1">
                    <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.18em] text-subtle">
                      Email Address
                    </span>
                    <input
                      value={invite.email}
                      onChange={(event) => updateInvite(invite.id, { email: event.target.value })}
                      placeholder="user@example.com"
                      className="focus-ring w-full rounded-2xl border border-navy-100 bg-white px-4 py-3 text-sm text-navy-900 placeholder:text-subtle"
                    />
                  </label>
                  <label className="w-full lg:w-48">
                    <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.18em] text-subtle">
                      Role
                    </span>
                    <select
                      value={invite.role}
                      onChange={(event) => updateInvite(invite.id, { role: event.target.value })}
                      className="focus-ring w-full rounded-2xl border border-navy-100 bg-white px-4 py-3 text-sm text-navy-900"
                    >
                      <option value="user">User</option>
                      <option value="admin">Admin</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    onClick={() => removeInvite(invite.id)}
                    disabled={invites.length === 1}
                    className="focus-ring inline-flex h-[52px] w-[52px] items-center justify-center rounded-2xl border border-rose-200 bg-white text-rose-600 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40"
                    aria-label="Remove invite row"
                    title="Remove invite row"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-4 flex justify-end">
            <button
              type="button"
              onClick={addInvite}
              className="focus-ring inline-flex items-center rounded-xl border border-navy-100 bg-white px-4 py-2 text-sm font-medium text-blue-700 shadow-soft hover:bg-navy-50"
            >
              Add More
            </button>
          </div>
        </div>

        <div className="mt-5 flex items-center justify-end gap-3 border-t border-navy-100 pt-4">
          <button
            type="button"
            onClick={handleSend}
            disabled={!canSend}
            className="focus-ring inline-flex items-center justify-center rounded-2xl bg-navy-800 px-5 py-3 text-sm font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
          >
            Send Invitations
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
