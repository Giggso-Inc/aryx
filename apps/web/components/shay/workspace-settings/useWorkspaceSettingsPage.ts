/**
 * State + mutation logic for WorkspaceSettingsPage.
 *
 * Composes useWorkspaceSettingsState.ts (state, loading, derived
 * values) and useWorkspaceSettingsActions.ts (write-path mutations)
 * into the single interface WorkspaceSettingsPage.tsx renders from
 * (2026-09; Raven Style Compliance Plan Phase 8b line-count reduction).
 */

import { useWorkspaceSettingsState } from "./useWorkspaceSettingsState";
import { useWorkspaceSettingsActions } from "./useWorkspaceSettingsActions";

export function useWorkspaceSettingsPage(workspaceId: string) {
  const state = useWorkspaceSettingsState(workspaceId);
  const actions = useWorkspaceSettingsActions(state);

  return { ...state, ...actions };
}
