"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useCallback,
  useState,
  type ReactNode,
} from "react";
import { shayApi } from "./shay-api";
import {
  clearStoredShaySession,
  getStoredShaySession,
  isHttpStatusError,
  type SessionClearReason,
  type ShayAuthState,
  SHAY_SESSION_STORAGE_KEY,
  storeShaySession,
  subscribeToShaySession,
} from "./shay-session";
import type { ShayProfile, ShaySession } from "./shay-types";

interface ShayAuthContextValue {
  ready: boolean;
  authState: ShayAuthState;
  session: ShaySession | null;
  profile: ShayProfile | null;
  setSession: (session: ShaySession) => void;
  clearSession: (reason?: SessionClearReason) => void;
  refreshProfile: () => Promise<void>;
}

const ShayAuthContext = createContext<ShayAuthContextValue | null>(null);

export function ShayAuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [authState, setAuthState] = useState<ShayAuthState>("signed_out");
  const [session, setSessionState] = useState<ShaySession | null>(null);
  const [profile, setProfile] = useState<ShayProfile | null>(null);

  const clearSession = useCallback((reason: SessionClearReason = "logout") => {
    clearStoredShaySession(reason);
  }, []);

  const setSession = useCallback((next: ShaySession) => {
    storeShaySession(next);
  }, []);

  const refreshProfile = useCallback(async () => {
    if (!session?.access_token) {
      setProfile(null);
      return;
    }
    try {
      const nextProfile = await shayApi.getProfile(session.access_token);
      setProfile(nextProfile);
    } catch (error) {
      setProfile(null);
      if (isHttpStatusError(error, 401)) {
        clearSession("expired");
      }
    }
  }, [clearSession, session?.access_token]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const syncSession = (nextSession: ShaySession | null, reason?: SessionClearReason) => {
      setSessionState(nextSession);
      setProfile(null);
      if (nextSession) {
        setAuthState("authenticated");
        return;
      }
      setAuthState(reason === "expired" ? "expired" : "signed_out");
    };

    syncSession(getStoredShaySession());

    const unsubscribe = subscribeToShaySession(syncSession);
    const onStorage = (event: StorageEvent) => {
      if (event.key && event.key !== SHAY_SESSION_STORAGE_KEY) {
        return;
      }
      syncSession(getStoredShaySession());
    };

    window.addEventListener("storage", onStorage);
    setReady(true);
    return () => {
      unsubscribe();
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  useEffect(() => {
    if (!ready || !session?.access_token) return;
    void refreshProfile();
  }, [ready, refreshProfile, session?.access_token]);

  const value = useMemo<ShayAuthContextValue>(() => ({
    ready,
    authState,
    session,
    profile,
    setSession,
    clearSession,
    refreshProfile,
  }), [authState, clearSession, profile, ready, refreshProfile, session, setSession]);

  return (
    <ShayAuthContext.Provider value={value}>
      {children}
    </ShayAuthContext.Provider>
  );
}

export function useShayAuth() {
  const value = useContext(ShayAuthContext);
  if (!value) {
    throw new Error("useShayAuth must be used inside <ShayAuthProvider>");
  }
  return value;
}
