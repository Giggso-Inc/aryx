"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { Header } from "@/components/brand/Header";
import { LightweightTab } from "@/components/model/LightweightTab";
import { RulesTab } from "@/components/model/RulesTab";
import { VersionsTab } from "@/components/model/VersionsTab";
import { PublishTab } from "@/components/model/PublishTab";
import { ImportTab } from "@/components/model/ImportTab";
import { useWorkspace } from "@/lib/workspace";
import { cn } from "@/lib/cn";
import { TabBar } from "./TabBar";
import type { Tab } from "./tab-config";

// Canvas (schema diagram) touches window — keep client-only.
const Canvas = dynamic(
  () => import("@/components/model/Canvas").then((m) => m.Canvas),
  { ssr: false, loading: () => (
    <div className="flex flex-1 items-center justify-center text-[13px] text-subtle">
      Loading schema diagram…
    </div>
  ) },
);

export default function ModelPage() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  const [tab, setTab] = useState<Tab>("lightweight");
  const [diagramKey, setDiagramKey] = useState(0);

  // When types change (approve/create/import), reload the diagram.
  const handleChanged = () => setDiagramKey((k) => k + 1);

  const isDiagram = tab === "diagram";

  return (
    <div className={cn("flex flex-col", isDiagram ? "h-screen" : "min-h-screen")}>
      <Header workspaceId={workspaceId} onWorkspaceChange={setWorkspaceId} />

      <div className={cn("app-shell-offset flex min-w-0 flex-1 flex-col", isDiagram ? "min-h-0" : "")}>
        <TabBar tab={tab} isDiagram={isDiagram} onTabChange={setTab} />

        {isDiagram ? (
          <Canvas key={diagramKey} />
        ) : (
          <main className="workspace-section-shell flex-1 py-6">
            {tab === "lightweight" && (
              <LightweightTab workspaceId={workspaceId} onChanged={handleChanged} />
            )}
            {tab === "rules" && <RulesTab workspaceId={workspaceId} />}
            {tab === "versions" && <VersionsTab workspaceId={workspaceId} />}
            {tab === "publish" && <PublishTab workspaceId={workspaceId} />}
            {tab === "import" && (
              <ImportTab
                workspaceId={workspaceId}
                onImported={() => { handleChanged(); setTab("lightweight"); }}
              />
            )}
          </main>
        )}
        </div>
    </div>
  );
}
