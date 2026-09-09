"use client";

import { PencilLine } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatWorkspaceName } from "@/lib/workspace-name";
import { AuthGuard } from "./AuthGuard";
import { ShayPageShell } from "./ShayPageShell";
import { WorkspaceProfileDialog } from "./WorkspaceProfileDialog";
import { AppsTab } from "./workspace-settings/AppsTab";
import { DangerZoneTab } from "./workspace-settings/DangerZoneTab";
import { MembersTab } from "./workspace-settings/MembersTab";
import { InlineNotice, ProfileSummaryField } from "./workspace-settings/shared";
import { SETTINGS_TABS } from "./workspace-settings/types";
import { useWorkspaceSettingsPage } from "./workspace-settings/useWorkspaceSettingsPage";

export function WorkspaceSettingsPage({ workspaceId }: { workspaceId: string }) {
  const s = useWorkspaceSettingsPage(workspaceId);

  return (
    <AuthGuard>
      <ShayPageShell
        eyebrow="Workspace settings"
        title="Workspace settings"
        description="Manage workspace access and maintenance actions while keeping the Aryx workspace mapping aligned."
        showHero={false}
        contentCard={false}
        contentWidth="detail"
      >
        {s.loading ? (
          <div className="rounded-[1.5rem] border border-navy-100 bg-white px-5 py-12 text-center text-sm text-subtle shadow-soft">
            Loading workspace settings...
          </div>
        ) : (
          <div className="space-y-6">
            <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
              <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                <div className="flex w-full flex-col gap-5 lg:flex-row lg:items-start">
                  <div className="grid flex-1 gap-5 md:grid-cols-2">
                    <ProfileSummaryField
                      label="Workspace name"
                      value={formatWorkspaceName(s.workspace?.name)}
                    />
                    <ProfileSummaryField
                      label="Workspace description"
                      value={s.workspace?.description || "No description added yet."}
                    />
                  </div>

                  {s.canManageWorkspace ? (
                    <button
                      type="button"
                      onClick={() => s.setEditProfileOpen(true)}
                      className="focus-ring inline-flex items-center justify-center gap-2 self-start rounded-full border border-navy-200 bg-white px-4 py-2 text-sm font-semibold text-navy-800 hover:bg-navy-50 lg:ml-auto"
                    >
                      <PencilLine size={15} />
                      Edit workspace
                    </button>
                  ) : null}
                </div>
              </div>

              {s.notice ? <InlineNotice tone="success">{s.notice}</InlineNotice> : null}
              {s.error ? <InlineNotice tone="error">{s.error}</InlineNotice> : null}
            </section>

            <section className="overflow-hidden rounded-[1.5rem] border border-navy-100 bg-white shadow-soft">
              <div className="border-b border-navy-100 bg-white">
                <div className="flex flex-wrap items-end gap-0 px-5">
                  {SETTINGS_TABS
                    .filter((item) => item.id !== "danger-zone" || s.canManageWorkspace)
                    .map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => s.setTab(item.id)}
                      className={cn(
                        "border-b-2 px-4 py-3 text-sm font-medium transition-colors",
                        s.activeTab === item.id
                          ? "border-navy-800 text-navy-900"
                          : "border-transparent text-navy-500 hover:text-navy-800",
                      )}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="px-5 py-5">
                {s.activeTab === "members" ? (
                  <MembersTab
                    addMemberOpen={s.addMemberOpen}
                    availableUsers={s.availableUsers}
                    canManageMembers={s.canManageWorkspace}
                    currentUserId={s.session?.user_id ?? null}
                    memberBusy={s.memberBusy}
                    members={s.displayMembers}
                    onAddMember={s.addMember}
                    onCloseModal={s.closeAddMemberModal}
                    onOpenModal={s.openAddMemberModal}
                    onRemoveMember={s.removeMember}
                    onUpdateMemberRole={s.updateMemberRole}
                  />
                ) : null}

                {s.activeTab === "apps" ? <AppsTab /> : null}

                {s.activeTab === "danger-zone" ? (
                  <DangerZoneTab
                    bridgeReady={Boolean(s.bridge?.aryx_workspace_id)}
                    dangerError={s.dangerError}
                    dangerNotice={s.dangerNotice}
                    deleting={s.deleting}
                    onDeleteWorkspace={s.deleteWorkspace}
                    onPurgeWorkspace={s.purgeWorkspaceData}
                    purging={s.purging}
                  />
                ) : null}
              </div>
            </section>
          </div>
        )}
        {s.editProfileOpen ? (
          <WorkspaceProfileDialog
            description={s.draftDescription}
            name={s.draftName}
            onClose={() => s.setEditProfileOpen(false)}
            onDescriptionChange={s.setDraftDescription}
            onNameChange={s.setDraftName}
            onSave={s.saveWorkspace}
            saving={s.savingProfile}
          />
        ) : null}
      </ShayPageShell>
    </AuthGuard>
  );
}
