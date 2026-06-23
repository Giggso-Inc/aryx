"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import {
  Activity, AlertCircle, BookOpen, CheckCircle2, ChevronDown, ChevronLeft,
  Database, FileText, Home, Loader2, MessageCircle, Network, Pencil,
  Plus, RotateCcw, Settings, Share2, Sparkles, Trash2, Upload,
} from "lucide-react";
import { Logo } from "./Logo";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import { cn } from "@/lib/cn";
import { HITLBadge } from "@/components/hitl/HITLBadge";
import { JobsBadge } from "@/components/jobs/JobsBadge";

interface HeaderProps {
  workspaceId?: number;
  onWorkspaceChange?: (id: number) => void;
}

export function Header(props: HeaderProps) {
  const ws = useWorkspace();
  const router = useRouter();
  const workspaceId = props.workspaceId ?? ws.workspaceId;
  const setWorkspace = props.onWorkspaceChange ?? ws.setWorkspaceId;

  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const active = ws.workspaces.find((w) => w.id === workspaceId)
    || ws.workspaces[0];

  const onWizard = pathname?.startsWith("/start") || false;
  const showBell = !onWizard && !!active;

  return (
    <header className="sticky top-0 z-20 border-b border-navy-100/80 bg-canvas/85">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
        <div className="flex items-center gap-8">
          <Link href="/" className="focus-ring rounded-md">
            <Logo size={34} withWordmark />
          </Link>
          <nav className="flex items-center gap-1">
            <NavLink href="/home" icon={<Home size={14} />} label="Home"
                      active={pathname === "/home"} />
            <NavLink href="/brief" icon={<FileText size={14} />} label="Brief"
                      active={pathname?.startsWith("/brief") || false} />
            <NavLink href="/ingest" icon={<Upload size={14} />} label="Ingest"
                      active={pathname?.startsWith("/ingest") || false} />
            <NavLink href="/" icon={<MessageCircle size={14} />} label="Ask"
                      active={pathname === "/"} />
            <NavLink href="/graph" icon={<Share2 size={14} />} label="Graph"
                      active={pathname?.startsWith("/graph") || false} />
            <NavLink href="/model" icon={<BookOpen size={14} />} label="Ontology"
                      active={pathname?.startsWith("/model") || false} />
            <NavLink href="/observability" icon={<Activity size={14} />} label="Observability"
                      active={pathname?.startsWith("/observability") || false} />
            <NavLink href="/settings" icon={<Settings size={14} />} label="Settings"
                      active={pathname?.startsWith("/settings") || false} />
            <NavLink href="/data" icon={<Database size={14} />} label="Data"
                      active={pathname?.startsWith("/data") || false} />
            <NavLink href="/start" icon={<Sparkles size={14} />} label="Onboard"
                      active={pathname?.startsWith("/start") || false} />
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <JobsBadge />
          {showBell && <HITLBadge />}
          <WorkspacePicker
            workspaces={ws.workspaces}
            activeId={workspaceId}
            activeName={active?.name}
            activeContext={active?.context}
            open={open}
            onToggle={() => { if (open) setOpen(false); else setOpen(true); }}
            onSelect={(id) => {
              setWorkspace(id);
              setOpen(false);
              if (pathname?.startsWith("/start")) router.push("/");
            }}
            onCreated={async (id) => {
              await ws.refresh();
              setWorkspace(id);
              setOpen(false);
              router.push("/start");
            }}
            onRefresh={async () => {
              await ws.refresh();
            }}
            onDeleted={async () => {
              await ws.refresh();
              setWorkspace(1);
              setOpen(false);
            }}
          />
        </div>
      </div>
    </header>
  );
}

interface PickerProps {
  workspaces: { id: number; name: string; context?: string }[];
  activeId: number;
  activeName?: string;
  activeContext?: string;
  open: boolean;
  onToggle: () => void;
  onSelect: (id: number) => void;
  onCreated: (id: number) => void;
  onRefresh: () => Promise<void>;
  onDeleted: () => Promise<void>;
}

