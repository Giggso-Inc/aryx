"use client";

import { Header } from "@/components/brand/Header";
import { DataExplorer } from "@/components/data/DataExplorer";
import { useWorkspace } from "@/lib/workspace";

export default function DataPage() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  return (
    <div className="flex min-h-screen flex-col">
      <Header workspaceId={workspaceId} onWorkspaceChange={setWorkspaceId} />
      <main className="app-shell-offset flex-1">
        <DataExplorer />
      </main>
    </div>
  );
}
