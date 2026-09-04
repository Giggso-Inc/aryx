import { MailPlus, Trash2 } from "lucide-react";
import type { ShayInvitation } from "@/lib/shay-types";
import { EmptyState, RoleBadge } from "./shared";

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

function formatDateTime(value: string) {
  return new Date(value).toLocaleString();
}
