"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, Link2, Save, ShieldCheck, Users2 } from "lucide-react";
import { AuthGuard } from "./AuthGuard";
import { ShayPageShell } from "./ShayPageShell";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import type {
  ShayApp,
  ShayDatasource,
  ShayUser,
  ShayWorkspace,
  ShayWorkspaceAppConnection,
  ShayWorkspaceMember,
} from "@/lib/shay-types";

const datasourceKinds = ["postgresql", "mysql", "oracle", "docs", "rest"];

export function WorkspaceSettingsPage({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const tab = searchParams.get("tab") || "members";
  const { session, profile } = useShayAuth();

  const [workspace, setWorkspace] = useState<ShayWorkspace | null>(null);
  const [members, setMembers] = useState<ShayWorkspaceMember[]>([]);
  const [companyUsers, setCompanyUsers] = useState<ShayUser[]>([]);
  const [apps, setApps] = useState<ShayApp[]>([]);
  const [connections, setConnections] = useState<ShayWorkspaceAppConnection[]>([]);
  const [datasources, setDatasources] = useState<ShayDatasource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [draftName, setDraftName] = useState("");
  const [draftDescription, setDraftDescription] = useState("");
  const [memberUserId, setMemberUserId] = useState("");
  const [memberRole, setMemberRole] = useState("member");
  const [appId, setAppId] = useState("");
  const [connectionName, setConnectionName] = useState("");
  const [connectionProvider, setConnectionProvider] = useState("");
  const [datasourceName, setDatasourceName] = useState("");
  const [datasourceProvider, setDatasourceProvider] = useState("");
  const [datasourceUrl, setDatasourceUrl] = useState("");
  const [datasourceKind, setDatasourceKind] = useState("rest");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const nextWorkspace = await shayApi.getWorkspace(workspaceId, session.access_token);
      await shayApi.ensureWorkspaceBridge({
        shay_workspace_id: nextWorkspace.id,
        name: nextWorkspace.name,
        description: nextWorkspace.description ?? "",
        company_id: session.company_id,
      });
      const [memberList, userList, appList, connectionList, datasourceList] = await Promise.all([
        shayApi.listWorkspaceMembers(workspaceId, session.access_token),
        shayApi.listCompanyUsers(session.company_id, session.access_token),
        shayApi.listApps(session.access_token),
        shayApi.listWorkspaceAppConnections(workspaceId, session.access_token),
        shayApi.listDatasources(workspaceId, session.access_token),
      ]);
      setWorkspace(nextWorkspace);
      setDraftName(nextWorkspace.name);
      setDraftDescription(nextWorkspace.description ?? "");
      setMembers(memberList.members);
      setCompanyUsers(userList.users);
      setApps(appList.apps);
      setConnections(connectionList.connections);
      setDatasources(datasourceList.items);
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to load workspace settings.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [session?.access_token, session?.company_id, workspaceId]);

  const availableUsers = useMemo(() => {
    const memberIds = new Set(members.map((member) => member.user_id));
    return companyUsers.filter((user) => !memberIds.has(user.id));
  }, [companyUsers, members]);

  const setTab = (nextTab: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", nextTab);
    router.replace(`${pathname}?${params.toString()}`);
  };

  const saveWorkspace = async () => {
    if (!session || !workspace) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await shayApi.updateWorkspace(workspace.id, {
        name: draftName,
        description: draftDescription,
      }, session.access_token);
      await shayApi.ensureWorkspaceBridge({
        shay_workspace_id: updated.id,
        name: updated.name,
        description: updated.description ?? "",
        company_id: session.company_id,
      });
      setWorkspace(updated);
      setNotice("Workspace profile saved and bridge metadata refreshed.");
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to save workspace.");
    } finally {
      setSaving(false);
    }
  };

  const addMember = async () => {
    if (!session || !memberUserId) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await shayApi.addWorkspaceMember(workspaceId, {
        user_id: memberUserId,
        role: memberRole,
      }, session.access_token);
      setMemberUserId("");
      setNotice("Workspace member added.");
      await load();
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to add member.");
    } finally {
      setSaving(false);
    }
  };

  const updateMember = async (userId: string, payload: { role?: string; is_active?: boolean }) => {
    if (!session) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await shayApi.updateWorkspaceMember(workspaceId, userId, payload, session.access_token);
      setNotice("Workspace member updated.");
      await load();
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to update member.");
    } finally {
      setSaving(false);
    }
  };

  const removeMember = async (userId: string) => {
    if (!session) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await shayApi.removeWorkspaceMember(workspaceId, userId, session.access_token);
      setNotice("Workspace member removed.");
      await load();
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to remove member.");
    } finally {
      setSaving(false);
    }
  };

  const addConnection = async () => {
    if (!session || !appId) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await shayApi.createWorkspaceAppConnection(workspaceId, {
        app_id: appId,
        connection_name: connectionName || undefined,
        provider: connectionProvider || undefined,
      }, session.access_token);
      setAppId("");
      setConnectionName("");
      setConnectionProvider("");
      setNotice("Workspace app connection added.");
      await load();
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to add app connection.");
    } finally {
      setSaving(false);
    }
  };

  const toggleConnection = async (connection: ShayWorkspaceAppConnection) => {
    if (!session) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await shayApi.updateWorkspaceAppConnection(workspaceId, connection.id, {
        is_active: !connection.is_active,
        connection_status: !connection.is_active ? "active" : "inactive",
      }, session.access_token);
      setNotice("Workspace app connection updated.");
      await load();
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to update connection.");
    } finally {
      setSaving(false);
    }
  };

  const addDatasource = async () => {
    if (!session || !datasourceName.trim()) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const datasource = await shayApi.createDatasource({
        workspace_id: workspaceId,
        name: datasourceName.trim(),
        storage_type: datasourceKind === "docs" ? "local" : datasourceKind === "rest" ? "app" : "database",
        provider: datasourceProvider || datasourceKind,
        file_url: datasourceUrl || undefined,
        config: datasourceUrl ? { url: datasourceUrl } : {},
        datasource_metadata: {
          source: "shay-settings",
          created_by_name: profile?.name || session.name || session.email_id,
        },
      }, session.access_token);
      await shayApi.syncDatasourceBridge({
        shay_workspace_id: workspaceId,
        shay_datasource_id: datasource.id,
        name: datasource.name,
        kind: datasourceKind,
        config: datasource.config ?? {},
      });
      setDatasourceName("");
      setDatasourceProvider("");
      setDatasourceUrl("");
      setDatasourceKind("rest");
      setNotice("Datasource created and synced into Aryx ingest.");
      await load();
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to create datasource.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <AuthGuard>
      <ShayPageShell
        eyebrow="Workspace settings"
        title={workspace ? `${workspace.name} settings` : "Workspace settings"}
        description="Manage membership, app connections, and datasource bridging for this workspace while keeping the Aryx mapping current."
      >
        {loading ? (
          <div className="rounded-[1.5rem] border border-navy-100 bg-white px-5 py-12 text-center text-sm text-subtle shadow-soft">
            Loading workspace settings...
          </div>
        ) : (
          <div className="space-y-6">
            <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-xl font-semibold text-navy-900">Workspace profile</h2>
                  <p className="mt-2 text-sm text-subtle">
                    Keep the workspace profile in sync with the mapped Aryx workspace identity.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={saveWorkspace}
                  disabled={saving}
                  className="focus-ring inline-flex items-center gap-2 rounded-full bg-navy-800 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
                >
                  <Save size={15} />
                  Save workspace
                </button>
              </div>
              <div className="mt-5 grid gap-4 md:grid-cols-2">
                <input
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                  placeholder="Workspace name"
                  className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
                />
                <input
                  value={draftDescription}
                  onChange={(event) => setDraftDescription(event.target.value)}
                  placeholder="Workspace description"
                  className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
                />
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
              <div className="flex flex-wrap gap-2">
                {[
                  ["members", "Workspace members"],
                  ["apps", "Apps"],
                  ["data-sources", "Data sources"],
                ].map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setTab(key)}
                    className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                      tab === key ? "bg-navy-800 text-white" : "bg-navy-50 text-navy-700 hover:bg-navy-100"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {tab === "members" ? (
                <div className="mt-6 space-y-5">
                  <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_160px_160px]">
                    <select
                      value={memberUserId}
                      onChange={(event) => setMemberUserId(event.target.value)}
                      className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
                    >
                      <option value="">Select company user</option>
                      {availableUsers.map((user) => (
                        <option key={user.id} value={user.id}>
                          {user.name} ({user.email_id})
                        </option>
                      ))}
                    </select>
                    <select
                      value={memberRole}
                      onChange={(event) => setMemberRole(event.target.value)}
                      className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
                    >
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                      <option value="viewer">Viewer</option>
                    </select>
                    <button
                      type="button"
                      onClick={addMember}
                      disabled={!memberUserId || saving}
                      className="focus-ring rounded-2xl bg-navy-800 px-4 py-3 text-sm font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
                    >
                      Add member
                    </button>
                  </div>
                  <div className="space-y-3">
                    {members.map((member) => (
                      <div key={member.id} className="grid gap-3 rounded-2xl border border-navy-100 p-4 md:grid-cols-[minmax(0,1fr)_140px_140px_120px] md:items-center">
                        <div>
                          <p className="text-sm font-medium text-navy-900">{member.name || member.email || member.user_id}</p>
                          <p className="mt-1 text-xs text-subtle">{member.email || member.user_id}</p>
                        </div>
                        <select
                          value={member.role}
                          onChange={(event) => void updateMember(member.user_id, { role: event.target.value })}
                          className="focus-ring rounded-xl border border-navy-100 px-3 py-2 text-sm text-navy-900"
                        >
                          <option value="member">Member</option>
                          <option value="admin">Admin</option>
                          <option value="viewer">Viewer</option>
                        </select>
                        <button
                          type="button"
                          onClick={() => void updateMember(member.user_id, { is_active: !member.is_active })}
                          className="focus-ring rounded-xl border border-navy-100 px-3 py-2 text-sm font-medium text-navy-700 hover:bg-navy-50"
                        >
                          {member.is_active ? "Deactivate" : "Reactivate"}
                        </button>
                        <button
                          type="button"
                          onClick={() => void removeMember(member.user_id)}
                          className="focus-ring rounded-xl border border-rose-200 px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50"
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {tab === "apps" ? (
                <div className="mt-6 space-y-5">
                  <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_180px_180px_150px]">
                    <select
                      value={appId}
                      onChange={(event) => setAppId(event.target.value)}
                      className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
                    >
                      <option value="">Select app</option>
                      {apps.map((app) => (
                        <option key={app.id} value={app.id}>
                          {app.app_name} ({app.app_key})
                        </option>
                      ))}
                    </select>
                    <input
                      value={connectionName}
                      onChange={(event) => setConnectionName(event.target.value)}
                      placeholder="Connection name"
                      className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
                    />
                    <input
                      value={connectionProvider}
                      onChange={(event) => setConnectionProvider(event.target.value)}
                      placeholder="Provider"
                      className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
                    />
                    <button
                      type="button"
                      onClick={addConnection}
                      disabled={!appId || saving}
                      className="focus-ring rounded-2xl bg-navy-800 px-4 py-3 text-sm font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
                    >
                      Connect app
                    </button>
                  </div>
                  <div className="space-y-3">
                    {connections.map((connection) => {
                      const app = apps.find((item) => item.id === connection.app_id);
                      return (
                        <div key={connection.id} className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-navy-100 p-4">
                          <div>
                            <p className="text-sm font-medium text-navy-900">
                              {connection.connection_name || app?.app_name || connection.app_id}
                            </p>
                            <p className="mt-1 text-xs text-subtle">
                              {app?.app_key || "unknown app"} · {connection.connection_status} · {connection.provider || "provider not set"}
                            </p>
                          </div>
                          <button
                            type="button"
                            onClick={() => void toggleConnection(connection)}
                            className="focus-ring rounded-xl border border-navy-100 px-3 py-2 text-sm font-medium text-navy-700 hover:bg-navy-50"
                          >
                            {connection.is_active ? "Disable" : "Enable"}
                          </button>
                        </div>
                      );
                    })}
                    {connections.length === 0 ? (
                      <p className="rounded-2xl border border-dashed border-navy-200 px-4 py-6 text-sm text-subtle">
                        No app connections yet for this workspace.
                      </p>
                    ) : null}
                  </div>
                </div>
              ) : null}

              {tab === "data-sources" ? (
                <div className="mt-6 space-y-5">
                  <div className="rounded-2xl border border-navy-100 bg-canvas p-4 text-sm text-subtle">
                    Each datasource created here is also synced into Aryx ingest through the bridge table so the workspace can use Ask immediately after ingestion is configured.
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    <input
                      value={datasourceName}
                      onChange={(event) => setDatasourceName(event.target.value)}
                      placeholder="Datasource name"
                      className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
                    />
                    <select
                      value={datasourceKind}
                      onChange={(event) => setDatasourceKind(event.target.value)}
                      className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
                    >
                      {datasourceKinds.map((kind) => (
                        <option key={kind} value={kind}>{kind}</option>
                      ))}
                    </select>
                    <input
                      value={datasourceProvider}
                      onChange={(event) => setDatasourceProvider(event.target.value)}
                      placeholder="Provider or app key"
                      className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
                    />
                    <input
                      value={datasourceUrl}
                      onChange={(event) => setDatasourceUrl(event.target.value)}
                      placeholder="URL, file path, or connection hint"
                      className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={addDatasource}
                    disabled={!datasourceName.trim() || saving}
                    className="focus-ring rounded-2xl bg-navy-800 px-4 py-3 text-sm font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
                  >
                    Create and sync datasource
                  </button>
                  <div className="space-y-3">
                    {datasources.map((datasource) => (
                      <div key={datasource.id} className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-navy-100 p-4">
                        <div>
                          <p className="text-sm font-medium text-navy-900">{datasource.name}</p>
                          <p className="mt-1 text-xs text-subtle">
                            {datasource.storage_type} · {datasource.provider || "manual"} · {datasource.processing_status}
                          </p>
                        </div>
                        <Link
                          href={`/workspaces/${workspaceId}`}
                          className="inline-flex items-center gap-2 rounded-full border border-navy-100 px-3 py-1.5 text-xs font-medium text-navy-700 hover:bg-navy-50"
                        >
                          Overview
                          <ArrowRight size={12} />
                        </Link>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </section>

            <section className="grid gap-4 md:grid-cols-3">
              <InfoCard
                icon={<Users2 size={16} />}
                title="Member control"
                body="Workspace membership uses bridge tables while the mapping keeps the matching Aryx workspace available for Ask and ingest."
              />
              <InfoCard
                icon={<Link2 size={16} />}
                title="Bridge refresh"
                body="Saving workspace metadata updates the Aryx bridge mapping so names and descriptions stay aligned."
              />
              <InfoCard
                icon={<ShieldCheck size={16} />}
                title="Shared database"
                body="Both services run against the same Postgres instance with separate API surfaces and common bridge tables."
              />
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
