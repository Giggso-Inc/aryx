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

// Canvas (schema diagram) touches window — keep client-only.
const Canvas = dynamic(
  () => import("@/components/model/Canvas").then((m) => m.Canvas),
  { ssr: false, loading: () => (
    <div className="flex flex-1 items-center justify-center text-[13px] text-subtle">
      Loading schema diagram…
    </div>
  ) },
);

type Tab = "lightweight" | "diagram" | "rules" | "versions" | "publish" | "import";

const TABS: Array<{ id: Tab; label: string; emoji: string }> = [
  { id: "lightweight", label: "Lightweight",    emoji: "🟦" },
  { id: "diagram",     label: "Schema Diagram", emoji: "🖼" },
  { id: "rules",       label: "Rules",          emoji: "🟪" },
  { id: "versions",    label: "Versions",       emoji: "🟪" },
  { id: "publish",     label: "Publish",        emoji: "📤" },
  { id: "import",      label: "Import",         emoji: "📥" },
];

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

      {/* Tab bar */}
      <div className="border-b border-navy-100 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-end gap-0 px-6">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={cn(
                "inline-flex items-center gap-1.5 border-b-2 px-4 py-3 text-[13px] font-medium transition-colors",
                tab === t.id
                  ? "border-steel-500 text-steel-700"
                  : "border-transparent text-navy-500 hover:text-navy-800",
              )}
            >
              <span>{t.emoji}</span>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Lifecycle summary (collapsed hint) */}
      {!isDiagram && (
        <div className="border-b border-navy-50 bg-navy-50/40 px-6 py-2 text-[11px] text-navy-500">
          Brief → Ingest →
          <span className="font-semibold text-steel-600"> 🟦 Lightweight</span> →
          HITL review →
          <span className="font-semibold text-purple-600"> 🟪 Heavyweight (Rules + Versions)</span> →
          <span className="font-semibold text-emerald-600"> 📤 Publish</span>
        </div>
      )}

      {/* Tab content */}
      {isDiagram ? (
        <Canvas key={diagramKey} />
      ) : (
        <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-6">
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
  );
}
