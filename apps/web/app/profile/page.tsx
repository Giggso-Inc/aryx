"use client";

import { AuthGuard } from "@/components/shay/AuthGuard";
import { ShayPageShell } from "@/components/shay/ShayPageShell";
import { useShayAuth } from "@/lib/shay-auth";

function Detail({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-subtle">
        {label}
      </p>
      <p className="mt-3 text-sm font-medium text-navy-900">{value}</p>
    </div>
  );
}

export default function ProfilePage() {
  const { session, profile } = useShayAuth();
  const displayName = profile?.name || session?.name || "Aryx user";

  return (
    <AuthGuard>
      <ShayPageShell
        eyebrow="Profile"
        title={displayName}
        description="Manage your identity details, company context, and sign-in status from one place."
        contentWidth="wide"
      >
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
          <Detail label="Email" value={profile?.email_id || session?.email_id || "—"} />
          <Detail label="Role" value={profile?.role || session?.role || "—"} />
          <Detail label="Company" value={session?.company_name || session?.company_id || "—"} />
          <Detail label="Status" value={profile?.is_verified ? "Verified" : "Pending verification"} />
        </div>
      </ShayPageShell>
    </AuthGuard>
  );
}
