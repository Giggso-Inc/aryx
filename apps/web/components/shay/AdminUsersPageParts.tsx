"use client";

import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { MailPlus, Trash2, UserCheck, UserCog, UserX, Users2 } from "lucide-react";
import { cn } from "@/lib/cn";
import type { ShayInvitation, ShayUser } from "@/lib/shay-types";

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

export function LoadingState() {
  return (
    <div className="rounded-[1.75rem] border border-navy-100 bg-white px-5 py-12 text-center text-sm text-subtle shadow-soft">
      Loading company users...
    </div>
  );
}

export function MetricCard({
  tone,
  title,
  value,
  helper,
  icon,
}: {
  tone: "blue" | "green" | "red" | "slate";
  title: string;
  value: number;
  helper: string;
  icon: ReactNode;
}) {
  const toneClasses = {
    blue: "text-blue-700 bg-blue-100",
    green: "text-emerald-700 bg-emerald-100",
    red: "text-rose-700 bg-rose-100",
    slate: "text-slate-700 bg-slate-100",
  }[tone];

  const titleClass = {
    blue: "text-blue-700",
    green: "text-emerald-700",
    red: "text-rose-700",
    slate: "text-slate-700",
  }[tone];

  return (
    <div className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-[0_2px_6px_rgba(10,21,48,0.04)]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className={cn("text-sm font-medium", titleClass)}>{title}</p>
          <p className="mt-2 text-4xl font-semibold tracking-tight text-navy-900">{value}</p>
          <p className="mt-2 text-sm text-subtle">{helper}</p>
        </div>
        <div className={cn("flex size-11 items-center justify-center rounded-2xl", toneClasses)}>
          {icon}
        </div>
      </div>
    </div>
  );
}

export function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "focus-ring rounded-full px-4 py-2.5 text-sm font-semibold transition-colors",
        active
          ? "bg-navy-800 text-white shadow-sm"
          : "text-navy-700 hover:bg-white/70",
      )}
    >
      {children}
    </button>
  );
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