function WorkspacePicker({
  workspaces, activeId, activeName, activeContext, open, onToggle,
  onSelect, onCreated, onRefresh, onDeleted,
}: PickerProps) {
  const [mode, setMode] = useState<"list" | "create" | "manage">("list");

  // create form
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [ctx, setCtx] = useState("");

  // manage form
  const [manageCtx, setManageCtx] = useState("");
  const [saving, setSaving] = useState(false);
  const [purging, setPurging] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reset = () => {
    setMode("list");
    setName(""); setDesc(""); setCtx("");
    setManageCtx("");
    setError(null); setNotice(null);
  };

  const openManage = () => {
    setManageCtx(activeContext ?? "");
    setError(null); setNotice(null);
    setMode("manage");
  };

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true); setError(null);
    try {
      const w = await api.createWorkspace(name.trim(), desc.trim(), ctx.trim());
      onCreated(w.id);
      reset();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    } finally {
      setBusy(false);
    }
  };

  const saveContext = async () => {
    setSaving(true); setError(null); setNotice(null);
    try {
      await api.updateWorkspaceContext(activeId, manageCtx);
      await onRefresh();
      setNotice("Business context saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const purgeData = async () => {
    if (!confirm(`Purge all data from "${activeName}"? Entities and graph will be deleted.`)) return;
    setPurging(true); setError(null); setNotice(null);
    try {
      await api.purgeWorkspace(activeId);
      await onRefresh();
      setNotice("Workspace data purged.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Purge failed");
    } finally {
      setPurging(false);
    }
  };

  const deleteWs = async () => {
    if (activeId === 1) return;
    if (!confirm(`Delete workspace "${activeName}" permanently? This cannot be undone.`)) return;
    setDeleting(true); setError(null);
    try {
      await api.deleteWorkspace(activeId);
      await onDeleted();
      reset();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
      setDeleting(false);
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => { if (open) reset(); onToggle(); }}
        className="focus-ring inline-flex items-center gap-2 rounded-full border border-navy-100 bg-white px-4 py-2 text-sm font-medium text-navy-700 hover:border-navy-200 hover:bg-navy-50"
      >
        <span className="inline-block size-2 rounded-full bg-steel-500" />
        <span>{activeName || "Default"}</span>
        <ChevronDown size={14} className="text-subtle" />
      </button>

      {open && (
        <div className="absolute right-0 top-12 w-80 overflow-hidden rounded-xl border border-navy-100 bg-white shadow-soft animate-rise">

          {/* ── List mode ─────────────────────────────────── */}
          {mode === "list" && (
            <>
              <ul>
                {workspaces.map((w) => (
                  <li key={w.id}>
                    <button
                      type="button"
                      onClick={() => onSelect(w.id)}
                      className="flex w-full items-center justify-between px-4 py-2.5 text-left text-sm hover:bg-navy-50"
                    >
                      <span className="text-navy-800">{w.name}</span>
                      {w.id === activeId && (
                        <span className="size-1.5 rounded-full bg-steel-500" />
                      )}
                    </button>
                  </li>
                ))}
              </ul>
              <div className="border-t border-navy-100">
                <button
                  type="button"
                  onClick={openManage}
                  className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[13px] font-medium text-navy-600 hover:bg-navy-50"
                >
                  <Pencil size={13} /> Manage "{activeName}"…
                </button>
                <button
                  type="button"
                  onClick={() => setMode("create")}
                  className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[13px] font-medium text-steel-600 hover:bg-navy-50"
                >
                  <Plus size={13} /> New workspace…
                </button>
              </div>
            </>
          )}

          {/* ── Create mode ───────────────────────────────── */}
          {mode === "create" && (
            <div className="space-y-3 p-4">
              <button
                type="button"
                onClick={reset}
                className="mb-1 inline-flex items-center gap-1 text-[11px] text-navy-500 hover:text-navy-800"
              >
                <ChevronLeft size={11} /> Back
              </button>
              <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-navy-700">
                Create a workspace
              </div>
              <input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
                placeholder="Name (e.g. Sales Pipeline)"
                className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[13px] text-navy-800 focus:border-steel-500"
              />
              <input
                value={desc}
                onChange={(e) => setDesc(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
                placeholder="What it's for (optional)"
                className="focus-ring w-full rounded-lg border border-navy-100 bg-white px-3 py-2 text-[12px] text-navy-800 focus:border-steel-500"
              />
              <textarea
                value={ctx}
                onChange={(e) => setCtx(e.target.value)}
                rows={3}
                placeholder="Business context — industry, domain, use case (optional)"
                className="focus-ring w-full resize-none rounded-lg border border-navy-100 bg-white px-3 py-2 text-[12px] text-navy-800 focus:border-steel-500"
              />
              {error && (
                <div className="rounded-md border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-[11px] text-rose-700">
                  {error}
                </div>
              )}
              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={reset}
                  className="focus-ring rounded-lg px-2.5 py-1.5 text-[12px] font-medium text-navy-700 hover:bg-navy-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={submit}
                  disabled={!name.trim() || busy}
                  className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
                >
                  {busy ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                  Create &amp; open setup
                </button>
              </div>
            </div>
          )}

          {/* ── Manage mode ───────────────────────────────── */}
          {mode === "manage" && (
            <div className="space-y-3 p-4">
              <button
                type="button"
                onClick={reset}
                className="mb-1 inline-flex items-center gap-1 text-[11px] text-navy-500 hover:text-navy-800"
              >
                <ChevronLeft size={11} /> Back
              </button>
              <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-navy-700">
                Manage — {activeName}
              </div>

              {error && (
                <div className="flex items-center gap-1.5 rounded-md border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-[11px] text-rose-700">
                  <AlertCircle size={11} /> {error}
                </div>
              )}
              {notice && (
                <div className="flex items-center gap-1.5 rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-[11px] text-emerald-700">
                  <CheckCircle2 size={11} /> {notice}
                </div>
              )}

              {/* Business context */}
              <div>
                <label className="mb-1 block text-[11px] font-medium text-navy-600">
                  Business context
                </label>
                <textarea
                  value={manageCtx}
                  onChange={(e) => setManageCtx(e.target.value)}
                  rows={3}
                  placeholder="Industry, domain, use case — helps the AI understand the data"
                  className="focus-ring w-full resize-none rounded-lg border border-navy-100 bg-white px-3 py-2 text-[12px] text-navy-800 focus:border-steel-500"
                />
                <button
                  type="button"
                  onClick={saveContext}
                  disabled={saving}
                  className="focus-ring mt-1.5 inline-flex items-center gap-1.5 rounded-lg bg-navy-800 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
                >
                  {saving ? <Loader2 size={11} className="animate-spin" /> : null}
                  Save context
                </button>
              </div>

              {/* Purge data */}
              <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-3">
                <p className="mb-2 text-[11px] text-amber-800">
                  <strong>Purge data</strong> — deletes entities, relationships and embeddings. Workspace is kept.
                </p>
                <button
                  type="button"
                  onClick={purgeData}
                  disabled={purging}
                  className="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-[12px] font-semibold text-amber-800 hover:bg-amber-50 disabled:opacity-50"
                >
                  {purging ? <Loader2 size={11} className="animate-spin" /> : <RotateCcw size={11} />}
                  Purge "{activeName}"
                </button>
              </div>

              {/* Delete workspace */}
              {activeId !== 1 && (
                <div className="rounded-lg border border-rose-200 bg-rose-50/50 p-3">
                  <p className="mb-2 text-[11px] text-rose-800">
                    <strong>Delete workspace</strong> — permanently removes this workspace and all its data.
                  </p>
                  <button
                    type="button"
                    onClick={deleteWs}
                    disabled={deleting}
                    className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-rose-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
                  >
                    {deleting ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
                    Delete workspace
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function NavLink({
  href, icon, label, active,
}: { href: string; icon: React.ReactNode; label: string; active: boolean }) {
  return (
    <Link
      href={href}
      className={cn(
        "focus-ring inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors",
        active ? "bg-navy-800 text-white"
                : "text-navy-600 hover:bg-navy-50 hover:text-navy-900",
      )}
    >
      {icon}
      {label}
    </Link>
  );
}
