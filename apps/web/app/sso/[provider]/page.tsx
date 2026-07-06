"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { Header } from "@/components/brand/Header";
import { shayApi } from "@/lib/shay-api";

export default function SsoProviderPage() {
  return (
    <Suspense fallback={<SsoPageFallback />}>
      <SsoProviderPageContent />
    </Suspense>
  );
}

function SsoProviderPageContent() {
  const params = useParams<{ provider: string }>();
  const searchParams = useSearchParams();
  const [message, setMessage] = useState("Preparing secure redirect...");

  useEffect(() => {
    const provider = params.provider;
    const next = searchParams.get("next") || "/workspaces";
    const inviteId = searchParams.get("invite_id") || undefined;
    if (!provider || typeof window === "undefined") return;
    localStorage.setItem("aryx.shay.sso.next", next);
    shayApi.initiateSso(provider, `${window.location.origin}/sso/callback`, inviteId)
      .then((payload) => {
        window.location.href = payload.authorization_url;
      })
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Unable to start SSO.");
      });
  }, [params.provider, searchParams]);

  return (
    <div className="min-h-screen bg-canvas">
      <Header />
      <main className="mx-auto flex min-h-[calc(100vh-72px)] max-w-3xl items-center justify-center px-6 py-12">
        <div className="rounded-[2rem] border border-navy-100 bg-white px-8 py-10 text-center shadow-soft">
          <h1 className="font-display text-4xl text-navy-900">
            Redirecting to {String(params.provider).toUpperCase()}
          </h1>
          <p className="mt-4 text-sm text-subtle">{message}</p>
        </div>
      </main>
    </div>
  );
}

function SsoPageFallback() {
  return (
    <div className="min-h-screen bg-canvas">
      <Header />
      <main className="mx-auto flex min-h-[calc(100vh-72px)] max-w-3xl items-center justify-center px-6 py-12">
        <div className="rounded-[2rem] border border-navy-100 bg-white px-8 py-10 text-center shadow-soft">
          <p className="text-sm text-subtle">Preparing secure redirect...</p>
        </div>
      </main>
    </div>
  );
}
