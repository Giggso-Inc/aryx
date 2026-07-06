"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Eye, EyeOff, Shield } from "lucide-react";
import { Header } from "@/components/brand/Header";
import SsoProviderButtons from "@/components/auth/SsoProviderButtons";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import type { ShaySession } from "@/lib/shay-types";

export default function LoginPage() {
  return (
    <Suspense fallback={<AuthPageFallback message="Loading login..." />}>
      <LoginPageContent />
    </Suspense>
  );
}

function LoginPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { ready, session, setSession } = useShayAuth();
  const [email, setEmail] = useState(searchParams.get("email") || "");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const next = searchParams.get("next") || "";
  const mcpCallback = searchParams.get("mcp_callback") || "";
  const destinationFor = useCallback((auth: ShaySession) => {
    if (next === "/" || next === "/start") {
      return "/workspaces";
    }
    if (next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/login")) {
      return next;
    }
    return auth.default_workspace_id ? `/workspaces/${auth.default_workspace_id}` : "/workspaces";
  }, [next]);

  useEffect(() => {
    if (!ready || !session) return;
    router.replace(destinationFor(session));
  }, [destinationFor, ready, router, session]);

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      const auth = await shayApi.login(email.trim(), password);
      setSession(auth);
      router.replace(destinationFor(auth));
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Login failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-screen overflow-x-hidden bg-canvas">
      <Header />
      <main className="mx-auto flex min-h-[calc(100vh-72px)] max-w-6xl items-center px-6 py-12">
        <div className="grid w-full gap-8 lg:grid-cols-[minmax(0,1.05fr)_420px]">
          <section className="rounded-[2rem] bg-[radial-gradient(circle_at_top_left,_rgba(64,104,168,0.18),_transparent_42%),linear-gradient(140deg,_rgba(10,21,48,0.98),_rgba(15,31,61,0.94))] px-8 py-10 text-white shadow-soft">
            <div className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-white/75">
              <Shield size={13} />
              Aryx knowledge graph
            </div>
            <h1 className="mt-5 font-display text-5xl leading-tight">
              Login once, move across the Aryx stack.
            </h1>
            <p className="mt-5 max-w-2xl text-base text-white/78">
              Aryx keeps identity, workspaces, ingest, graph retrieval, and Ask in one place.
              Sign in once to manage your workspace and explore the knowledge graph.
            </p>
            <div className="mt-8 grid gap-4 md:grid-cols-3">
              <Feature title="Secure sign-in" body="Email, password, Google, or Microsoft authentication" />
              <Feature title="Shared workspace" body="Company, membership, and source registration in one place" />
              <Feature title="Aryx Ask" body="Questions are answered from the graph with citations" />
            </div>
          </section>

          <section className="rounded-[2rem] border border-navy-100 bg-white p-7 shadow-soft">
            <h2 className="mt-4 text-3xl font-semibold text-navy-900">Welcome back</h2>
            <p className="mt-2 text-sm text-subtle">
              Sign in with your Aryx credentials or continue with Google or Microsoft.
            </p>
            <div className="mt-6 space-y-3">
              <input
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="Email address"
                className="focus-ring w-full rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
              />
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Password"
                  className="focus-ring w-full rounded-2xl border border-navy-100 px-4 py-3 pr-12 text-sm text-navy-900"
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !saving) void submit();
                  }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((current) => !current)}
                  className="focus-ring absolute right-3 top-1/2 inline-flex size-8 -translate-y-1/2 items-center justify-center rounded-full text-navy-500 hover:bg-navy-50 hover:text-navy-800"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  title={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </div>
              <div className="flex justify-end">
                <Link
                  href="/forgot-password"
                  className="text-sm font-medium text-navy-700 underline underline-offset-4 transition-colors hover:text-navy-900"
                >
                  Forgot password?
                </Link>
              </div>
              <button
                type="button"
                onClick={submit}
                disabled={!email.trim() || !password || saving}
                className="focus-ring inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-navy-800 px-4 py-3 text-sm font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
              >
                {saving ? "Signing in..." : "Login"}
              </button>
              {error ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                  {error}
                </div>
              ) : null}
            </div>
            <div className="mt-6 flex items-center gap-4 text-[11px] font-semibold uppercase tracking-[0.22em] text-subtle">
              <span className="h-px flex-1 bg-navy-100" />
              <span>OR</span>
              <span className="h-px flex-1 bg-navy-100" />
            </div>
            <div className="mt-6">
              <SsoProviderButtons
                onError={(message) => setError(message || null)}
                mcpCallback={mcpCallback || undefined}
              />
            </div>
            <div className="mt-6 text-center text-sm text-subtle">
              If you don&apos;t have an account,&nbsp;
              <Link
                href="/company-signup"
                className="font-medium text-navy-700 underline underline-offset-4 hover:text-navy-900"
              >
                Sign Up
              </Link>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}

function AuthPageFallback({ message }: { message: string }) {
  return (
    <div className="min-h-screen bg-canvas">
      <Header />
      <main className="mx-auto flex min-h-[calc(100vh-72px)] max-w-6xl items-center justify-center px-6 py-12">
        <div className="rounded-[2rem] border border-navy-100 bg-white px-8 py-10 text-center shadow-soft">
          <p className="text-sm text-subtle">{message}</p>
        </div>
      </main>
    </div>
  );
}

function Feature({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-[1.5rem] border border-white/10 bg-white/5 p-4">
      <p className="text-sm font-semibold text-white">{title}</p>
      <p className="mt-2 text-sm text-white/72">{body}</p>
    </div>
  );
}
