"use client";

import { FolderPlus, Search } from "lucide-react";
import { AuthGuard } from "./AuthGuard";
import { WorkspaceIndexCard } from "./WorkspaceIndexCard";
import { WorkspaceProfileDialog } from "./WorkspaceProfileDialog";
import { ShayPageShell } from "./ShayPageShell";
import { workspaceSectionHref } from "@/lib/workspace-route";
import { CreateWorkspaceModal } from "./workspace-index/CreateWorkspaceModal";
import { DeleteWorkspaceModal } from "./workspace-index/DeleteWorkspaceModal";
import { useWorkspaceIndexPage } from "./workspace-index/useWorkspaceIndexPage";

export function WorkspaceIndexPage() {
  const s = useWorkspaceIndexPage();

  return (
    <AuthGuard>
      <ShayPageShell
        title="Workspaces"
        description="Create and manage workspaces."
        showHero={false}
        contentWidth="wide"
      >
        <div className="space-y-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <label className="relative block w-full max-w-xl">
              <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-subtle" />
              <input
                value={s.query}
                onChange={(event) => s.setQuery(event.target.value)}
                placeholder="Search workspaces..."
                className="focus-ring w-full rounded-2xl border border-navy-100 bg-white py-3 pl-11 pr-4 text-sm text-navy-900 shadow-soft"
              />
            </label>
            <button
              type="button"
              onClick={() => {
                s.setModalError(null);
                s.setShowCreateModal(true);
              }}
              className="focus-ring inline-flex items-center justify-center gap-2 rounded-2xl bg-navy-800 px-5 py-3 text-sm font-semibold text-white shadow-soft hover:bg-navy-700"
            >
              <FolderPlus size={16} />
              New Workspace
            </button>
          </div>

          {s.loading ? (
            <div className="rounded-[1.5rem] border border-navy-100 bg-white px-5 py-12 text-center text-sm text-subtle shadow-soft">
              Loading Aryx workspaces...
            </div>
          ) : s.filteredWorkspaces.length === 0 ? (
            <div className="rounded-[1.75rem] border border-dashed border-navy-200 bg-white px-5 py-16 text-center shadow-soft">
              <div className="mx-auto max-w-md">
                <p className="text-lg font-semibold text-navy-900">
                  {s.workspaces.length === 0 ? "No workspaces yet." : "No workspaces match that search."}
                </p>
                <p className="mt-2 text-sm text-subtle">
                  {s.workspaces.length === 0
                    ? "Create the first workspace to start the Aryx bridge."
                    : "Try a different name or description keyword."}
                </p>
              </div>
            </div>
          ) : (
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {s.filteredWorkspaces.map((workspace) => (
                <WorkspaceIndexCard
                  key={workspace.id}
                  workspace={workspace}
                  metrics={s.workspaceMetrics[workspace.id]}
                  onOpen={() => s.router.push(workspaceSectionHref(workspace.id, "home"))}
                  onEdit={() => s.openEditModal(workspace)}
                  onDelete={() => {
                    s.setDeleteError(null);
                    s.setWorkspaceToDelete(workspace);
                  }}
                />
              ))}
            </div>
          )}
        </div>

        <CreateWorkspaceModal
          open={s.showCreateModal}
          name={s.name}
          description={s.description}
          modalError={s.modalError}
          saving={s.saving}
          onNameChange={s.setName}
          onDescriptionChange={s.setDescription}
          onClose={s.resetModal}
          onCreate={() => void s.createWorkspace()}
        />

        <DeleteWorkspaceModal
          workspace={s.workspaceToDelete}
          deleteError={s.deleteError}
          deleting={Boolean(s.workspaceToDelete && s.deletingWorkspaceId === s.workspaceToDelete.id)}
          onClose={() => {
            s.setDeleteError(null);
            s.setWorkspaceToDelete(null);
          }}
          onConfirm={() => void s.deleteWorkspace()}
        />

        {s.workspaceToEdit ? (
          <WorkspaceProfileDialog
            description={s.editDescription}
            error={s.modalError}
            name={s.editName}
            onClose={s.closeEditModal}
            onDescriptionChange={s.setEditDescription}
            onNameChange={s.setEditName}
            onSave={s.saveEditedWorkspace}
            saving={s.saving}
            title="Edit workspace"
            descriptionText="Update the workspace name and description directly from the workspace library."
          />
        ) : null}
      </ShayPageShell>
    </AuthGuard>
  );
}
