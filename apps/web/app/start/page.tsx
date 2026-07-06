"use client";

import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useWorkspace } from "@/lib/workspace";
import { parseWorkspaceScope, workspaceModelHref, workspaceSectionHref } from "@/lib/workspace-route";
import type { Brief } from "@/lib/types";
import { Intro } from "@/components/start/Intro";
import { Goals } from "@/components/start/Goals";
import { Confirm } from "@/components/start/Confirm";
import { Sources, type SourceKind } from "@/components/start/Sources";
import { Connect } from "@/components/start/Connect";
import { Files } from "@/components/start/Files";
import { Running } from "@/components/start/Running";
import { Done } from "@/components/start/Done";

type Step =
  | "intro" | "goals" | "confirm" | "sources" | "connect" | "files"
  | "running" | "done";

/** Guided setup state machine. Loops through every picked source kind:
 *  Database → Connect, Files → Files upload step. Manual is informational
 *  for now (Inspector on /model handles manual type creation). */
export default function StartWizard() {
  const router = useRouter();
  const pathname = usePathname();
  const { ready, workspaceId, workspaces } = useWorkspace();
  const { shayWorkspaceId } = parseWorkspaceScope(pathname);

  const [step, setStep] = useState<Step>("intro");
  const [brief, setBrief] = useState<Brief>({});
  const [sources, setSources] = useState<SourceKind[]>(["database"]);
  const [jobId, setJobId] = useState<string | null>(null);
  const hasWorkspace = ready && workspaceId > 0 && workspaces.length > 0;
  const briefHref = hasWorkspace
    ? (shayWorkspaceId ? workspaceSectionHref(shayWorkspaceId, "brief") : "/workspaces")
    : "/workspaces";

  /** After a source completes, advance through any remaining picked
   *  sources before flipping to "running". */
  const nextSource = (completed: SourceKind) => {
    const remaining = sources.filter((s) => s !== completed);
    setSources(remaining);
    if (remaining.includes("database")) setStep("connect");
    else if (remaining.includes("files")) setStep("files");
    else setStep("running");
  };

  return (
    <>
      {step === "intro" && <Intro onStart={() => router.push(briefHref)} />}

      {ready && !hasWorkspace && (
        <div className="mx-auto mt-6 max-w-xl rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          You need a workspace before onboarding can continue. Create or select one from Workspaces first.
        </div>
      )}

      {step === "goals" && hasWorkspace && (
        <Goals
          workspaceId={workspaceId}
          onDrafted={(b) => { setBrief(b); setStep("confirm"); }}
          onSkip={() => setStep("sources")}
        />
      )}

      {step === "confirm" && hasWorkspace && (
        <Confirm
          workspaceId={workspaceId}
          brief={brief}
          onConfirm={() => setStep("sources")}
          onBack={() => setStep("goals")}
        />
      )}

      {step === "sources" && hasWorkspace && (
        <Sources
          initial={sources}
          onContinue={(picked) => {
            setSources(picked);
            if (picked.includes("database")) setStep("connect");
            else if (picked.includes("files")) setStep("files");
            else setStep("running");
          }}
          onBack={() => setStep("confirm")}
        />
      )}

      {step === "connect" && hasWorkspace && (
        <Connect
          workspaceId={workspaceId}
          kind="postgres"
          onConnected={() => nextSource("database")}
          onBack={() => setStep("sources")}
        />
      )}

      {step === "files" && hasWorkspace && (
        <Files
          workspaceId={workspaceId}
          onUploaded={(id) => { setJobId(id); nextSource("files"); }}
          onBack={() => setStep("sources")}
          onSkip={() => nextSource("files")}
        />
      )}

      {step === "running" && hasWorkspace && (
        <Running
          workspaceId={workspaceId}
          jobId={jobId}
          onDone={() => setStep("done")}
          onSkip={() => router.push(shayWorkspaceId ? workspaceModelHref(shayWorkspaceId) : "/model")}
        />
      )}

      {step === "done" && hasWorkspace && <Done workspaceId={workspaceId} />}
    </>
  );
}
