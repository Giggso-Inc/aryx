import Link from "next/link";
import { ArrowRight, MessageSquareText } from "lucide-react";
import type { ShayBridgeThread } from "@/lib/shay-types";

export function ChatSessionsPanel({
  workspaceId,
  threads,
  onNewChat,
}: {
  workspaceId: string;
  threads: ShayBridgeThread[];
  onNewChat: () => void;
}) {
  return (
    <section className="rounded-[1.5rem] border border-navy-100 bg-white p-5 shadow-soft">
      <div className="flex items-center gap-2 text-sm font-semibold text-navy-900">
        <MessageSquareText size={15} />
        Mapped chat sessions
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {threads.map((thread) => (
          <Link
            key={thread.shay_thread_id}
            href={`/workspaces/${workspaceId}/chats/${thread.shay_thread_id}`}
            className="group rounded-[1.5rem] border border-navy-100 bg-canvas p-4 transition-colors hover:border-steel-300"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold text-navy-900">{thread.title}</h3>
                <p className="mt-2 text-sm text-subtle">
                  {thread.turn_count} turn{thread.turn_count === 1 ? "" : "s"} · updated {new Date(thread.updated_at).toLocaleString()}
                </p>
              </div>
              <ArrowRight size={16} className="text-subtle transition-transform group-hover:translate-x-1" />
            </div>
          </Link>
        ))}
        {threads.length === 0 ? (
          <button
            type="button"
            onClick={onNewChat}
            className="rounded-[1.5rem] border border-dashed border-navy-200 bg-canvas p-5 text-left text-sm text-subtle hover:border-steel-300"
          >
            Create the first Aryx Ask session for this workspace.
          </button>
        ) : null}
      </div>
    </section>
  );
}
