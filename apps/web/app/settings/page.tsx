"use client";

import { useState } from "react";
import { Cpu, Globe, KeyRound, Shield } from "lucide-react";
import { Header } from "@/components/brand/Header";
import { useWorkspace } from "@/lib/workspace";
import { cn } from "@/lib/cn";
import { DangerTab } from "./_components/DangerTab";
import { LlmTab } from "./_components/LlmTab";
import { McpTab } from "./_components/McpTab";
import { OntologyTab } from "./_components/OntologyTab";

type Tab = "llm" | "mcp" | "ontology" | "danger";

export default function SettingsPage() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  const [tab, setTab] = useState<Tab>("mcp");

  const tabs: Array<{ id: Tab; label: string; icon: React.ReactNode }> = [
    { id: "llm",      label: "LLM Config",   icon: <Cpu size={14} /> },
    { id: "mcp",      label: "MCP Tokens",   icon: <KeyRound size={14} /> },
    { id: "ontology", label: "Ontology",      icon: <Globe size={14} /> },
    { id: "danger",   label: "Danger Zone",   icon: <Shield size={14} /> },
  ];

  return (
    <div className="flex min-h-screen flex-col">
      <Header workspaceId={workspaceId} onWorkspaceChange={setWorkspaceId} />

      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-8">
        <section className="overflow-hidden rounded-[1.5rem] border border-navy-100 bg-white shadow-soft">
          <div className="border-b border-navy-100 bg-white">
            <div className="flex flex-wrap items-end gap-0 px-5">
              {tabs.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTab(t.id)}
                  className={cn(
                    "inline-flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors",
                    tab === t.id
                      ? "border-navy-800 text-navy-900"
                      : "border-transparent text-navy-500 hover:text-navy-800",
                  )}
                >
                  {t.icon}
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          <div className="px-5 py-5">
            {tab === "llm" && <LlmTab />}
            {tab === "mcp" && <McpTab />}
            {tab === "ontology" && <OntologyTab />}
            {tab === "danger" && <DangerTab />}
          </div>
        </section>
      </main>
    </div>
  );
}
