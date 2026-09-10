"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Header } from "@/components/brand/Header";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import type { ShaySession } from "@/lib/shay-types";
import { AuthPageFallback } from "./AuthPageFallback";
import { HeroPanel } from "./HeroPanel";
import { LoginForm } from "./LoginForm";

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
          <HeroPanel />
          <LoginForm
            email={email}
            password={password}
            showPassword={showPassword}
            saving={saving}
            error={error}
            mcpCallback={mcpCallback}
            onEmailChange={setEmail}
            onPasswordChange={setPassword}
            onToggleShowPassword={() => setShowPassword((current) => !current)}
            onSubmit={() => void submit()}
            onError={(message) => setError(message || null)}
          />
        </div>
      </main>
    </div>
  );
}
