"use client";

import { useCallback, useState } from "react";
import dynamic from "next/dynamic";
import {
  FolderDown, FolderUp, GitBranch, Scale, Table2, Weight,
} from "lucide-react";
import { Header } from "@/components/brand/Header";
import { cn } from "@/lib/cn";
import { useWorkspace } from "@/lib/workspace";
import { LightweightTab } from "@/components/model/LightweightTab";
import { RulesTab } from "@/components/model/RulesTab";
import { VersionsTab } from "@/components/model/VersionsTab";
import { PublishTab } from "@/components/model/PublishTab";
import { ImportTab } from "@/components/model/ImportTab";

// React Flow touches `window` during import; keep it client-only.
const Canvas = dynamic(
  () => import("@/components/model/Canvas").then((m) => m.Canvas),
  { ssr: false },
);

type Tab = "lightweight" | "diagram" | "rules" | "versions" | "publish" | "import";

const TABS: { id: Tab; label: string; icon: typeof Weight }[] = [
  { id: "lightweight", label: "Lightweight", icon: Weight },
  { id: "diagram", label: "Diagram", icon: Table2 },
  { id: "rules", label: "Rules", icon: Scale },
  { id: "versions", label: "Versions", icon: GitBranch },
  { id: "publish", label: "Publish", icon: FolderUp },
  { id: "import", label: "Import", icon: FolderDown },
];

export default function ModelPage() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  const [tab, setTab] = useState<Tab>("lightweight");
  const [diagramKey, setDiagramKey] = useState(0);

  // Any type-changing action (approve/create/delete/import) bumps this so
  // the diagram tab remounts and reloads fresh data next time it's shown.
  const handleChanged = useCallback(() => setDiagramKey((k) => k + 1), []);

  return (
    <div className="flex h-screen flex-col">
      <Header workspaceId={workspaceId} onWorkspaceChange={setWorkspaceId} />

      <div className="flex items-center gap-1 border-b border-navy-100 bg-white px-6">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cn(
              "focus-ring relative inline-flex items-center gap-1.5 px-3 py-2.5 text-[13px] font-medium transition-colors",
              tab === id ? "text-navy-900" : "text-subtle hover:text-navy-700",
            )}
          >
            <Icon size={14} />
            {label}
            {tab === id && (
              <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-navy-800" />
            )}
          </button>
        ))}
      </div>

      {tab !== "diagram" && (
        <div className="border-b border-navy-100 bg-navy-50/50 px-6 py-1.5 text-center text-[11px] text-subtle">
          Brief → Ingest → Lightweight → HITL review → Heavyweight (Rules + Versions) → Publish
        </div>
      )}

      <div className="flex flex-1 flex-col overflow-hidden">
        {tab === "lightweight" && (
          <LightweightTab workspaceId={workspaceId} onChanged={handleChanged} />
        )}
        {tab === "diagram" && <Canvas key={diagramKey} />}
        {tab === "rules" && <RulesTab workspaceId={workspaceId} />}
        {tab === "versions" && <VersionsTab workspaceId={workspaceId} />}
        {tab === "publish" && <PublishTab workspaceId={workspaceId} />}
        {tab === "import" && (
          <ImportTab
            workspaceId={workspaceId}
            onImported={() => { handleChanged(); setTab("lightweight"); }}
          />
        )}
      </div>
    </div>
  );
}
