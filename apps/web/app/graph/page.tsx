"use client";

import dynamic from "next/dynamic";
import { Header } from "@/components/brand/Header";
import { useWorkspace } from "@/lib/workspace";

const EntityGraph = dynamic(
  () => import("@/components/graph/EntityGraph").then((m) => m.EntityGraph),
  { ssr: false },
);

export default function GraphPage() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  return (
    <div className="flex h-screen flex-col">
      <Header workspaceId={workspaceId} onWorkspaceChange={setWorkspaceId} />
      <EntityGraph workspaceId={workspaceId} />
    </div>
  );
}
