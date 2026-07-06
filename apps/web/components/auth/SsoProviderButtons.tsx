"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { shayApi } from "@/lib/shay-api";

type SsoProvider = "google" | "microsoft";

interface SsoProviderButtonsProps {
  allowClick?: boolean;
  inviteId?: string;
  mcpCallback?: string;
  onError: (message: string) => void;
}

function GoogleIcon() {
  return (
    <svg className="mr-2 size-5" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
    </svg>
  );
}

function MicrosoftIcon() {
  return (
    <svg className="mr-2 size-5" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#f25022" d="M1 1h10v10H1z" />
      <path fill="#00a4ef" d="M13 1h10v10H13z" />
      <path fill="#7fba00" d="M1 13h10v10H1z" />
      <path fill="#ffb900" d="M13 13h10v10H13z" />
    </svg>
  );
}

export default function SsoProviderButtons({
  allowClick = true,
  inviteId,
  mcpCallback,
  onError,
}: SsoProviderButtonsProps) {
  const [loading, setLoading] = useState<SsoProvider | null>(null);

  const startSso = async (provider: SsoProvider) => {
    if (!allowClick || loading) return;
    setLoading(provider);
    onError("");
    try {
      if (mcpCallback && typeof window !== "undefined") {
        window.sessionStorage.setItem("mcp_callback_pending", mcpCallback);
      }
      const redirectUri = `${window.location.origin}/sso/callback`;
      const { authorization_url: authorizationUrl } = await shayApi.initiateSso(
        provider,
        redirectUri,
        inviteId,
      );
      window.location.assign(authorizationUrl);
    } catch (error: unknown) {
      onError(error instanceof Error ? error.message : "Sign-in could not be started");
      setLoading(null);
    }
  };

  const disabled = !allowClick || !!loading;

  return (
    <div className="space-y-3">
      <button
        type="button"
        disabled={disabled}
        onClick={() => void startSso("google")}
        className="focus-ring inline-flex h-12 w-full items-center justify-center rounded-2xl border-2 border-navy-100 bg-white px-4 text-sm font-semibold text-navy-700 hover:bg-navy-50 disabled:opacity-50"
      >
        {loading === "google" ? <Loader2 className="mr-2 size-5 animate-spin" /> : <GoogleIcon />}
        Continue with Google
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={() => void startSso("microsoft")}
        className="focus-ring inline-flex h-12 w-full items-center justify-center rounded-2xl border-2 border-navy-100 bg-white px-4 text-sm font-semibold text-navy-700 hover:bg-navy-50 disabled:opacity-50"
      >
        {loading === "microsoft" ? <Loader2 className="mr-2 size-5 animate-spin" /> : <MicrosoftIcon />}
        Continue with Microsoft
      </button>
    </div>
  );
}
