import { Clock3 } from "lucide-react";
import { formatWorkspaceName } from "@/lib/workspace-name";

export function SessionSidebar({
  workspaceId,
  workspaceName,
  threadId,
}: {
  workspaceId: string;
  workspaceName?: string;
  threadId: string;
}) {
  return (
    <aside className="space-y-4">
      <div className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
        <h3 className="text-sm font-semibold text-navy-900">Merged behavior</h3>
        <ul className="mt-3 space-y-3 text-sm text-subtle">
          <li>Each thread is mapped to one Aryx Ask session key and workspace bridge.</li>
          <li>Citations and grounding come from the Aryx Ask pipeline and stay visible here.</li>
          <li>Conversation history is persisted in Aryx bridge tables for replay and audit.</li>
        </ul>
      </div>
      <div className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
        <div className="flex items-center gap-2 text-sm font-semibold text-navy-900">
          <Clock3 size={14} />
          Session details
        </div>
        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex items-start justify-between gap-3">
            <dt className="text-subtle">Workspace</dt>
            <dd className="text-right font-medium text-navy-900">
              {workspaceName ? formatWorkspaceName(workspaceName) : workspaceId}
            </dd>
          </div>
          <div className="flex items-start justify-between gap-3">
            <dt className="text-subtle">Thread</dt>
            <dd className="text-right font-medium text-navy-900">{threadId}</dd>
          </div>
        </dl>
      </div>
    </aside>
  );
}
