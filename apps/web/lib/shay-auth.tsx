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
import type { ShayProfile, ShaySession } from "./shay-types";

export const SHAY_SESSION_STORAGE_KEY = "aryx.shay.session";

interface ShayAuthContextValue {
  ready: boolean;
  session: ShaySession | null;
  profile: ShayProfile | null;
  setSession: (session: ShaySession) => void;
  clearSession: () => void;
  refreshProfile: () => Promise<void>;
}

const ShayAuthContext = createContext<ShayAuthContextValue | null>(null);

function isAuthFailure(error: unknown) {
  return error instanceof Error && /\b(401|403)\b/.test(error.message);
}

export function ShayAuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [session, setSessionState] = useState<ShaySession | null>(null);
  const [profile, setProfile] = useState<ShayProfile | null>(null);

  const clearSession = useCallback(() => {
    setSessionState(null);
    setProfile(null);
    if (typeof window !== "undefined") {
      localStorage.removeItem(SHAY_SESSION_STORAGE_KEY);
    }
  }, []);

  const setSession = useCallback((next: ShaySession) => {
    setSessionState(next);
    setProfile(null);
    if (typeof window !== "undefined") {
      localStorage.setItem(SHAY_SESSION_STORAGE_KEY, JSON.stringify(next));
    }
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
      if (isAuthFailure(error)) {
        clearSession();
      }
    }
  }, [clearSession, session?.access_token]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const raw = localStorage.getItem(SHAY_SESSION_STORAGE_KEY);
    if (raw) {
      try {
        setSessionState(JSON.parse(raw) as ShaySession);
      } catch {
        localStorage.removeItem(SHAY_SESSION_STORAGE_KEY);
      }
    }
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready || !session?.access_token) return;
    void refreshProfile();
  }, [ready, refreshProfile, session?.access_token]);

  const value = useMemo<ShayAuthContextValue>(() => ({
    ready,
    session,
    profile,
    setSession,
    clearSession,
    refreshProfile,
  }), [clearSession, profile, ready, refreshProfile, session, setSession]);

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
