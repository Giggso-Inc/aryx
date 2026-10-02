"use client";

import { useEffect, useState } from "react";
import { Clock, Database, FileText, Globe } from "lucide-react";
import { Header } from "@/components/brand/Header";
import { useWorkspace } from "@/lib/workspace";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";
import { DatabaseTab } from "@/components/ingest/DatabaseTab";
import { DocsTab } from "@/components/ingest/DocsTab";
import { RestTab } from "@/components/ingest/RestTab";
import type { DiscoveryHistoryItem } from "@/lib/types";

type Tab = "database" | "docs" | "rest";

const TABS = [
  { id: "database" as Tab, label: "Database",  icon: <Database size={14} /> },
  { id: "docs"     as Tab, label: "Documents", icon: <FileText size={14} /> },
  { id: "rest"     as Tab, label: "REST API",  icon: <Globe size={14} /> },
];

// Rows this banner shows: anything not yet confirmed, and not a confirm
// already in flight (that has its own job-progress UI once you switch to
// the Documents tab). Shared so the initial fetch and the dismiss-failure
// refetch can't drift apart on what counts as "still pending".
const isPendingDiscovery = (item: DiscoveryHistoryItem) =>
  item.status !== "confirmed" && item.status !== "confirming";

export default function IngestPage() {
  const { workspaceId, setWorkspaceId } = useWorkspace();
  const [tab, setTab] = useState<Tab>("database");
  const [pendingItems, setPendingItems] = useState<DiscoveryHistoryItem[]>([]);
  const [restoreId, setRestoreId] = useState<string | null>(null);
  const [restartFlag, setRestartFlag] = useState(false);

  useEffect(() => {
    api.listDiscoveries(workspaceId)
      .then((items) => setPendingItems(items.filter(isPendingDiscovery)))
      .catch(() => {});
  }, [workspaceId]);

  const handleConfirm = (id: string) => {
    setRestartFlag(false);
    setRestoreId(id);
    setPendingItems((prev) => prev.filter((i) => i.discovery_id !== id));
    setTab("docs");
  };

  const handleDismiss = (id: string) => {
    if (!window.confirm("Dismiss this discovery? This can't be undone.")) return;
    // Optimistic removal -- a dismiss failing (e.g. its read job is still
    // running, or a confirm job started for it moments ago in another tab)
    // is rare enough that re-fetching the list on error is simpler than
    // reconciling a partial rollback.
    setPendingItems((prev) => prev.filter((i) => i.discovery_id !== id));
    api.dismissDiscovery(id, workspaceId).catch((e) => {
      // Without this the row just silently reappears on refetch with no
      // explanation -- surface the backend's actual reason (e.g. "cannot
      // dismiss a discovery while its read job is still running").
      window.alert(e instanceof Error ? e.message : "Dismiss failed");
      api.listDiscoveries(workspaceId)
        .then((items) => setPendingItems(items.filter(isPendingDiscovery)))
        .catch(() => {});
    });
  };

  const handleAction = (id: string, restart: boolean) => {
    setRestartFlag(restart);
    setRestoreId(id);
    setPendingItems((prev) => prev.filter((i) => i.discovery_id !== id));
    setTab("docs");
  };

  const handleRestored = () => {
    const id = restoreId;
    setRestoreId(null);
    setRestartFlag(false);
    setPendingItems((prev) => prev.filter((i) => i.discovery_id !== id));
  };

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

          {pendingItems.length > 0 && (
            <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
              <p className="mb-2 text-[12px] font-semibold text-amber-800">
                {pendingItems.length === 1
                  ? "1 document discovery is waiting to be confirmed"
                  : `${pendingItems.length} document discoveries are waiting to be confirmed`}
              </p>
              <div className="max-h-[160px] overflow-y-auto space-y-1.5 pr-1">
                {pendingItems.map((item) => (
                  <div key={item.discovery_id} className="flex items-center gap-3 text-[12px]">
                    <Clock size={11} className="text-amber-600 shrink-0" />
                    <span className="flex-1 truncate text-amber-900">
                      {Array.from(new Set(item.summary?.files?.map((f) => f.source_filename ?? f.filename)))
                        .join(", ") || `${item.file_count} file(s)`}
                    </span>
                    <span className="text-amber-700 whitespace-nowrap shrink-0">
                      {item.status === "partial" ? "partially confirmed" : "pending"}
                    </span>
                    {item.status === "partial" ? (
                      <span className="flex gap-1.5 shrink-0">
                        <button
                          type="button"
                          onClick={() => handleAction(item.discovery_id, false)}
                          className="rounded-md bg-amber-700 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-amber-800 whitespace-nowrap">
                          Resume
                        </button>
                        <button
                          type="button"
                          onClick={() => handleAction(item.discovery_id, true)}
                          className="rounded-md border border-amber-700 px-2.5 py-1 text-[11px] font-medium text-amber-800 hover:bg-amber-100 whitespace-nowrap">
                          Restart
                        </button>
                      </span>
                    ) : (
                      <span className="flex gap-1.5 shrink-0">
                        <button
                          type="button"
                          onClick={() => handleConfirm(item.discovery_id)}
                          className="rounded-md bg-amber-700 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-amber-800 whitespace-nowrap">
                          Confirm
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDismiss(item.discovery_id)}
                          className="rounded-md border border-amber-700 px-2.5 py-1 text-[11px] font-medium text-amber-800 hover:bg-amber-100 whitespace-nowrap">
                          Dismiss
                        </button>
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

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
          {tab === "docs" && <DocsTab restoreId={restoreId} restart={restartFlag} onRestored={handleRestored} />}
          {tab === "rest" && <RestTab />}
        </main>
      </div>
    </div>
  );
}
