"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Header } from "@/components/brand/Header";
import { useShayAuth } from "@/lib/shay-auth";
import type { ShaySession } from "@/lib/shay-types";

function decodeBase64Url(value: string) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  return atob(padded);
}

export default function SsoCallbackPage() {
  const router = useRouter();
  const { setSession } = useShayAuth();
  const [message, setMessage] = useState("Finalizing SSO session...");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const hash = window.location.hash.startsWith("#")
      ? window.location.hash.slice(1)
      : window.location.hash;
    const params = new URLSearchParams(hash);
    const next = localStorage.getItem("aryx.shay.sso.next") || "/workspaces";
    localStorage.removeItem("aryx.shay.sso.next");

    const error = params.get("message");
    const ssoData = params.get("sso_data");

    if (error) {
      setMessage(error);
      return;
    }
    if (!ssoData) {
      setMessage("Missing SSO payload.");
      return;
    }
    try {
      const parsed = JSON.parse(decodeBase64Url(ssoData)) as ShaySession;
      setSession(parsed);
      router.replace(parsed.default_workspace_id ? `/workspaces/${parsed.default_workspace_id}` : next);
    } catch (nextError: unknown) {
      setMessage(nextError instanceof Error ? nextError.message : "Unable to decode SSO payload.");
    }
  }, [router, setSession]);

  return (
    <div className="min-h-screen bg-canvas">
      <Header />
      <main className="mx-auto flex min-h-[calc(100vh-72px)] max-w-3xl items-center justify-center px-6 py-12">
        <div className="rounded-[2rem] border border-navy-100 bg-white px-8 py-10 text-center shadow-soft">
          <h1 className="font-display text-4xl text-navy-900">SSO callback</h1>
          <p className="mt-4 text-sm text-subtle">{message}</p>
        </div>
      </main>
    </div>
  );
}

