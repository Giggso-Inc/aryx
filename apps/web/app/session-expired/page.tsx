"use client";

import { Suspense, useEffect } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Clock3, LogIn } from "lucide-react";
import { Header } from "@/components/brand/Header";
import { useShayAuth } from "@/lib/shay-auth";

export default function SessionExpiredPage() {
  return (
    <Suspense fallback={<SessionExpiredFallback />}>
      <SessionExpiredContent />
    </Suspense>
  );
}

function SessionExpiredContent() {
  const { authState, ready, session } = useShayAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedNext = searchParams.get("next") || "/workspaces";
  const next = requestedNext.startsWith("/") && !requestedNext.startsWith("//")
    ? requestedNext
    : "/workspaces";

  useEffect(() => {
    if (!ready || !session) {
      return;
    }
    router.replace(next);
  }, [next, ready, router, session]);

  if (ready && authState === "authenticated" && session) {
    return null;
  }

  return (
    <div className="min-h-screen overflow-x-hidden bg-canvas">
      <Header />
      <main className="mx-auto flex min-h-[calc(100vh-72px)] max-w-5xl items-center justify-center px-6 py-12">
        <section className="w-full max-w-2xl rounded-[2rem] border border-navy-100 bg-white px-8 py-10 text-center shadow-soft">
          <div className="mx-auto flex size-14 items-center justify-center rounded-3xl bg-amber-50 text-amber-700">
            <Clock3 size={24} />
          </div>
          <h1 className="mt-6 font-display text-4xl text-navy-900">
            Your session has expired
          </h1>
          <p className="mt-4 text-base leading-7 text-subtle">
            Aryx could not refresh your sign-in automatically, so we cleared the expired session
            to keep both Shay and Aryx API calls in sync. Sign in again to continue where you left off.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href={`/login?next=${encodeURIComponent(next)}`}
              className="focus-ring inline-flex items-center justify-center gap-2 rounded-2xl bg-navy-800 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-navy-700"
            >
              <LogIn size={16} />
              Login
            </Link>
            <Link
              href="/login"
              className="focus-ring inline-flex items-center justify-center rounded-2xl border border-navy-200 px-6 py-3 text-sm font-semibold text-navy-700 transition-colors hover:bg-navy-50"
            >
              Go to login
            </Link>
          </div>
        </section>
      </main>
    </div>
  );
}

function SessionExpiredFallback() {
  return (
    <div className="min-h-screen bg-canvas">
      <Header />
      <main className="mx-auto flex min-h-[calc(100vh-72px)] max-w-3xl items-center justify-center px-6 py-12">
        <div className="rounded-[2rem] border border-navy-100 bg-white px-8 py-10 text-center shadow-soft">
          <p className="text-sm text-subtle">Loading session status...</p>
        </div>
      </main>
    </div>
  );
}
