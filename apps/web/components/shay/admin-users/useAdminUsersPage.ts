/**
 * State + data-loading + mutation logic for AdminUsersPage.
 *
 * Composes useAdminUsersState.ts (state, loading, filters) and
 * useAdminUsersActions.ts (write-path mutations) into the single
 * interface AdminUsersPage.tsx renders from (2026-09; Raven Style
 * Compliance Plan Phase 8b line-count reduction).
 */

import { useAdminUsersState } from "./useAdminUsersState";
import { useAdminUsersActions } from "./useAdminUsersActions";

export function useAdminUsersPage() {
  const state = useAdminUsersState();
  const actions = useAdminUsersActions(state);

  return {
    ...state,
    ...actions,
    closeInviteModal: () => {
      state.setShowInviteComposer(false);
      state.setInviteError(null);
    },
  };
}
