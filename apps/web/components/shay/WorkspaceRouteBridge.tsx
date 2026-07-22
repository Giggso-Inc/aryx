"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import { useWorkspace } from "@/lib/workspace";

interface WorkspaceRouteError {
  workspaceId: string;
  message: string;
}

export function WorkspaceRouteBridge({
  shayWorkspaceId,
  children,
}: {
  shayWorkspaceId: string;
  children: React.ReactNode;
}) {
  const { session } = useShayAuth();
  const { setWorkspaceId } = useWorkspace();
  const readyWorkspaceIdRef = useRef<string | null>(null);
  const [readyWorkspaceId, setReadyWorkspaceId] = useState<string | null>(null);
  const [error, setError] = useState<WorkspaceRouteError | null>(null);

  useEffect(() => {
    if (!session?.access_token) {
      return;
    }

    let active = true;
    const isWorkspaceChange = readyWorkspaceIdRef.current !== shayWorkspaceId;

    const syncWorkspace = async () => {
      if (isWorkspaceChange) {
        setError(null);
      }
      try {
        const workspace = await shayApi.getWorkspace(
          shayWorkspaceId,
          session.access_token,
        );
        const bridge = workspace.bridge;
        if (!bridge) {
          throw new Error("Workspace bridge is not ready yet.");
        }
        if (!active) {
          return;
        }
        setWorkspaceId(bridge.aryx_workspace_id);
        readyWorkspaceIdRef.current = shayWorkspaceId;
        setReadyWorkspaceId(shayWorkspaceId);
      } catch (nextError: unknown) {
        if (!active) {
          return;
        }
        if (isWorkspaceChange) {
          setError({
            workspaceId: shayWorkspaceId,
            message: nextError instanceof Error
              ? nextError.message
              : "Unable to open this workspace.",
          });
        }
      }
    };

    void syncWorkspace();

    return () => {
      active = false;
    };
  }, [session?.access_token, setWorkspaceId, shayWorkspaceId]);

  const errorMessage = error?.workspaceId === shayWorkspaceId
    ? error.message
    : null;
  const ready = readyWorkspaceId === shayWorkspaceId;

  if (errorMessage) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center px-6 py-10">
        <div className="rounded-[2rem] border border-rose-200 bg-white px-6 py-8 text-center shadow-soft">
          <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-rose-50 text-rose-600">
            <AlertCircle size={20} />
          </div>
          <h1 className="mt-4 font-display text-2xl text-navy-900">
            Workspace unavailable
          </h1>
          <p className="mt-2 max-w-md text-sm text-subtle">{errorMessage}</p>
        </div>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center px-6 py-10">
        <div className="rounded-[2rem] border border-navy-100 bg-white px-6 py-8 text-center shadow-soft">
          <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-navy-50 text-navy-700">
            <Loader2 size={20} className="animate-spin" />
          </div>
          <h1 className="mt-4 font-display text-2xl text-navy-900">
            Opening workspace
          </h1>
          <p className="mt-2 max-w-md text-sm text-subtle">
            We’re syncing the Aryx runtime for this workspace now.
          </p>
        </div>
      </div>
    );
  }

  return <div data-workspace-detail-route="true">{children}</div>;
}
