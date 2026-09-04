import Link from "next/link";
import { Settings2, Sparkles } from "lucide-react";
import { ActionCard } from "./shared";

export function CommandCenter({
  workspaceId,
  onNewChat,
}: {
  workspaceId: string;
  onNewChat: () => void;
}) {
  return (
    <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-navy-900">Workspace command center</h2>
          <p className="mt-2 text-sm text-subtle">
            Move between Aryx administration and graph work without leaving this workspace.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onNewChat}
            className="focus-ring inline-flex items-center gap-2 rounded-full bg-navy-800 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-700"
          >
            <Sparkles size={15} />
            New Ask session
          </button>
          <Link
            href={`/workspaces/${workspaceId}/settings`}
            className="focus-ring inline-flex items-center gap-2 rounded-full border border-navy-100 px-4 py-2 text-sm font-medium text-navy-700 hover:bg-navy-50"
          >
            <Settings2 size={15} />
            Workspace settings
          </Link>
        </div>
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <ActionCard
          title="Workspace members"
          description="Manage company users, membership roles, and shared access from the workspace settings tabs."
          href={`/workspaces/${workspaceId}/settings?tab=members`}
        />
        <ActionCard
          title="Apps and connections"
          description="Attach workspace apps while preserving the Aryx bridge to downstream ingest and Ask."
          href={`/workspaces/${workspaceId}/settings?tab=apps`}
        />
        <ActionCard
          title="Data sources and ingest"
          description="Register sources, then sync them into Aryx ingest with a workspace-aware datasource map."
          href={`/workspaces/${workspaceId}/settings?tab=data-sources`}
        />
        <ActionCard
          title="Admin hub"
          description="Invite and manage company users who can participate in this shared workspace."
          href="/admin/users"
        />
      </div>
    </section>
  );
}