export function UsersTable({
  users,
  onRoleChange,
  onToggle,
  saving,
}: {
  users: ShayUser[];
  onRoleChange: (userId: string, role: string) => void;
  onToggle: (user: ShayUser) => void;
  saving: boolean;
}) {
  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-[1.5rem] border border-navy-100">
        <div className="grid grid-cols-[minmax(0,1.9fr)_minmax(0,1.4fr)_120px_120px_160px_96px] gap-4 border-b border-navy-100 bg-canvas px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle">
          <span>Name</span>
          <span>Email</span>
          <span>Role</span>
          <span>Status</span>
          <span>Last login</span>
          <span>Actions</span>
        </div>
        <div className="divide-y divide-navy-100 bg-white">
          {users.length === 0 ? (
            <EmptyState
              icon={<Users2 size={18} />}
              title="No matching users"
              body="Adjust the search or filters to reveal the company members."
            />
          ) : (
            users.map((user) => (
              <div
                key={user.id}
                className="grid grid-cols-1 gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1.9fr)_minmax(0,1.4fr)_120px_120px_160px_96px] lg:items-center"
              >
                <UserCell user={user} />
                <div className="min-w-0">
                  <p className="truncate text-sm text-navy-900">{user.email_id}</p>
                </div>
                <div>
                  <select
                    value={user.role}
                    onChange={(event) => onRoleChange(user.id, event.target.value)}
                    disabled={saving}
                    className="focus-ring w-full rounded-full border border-navy-100 bg-white px-3 py-2 text-sm text-navy-900 disabled:opacity-60"
                  >
                    <option value="user">User</option>
                    <option value="manager">Manager</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                <div>
                  <StatusBadge active={user.is_active} />
                </div>
                <div className="text-sm text-navy-700">
                  {user.last_login ? new Date(user.last_login).toLocaleString() : "Never"}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => onToggle(user)}
                    disabled={saving}
                    className="focus-ring inline-flex size-9 items-center justify-center rounded-xl border border-navy-100 bg-white text-navy-700 hover:bg-navy-50 disabled:opacity-60"
                    aria-label={user.is_active ? "Deactivate user" : "Reactivate user"}
                  >
                    {user.is_active ? <UserX size={15} /> : <UserCheck size={15} />}
                  </button>
                  <button
                    type="button"
                    disabled
                    className="inline-flex size-9 items-center justify-center rounded-xl border border-navy-100 bg-white text-navy-300"
                    aria-label="Edit user"
                    title="Edit user"
                  >
                    <UserCog size={15} />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export function InvitationsTable({
  invitations,
  onDelete,
  saving,
}: {
  invitations: ShayInvitation[];
  onDelete: (email: string) => void;
  saving: boolean;
}) {
  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-[1.5rem] border border-navy-100">
        <div className="grid grid-cols-[minmax(0,1.7fr)_120px_1.2fr_1.2fr_1.2fr_96px] gap-4 border-b border-navy-100 bg-canvas px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-subtle">
          <span>Email</span>
          <span>Role</span>
          <span>Invited by</span>
          <span>Invited on</span>
          <span>Expires on</span>
          <span>Actions</span>
        </div>
        <div className="divide-y divide-navy-100 bg-white">
          {invitations.length === 0 ? (
            <EmptyState
              icon={<MailPlus size={18} />}
              title="No matching invitations"
              body="Try widening the filters or search to reveal pending invites."
            />
          ) : (
            invitations.map((invitation) => (
              <div
                key={invitation.id}
                className="grid grid-cols-1 gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1.7fr)_120px_1.2fr_1.2fr_1.2fr_96px] lg:items-center"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-navy-900">{invitation.email}</p>
                </div>
                <div>
                  <RoleBadge role={invitation.role} />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm text-navy-900">
                    {invitation.invited_by.username || invitation.invited_by.userEmail || "Unknown"}
                  </p>
                </div>
                <div className="text-sm text-navy-700">
                  {formatDateTime(invitation.created_at)}
                </div>
                <div className="text-sm text-navy-700">
                  {formatDateTime(invitation.expires_at)}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled
                    className="focus-ring inline-flex size-9 items-center justify-center rounded-xl border border-navy-100 bg-white text-navy-300"
                    aria-label="Resend invitation"
                    title="Resend invitation"
                  >
                    <MailPlus size={15} />
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(invitation.email)}
                    disabled={saving}
                    className="focus-ring inline-flex size-9 items-center justify-center rounded-xl border border-rose-200 bg-white text-rose-600 hover:bg-rose-50 disabled:opacity-60"
                    aria-label="Delete invitation"
                    title="Delete invitation"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function UserCell({ user }: { user: ShayUser }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <Avatar name={user.name} email={user.email_id} />
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-navy-900">{user.name}</p>
        <p className="mt-1 text-xs text-subtle">
          {user.is_active ? "Team member" : "Inactive"}
        </p>
      </div>
    </div>
  );
}

function Avatar({ name, email }: { name: string; email: string }) {
  return (
    <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-navy-800 text-sm font-semibold text-white">
      {initials(name, email)}
    </div>
  );
}

function StatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-3 py-1 text-xs font-medium",
        active ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-700",
      )}
    >
      {active ? "Active" : "Inactive"}
    </span>
  );
}

function RoleBadge({ role }: { role: string }) {
  return (
    <span className="inline-flex items-center rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-700">
      {capitalize(role)}
    </span>
  );
}

function EmptyState({
  icon,
  title,
  body,
}: {
  icon: ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="col-span-full flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="flex size-12 items-center justify-center rounded-2xl bg-navy-50 text-navy-700">
        {icon}
      </div>
      <h3 className="mt-4 text-base font-semibold text-navy-900">{title}</h3>
      <p className="mt-2 max-w-md text-sm text-subtle">{body}</p>
    </div>
  );
}

function initials(name: string, email: string) {
  const source = name.trim() || email.trim();
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "A";
  if (parts.length === 1) return parts[0].slice(0, 1).toUpperCase();
  return `${parts[0].slice(0, 1)}${parts[1].slice(0, 1)}`.toUpperCase();
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString();
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
