"use client";

import dynamic from "next/dynamic";
import { Header } from "@/components/brand/Header";
import { useWorkspace } from "@/lib/workspace";

// @xyflow/react touches `window` during import; keep it client-only (same
// pattern as /model's Canvas — see apps/web/app/model/page.tsx).
const EntityGraph = dynamic(
  () => import("@/components/graph/EntityGraph").then((m) => m.EntityGraph),
  { ssr: false },
);

export default function GraphPage() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  return (
    <div className="flex h-screen flex-col">
      <Header workspaceId={workspaceId} onWorkspaceChange={setWorkspaceId} />
      <div className="flex min-h-0 flex-1 flex-col p-4">
        <EntityGraph workspaceId={workspaceId} />
      </div>
    </div>
  );
}
