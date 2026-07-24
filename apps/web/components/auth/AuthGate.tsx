"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useShayAuth } from "@/lib/shay-auth";

const PROTECTED_PATHS = [
  "/",
  "/home",
  "/brief",
  "/ingest",
  "/graph",
  "/model",
  "/observability",
  "/settings",
  "/data",
  "/start",
  "/workspaces",
  "/admin",
];

function isProtectedPath(pathname: string) {
  if (pathname === "/") return true;
  return PROTECTED_PATHS.slice(1).some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { authState, ready, session } = useShayAuth();
  const pathname = usePathname();
  const router = useRouter();

  const protectedPath = isProtectedPath(pathname || "/");

  useEffect(() => {
    if (!ready || !protectedPath || session) return;
    const search = typeof window !== "undefined" ? window.location.search : "";
    const next = pathname === "/" ? "/workspaces" : `${pathname || "/"}${search}`;
    if (authState === "expired") {
      router.replace(`/session-expired?next=${encodeURIComponent(next)}`);
      return;
    }
    router.replace(`/login?next=${encodeURIComponent(next)}`);
  }, [authState, pathname, protectedPath, ready, router, session]);

  if (!protectedPath) {
    return <>{children}</>;
  }

  if (ready && !session) {
    return null;
  }

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-6">
        <div className="rounded-3xl border border-navy-100 bg-white px-8 py-10 text-center shadow-soft">
          <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-navy-50 text-navy-700">
            <Loader2 size={20} className="animate-spin" />
          </div>
          <h1 className="mt-4 font-display text-2xl text-navy-900">
            Loading Aryx
          </h1>
          <p className="mt-2 max-w-sm text-sm text-subtle">
            Checking your session.
          </p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
