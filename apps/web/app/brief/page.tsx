"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AlertCircle, CheckCircle2, FileText } from "lucide-react";
import { Header } from "@/components/brand/Header";
import { api } from "@/lib/api";
import { parseWorkspaceScope, workspaceStartHref } from "@/lib/workspace-route";
import { useWorkspace } from "@/lib/workspace";
import type { Brief } from "@/lib/types";
import { BriefFieldsForm } from "./BriefFieldsForm";
import { BriefSummary } from "./BriefSummary";
import { DraftSeedCard } from "./DraftSeedCard";

export default function BriefPage() {
  const { ready, workspaceId, workspaces, setWorkspaceId } = useWorkspace();
  const router = useRouter();
  const pathname = usePathname();
  const { shayWorkspaceId } = parseWorkspaceScope(pathname);
  const [domain, setDomain] = useState("");
  const [aim, setAim] = useState("");
  const [objectives, setObjectives] = useState("");
  const [scope, setScope] = useState("");
  const [roles, setRoles] = useState("");

  const [seed, setSeed] = useState("");
  const [briefLoading, setBriefLoading] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch brief directly from API on page visit or workspace switch.
  useEffect(() => {
    if (!workspaceId || workspaceId <= 0) return;
    setBriefLoading(true);
    api.listWorkspaces().then((list) => {
      const ws = list.find((w) => w.id === Number(workspaceId));
      const b = (ws?.brief ?? {}) as Partial<Brief>;
      setDomain(b.domain ?? "");
      setAim(b.aim ?? "");
      setObjectives((b.objectives ?? []).join("\n"));
      setScope(b.scope ?? "");
      setRoles((b.roles ?? []).join("\n"));
    }).finally(() => setBriefLoading(false));
  }, [workspaceId, pathname]);

  useEffect(() => {
    if (ready && (workspaceId <= 0 || workspaces.length === 0)) {
      router.replace(shayWorkspaceId ? workspaceStartHref(shayWorkspaceId) : "/start");
    }
  }, [ready, router, shayWorkspaceId, workspaceId, workspaces.length]);

  const filledCount = [domain, aim, objectives, scope, roles].filter(
    (v) => v.trim().length > 0,
  ).length;

  const draftBrief = async () => {
    if (!seed.trim()) return;
    setDrafting(true); setError(null); setResult(null);
    try {
      const res = await api.draftBrief(workspaceId, seed);
      const b = res.brief as Partial<Brief>;
      setDomain(b.domain ?? "");
      setAim(b.aim ?? "");
      setObjectives((b.objectives ?? []).join("\n"));
      setScope(b.scope ?? "");
      setRoles((b.roles ?? []).join("\n"));
      setResult("Brief drafted — review and save below.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Draft failed");
    } finally {
      setDrafting(false);
    }
  };

  const saveBrief = async () => {
    setSaving(true); setError(null); setResult(null);
    try {
      const brief: Brief = {
        domain: domain.trim(),
        aim: aim.trim(),
        objectives: objectives.split("\n").map((l) => l.trim()).filter(Boolean),
        scope: scope.trim(),
        roles: roles.split("\n").map((l) => l.trim()).filter(Boolean),
      };
      await api.saveBrief(workspaceId, brief);
      setResult("Brief saved — Aryx will use it for extraction.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col">
      <Header workspaceId={workspaceId} onWorkspaceChange={setWorkspaceId} />
      <div className="app-shell-offset flex-1">
        <main className="workspace-section-shell pb-6 pt-6">
        <div className="mb-6 flex items-center gap-2">
          <FileText size={20} className="text-steel-600" />
          <div>
            <h1 className="font-display text-2xl font-bold text-navy-900">Brief</h1>
            <p className="text-[13px] text-subtle">
              Five questions that ground every extraction. Skip any field and Aryx ingests generically.
            </p>
          </div>
        </div>

        {error && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
            <AlertCircle size={13} /> {error}
          </div>
        )}
        {result && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] text-emerald-700">
            <CheckCircle2 size={13} /> {result}
          </div>
        )}

        <DraftSeedCard
          seed={seed}
          drafting={drafting}
          onSeedChange={setSeed}
          onDraft={draftBrief}
        />

        <BriefFieldsForm
          loading={briefLoading}
          domain={domain}
          aim={aim}
          objectives={objectives}
          scope={scope}
          roles={roles}
          saving={saving}
          filledCount={filledCount}
          onDomainChange={setDomain}
          onAimChange={setAim}
          onObjectivesChange={setObjectives}
          onScopeChange={setScope}
          onRolesChange={setRoles}
          onSave={saveBrief}
        />

        {!briefLoading && filledCount > 0 && (
          <BriefSummary domain={domain} aim={aim} scope={scope} objectives={objectives} roles={roles} />
        )}
        </main>
      </div>
    </div>
  );
}
