"use client";

import { useState } from "react";
import { Database, FileText, Globe } from "lucide-react";
import { Header } from "@/components/brand/Header";
import { useWorkspace } from "@/lib/workspace";
import { cn } from "@/lib/cn";
import { DatabaseTab } from "@/components/ingest/DatabaseTab";
import { DocsTab } from "@/components/ingest/DocsTab";
import { RestTab } from "@/components/ingest/RestTab";

type Tab = "database" | "docs" | "rest";

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "database", label: "Database", icon: <Database size={14} /> },
  { id: "docs", label: "Documents", icon: <FileText size={14} /> },
  { id: "rest", label: "REST", icon: <Globe size={14} /> },
];

export default function IngestPage() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  // Documents is the only fully-functional tab this round, so it's the
  // default landing spot.
  const [tab, setTab] = useState<Tab>("docs");

  return (
    <div className="flex min-h-screen flex-col">
      <Header workspaceId={workspaceId} onWorkspaceChange={setWorkspaceId} />
      <main className="flex-1">
        <div className="mx-auto flex max-w-7xl flex-col items-center pt-8">
          <div className="inline-flex rounded-full border border-navy-100 bg-white p-1 shadow-soft">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={cn(
                  "focus-ring inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors",
                  tab === t.id
                    ? "bg-navy-800 text-white"
                    : "text-navy-600 hover:bg-navy-50 hover:text-navy-900",
                )}
              >
                {t.icon}
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {tab === "database" && <DatabaseTab />}
        {tab === "docs" && <DocsTab />}
        {tab === "rest" && <RestTab />}
      </main>
    </div>
  );
}
