"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Building2, MailPlus, Users } from "lucide-react";
import { AuthGuard } from "./AuthGuard";
import { ShayPageShell } from "./ShayPageShell";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import type { ShayCompany, ShayUser } from "@/lib/shay-types";

export function AdminUsersPage() {
  const { session } = useShayAuth();
  const [company, setCompany] = useState<ShayCompany | null>(null);
  const [users, setUsers] = useState<ShayUser[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("user");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const [nextCompany, userList] = await Promise.all([
        shayApi.getMyCompany(session.access_token),
        shayApi.listCompanyUsers(session.company_id, session.access_token),
      ]);
      setCompany(nextCompany);
      setUsers(userList.users);
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to load company users.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [session?.access_token, session?.company_id]);

  const inviteUser = async () => {
    if (!session || !inviteEmail.trim()) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await shayApi.inviteUser({
        email: inviteEmail.trim(),
        company_id: session.company_id,
        role: inviteRole,
        user_id: session.user_id,
      }, session.access_token);
      setInviteEmail("");
      setInviteRole("user");
      setNotice("Invitation sent.");
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to invite user.");
    } finally {
      setSaving(false);
    }
  };

  const updateUser = async (userId: string, payload: { role?: string; is_active?: boolean }) => {
    if (!session) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await shayApi.updateCompanyUser(session.company_id, userId, payload, session.access_token);
      setNotice("User updated.");
      await load();
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to update user.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <AuthGuard>
      <ShayPageShell
        eyebrow="Company admin hub"
        title="Company user management"
        description="Manage company access, then assign those users to bridged workspaces where ingest and Ask are available."
      >
        {loading ? (
          <div className="rounded-[1.5rem] border border-navy-100 bg-white px-5 py-12 text-center text-sm text-subtle shadow-soft">
            Loading company users...
          </div>
        ) : (
          <div className="space-y-6">
            <section className="grid gap-4 md:grid-cols-3">
              <InfoCard
                icon={<Building2 size={16} />}
                title={company?.name || "Company"}
                body={company?.description || "The company object anchors login, invitations, and workspace ownership."}
              />
              <InfoCard
                icon={<Users size={16} />}
                title={`${users.length} active records`}
                body="These users can be assigned into the shared Aryx workspace."
              />
              <InfoCard
                icon={<MailPlus size={16} />}
                title="Invitation flow"
                body="Invites land in auth first, then new users can be mapped into any bridged workspace."
              />
            </section>

            <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-xl font-semibold text-navy-900">Invite users</h2>
                  <p className="mt-2 text-sm text-subtle">
                    Bring a user into the company so they can be added into specific workspaces next.
                  </p>
                </div>
                <Link
                  href="/workspaces"
                  className="rounded-full border border-navy-100 px-4 py-2 text-sm font-medium text-navy-700 hover:bg-navy-50"
                >
                  Open workspaces
                </Link>
              </div>
              <div className="mt-5 grid gap-4 md:grid-cols-[minmax(0,1fr)_180px_160px]">
                <input
                  value={inviteEmail}
                  onChange={(event) => setInviteEmail(event.target.value)}
                  placeholder="name@company.com"
                  className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
                />
                <select
                  value={inviteRole}
                  onChange={(event) => setInviteRole(event.target.value)}
                  className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
                >
                  <option value="user">User</option>
                  <option value="manager">Manager</option>
                  <option value="admin">Admin</option>
                </select>
                <button
                  type="button"
                  onClick={inviteUser}
                  disabled={!inviteEmail.trim() || saving}
                  className="focus-ring rounded-2xl bg-navy-800 px-4 py-3 text-sm font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
                >
                  Send invite
                </button>
              </div>
              {notice ? (
                <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
                  {notice}
                </div>
              ) : null}
              {error ? (
                <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                  {error}
                </div>
              ) : null}
            </section>

            <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
              <h2 className="text-xl font-semibold text-navy-900">Current users</h2>
              <div className="mt-5 space-y-3">
                {users.map((user) => (
                  <div key={user.id} className="grid gap-3 rounded-2xl border border-navy-100 p-4 md:grid-cols-[minmax(0,1fr)_150px_150px] md:items-center">
                    <div>
                      <p className="text-sm font-medium text-navy-900">{user.name}</p>
                      <p className="mt-1 text-xs text-subtle">
                        {user.email_id} · last login {user.last_login ? new Date(user.last_login).toLocaleString() : "never"}
                      </p>
                    </div>
                    <select
                      value={user.role}
                      onChange={(event) => void updateUser(user.id, { role: event.target.value })}
                      className="focus-ring rounded-xl border border-navy-100 px-3 py-2 text-sm text-navy-900"
                    >
                      <option value="user">User</option>
                      <option value="manager">Manager</option>
                      <option value="admin">Admin</option>
                    </select>
                    <button
                      type="button"
                      onClick={() => void updateUser(user.id, { is_active: !user.is_active })}
                      className="focus-ring rounded-xl border border-navy-100 px-3 py-2 text-sm font-medium text-navy-700 hover:bg-navy-50"
                    >
                      {user.is_active ? "Deactivate" : "Reactivate"}
                    </button>
                  </div>
                ))}
              </div>
            </section>
          </div>
        )}
      </ShayPageShell>
    </AuthGuard>
  );
}

function InfoCard({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
      <div className="inline-flex items-center gap-2 rounded-full bg-navy-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-navy-700">
        {icon}
        {title}
      </div>
      <p className="mt-4 text-sm text-subtle">{body}</p>
    </div>
  );
}
