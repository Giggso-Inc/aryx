"use client";

import {
  createContext, useCallback, useContext, useEffect, useState, type ReactNode,
} from "react";
import { api } from "./api";
import { useShayAuth } from "./shay-auth";
import type { Workspace } from "./types";

interface WorkspaceContext {
  ready: boolean;
  workspaceId: number;
  workspaces: Workspace[];
  setWorkspaceId: (id: number) => void;
  refresh: () => Promise<void>;
  updateWorkspaceBrief: (id: number, brief: Record<string, unknown>) => void;
}

const Ctx = createContext<WorkspaceContext | null>(null);

const STORAGE_KEY = "aryx.workspaceId";

/** Shared workspace selection across Ask, Model, and any future surface.
 *  First-time visitors land on the workspace named "Default" (typically the
 *  empty onboarding one), so the auto-redirect on / bounces them to /start.
 *  Returning users stay on whatever they last selected (localStorage). */
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { ready, session } = useShayAuth();
  const [workspaceId, setWorkspaceIdState] = useState(0);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);

  const refresh = useCallback(async () => {
    if (!session?.access_token) {
      setWorkspaces([]);
      return;
    }
    try {
      const list = await api.listWorkspaces();
      setWorkspaces(list);
    } catch {
      // Keep existing workspaces on transient error — don't blank the UI
    }
  }, [session?.access_token]);

  const updateWorkspaceBrief = useCallback((id: number, brief: Record<string, unknown>) => {
    setWorkspaces(prev => prev.map(w => w.id === id ? { ...w, brief } : w));
  }, []);

  useEffect(() => {
    if (!ready || !session?.access_token) {
      setWorkspaceIdState(0);
      setWorkspaces([]);
      return;
    }
    api.listWorkspaces().then((list) => {
      setWorkspaces(list);
      if (list.length === 0) {
        setWorkspaceIdState(0);
        if (typeof window !== "undefined") {
          localStorage.removeItem(STORAGE_KEY);
        }
        return;
      }
      const stored = typeof window !== "undefined"
        ? localStorage.getItem(STORAGE_KEY) : null;
      if (stored) {
        const id = Number(stored);
        if (list.some((w) => w.id === id)) {
          setWorkspaceIdState(id);
          return;
        }
      }
      // First visit (or stale id): prefer the workspace literally named
      // "Default" so onboarding/test users get the wizard. Fall back to
      // first workspace, then id=1.
      const def = list.find((w) => w.name === "Default") || list[0];
      if (def) setWorkspaceIdState(def.id);
    }).catch(() => {
      // Keep existing state on transient error — don't redirect to /start
    });
  }, [ready, session?.access_token]);

  const setWorkspaceId = (id: number) => {
    setWorkspaceIdState(Number(id));
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, String(id));
    }
  };

  return (
    <Ctx.Provider value={{ ready, workspaceId, workspaces, setWorkspaceId, refresh, updateWorkspaceBrief }}>
      {children}
    </Ctx.Provider>
  );
}

export function useWorkspace() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useWorkspace must be inside <WorkspaceProvider>");
  return v;
}
