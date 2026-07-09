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

const TABS = [
  { id: "database" as Tab, label: "Database",  icon: <Database size={14} /> },
  { id: "docs"     as Tab, label: "Documents", icon: <FileText size={14} /> },
  { id: "rest"     as Tab, label: "REST API",  icon: <Globe size={14} /> },
];

export default function IngestPage() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  const [tab, setTab] = useState<Tab>("database");

  return (
    <div className="flex min-h-screen flex-col">
      <Header workspaceId={workspaceId} onWorkspaceChange={setWorkspaceId} />
      <div className="app-shell-offset flex-1">
        <main className="workspace-section-shell pb-6 pt-6">
          <div className="mb-6">
            <h1 className="font-display text-2xl font-bold text-navy-900">Ingest</h1>
            <p className="mt-0.5 text-[13px] text-subtle">
              Add data to your knowledge graph — database, documents or REST APIs
            </p>
          </div>

          <div className="mb-6 flex gap-0.5 rounded-xl bg-navy-50 p-1">
            {TABS.map((t) => (
              <button key={t.id} type="button" onClick={() => setTab(t.id)}
                className={cn(
                  "focus-ring flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-all",
                  tab === t.id ? "bg-white text-navy-900 shadow-soft" : "text-navy-600 hover:text-navy-900",
                )}>
                {t.icon}
                {t.label}
              </button>
            ))}
          </div>

          {tab === "database" && <DatabaseTab />}
          {tab === "docs" && <DocsTab />}
          {tab === "rest" && <RestTab />}
        </main>
      </div>
    </div>
  );
}
