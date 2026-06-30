"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { AlertTriangle, CheckCircle2, MailCheck } from "lucide-react";
import { Logo } from "@/components/brand/Logo";
import { decodeVerificationToken } from "@/lib/auth-crypto";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";

type VerificationState = "loading" | "success" | "error";

export default function VerifyEmailPage() {
  const params = useParams<{ token: string }>();
  const router = useRouter();
  const { setSession } = useShayAuth();

  const tokenParam = Array.isArray(params?.token) ? params.token[0] : params?.token ?? "";

  const [status, setStatus] = useState<VerificationState>("loading");
  const [message, setMessage] = useState("Verifying your email and activating your Aryx workspace...");

  useEffect(() => {
    let active = true;

    async function verify() {
      if (!tokenParam) {
        if (active) {
          setStatus("error");
          setMessage("Verification link is missing or invalid.");
        }
        return;
      }

      const decoded = await decodeVerificationToken(tokenParam);
      if (!active) {
        return;
      }

      if (!decoded.valid) {
        setStatus("error");
        setMessage("Verification link is invalid. Request a new email and try again.");
        return;
      }

      try {
        const session = await shayApi.verifyEmail(decoded.token);
        if (!active) {
          return;
        }

        setSession(session);
        setStatus("success");
        setMessage("Email verified successfully. Redirecting you into Aryx...");

        window.setTimeout(() => {
          router.replace(
            session.default_workspace_id
              ? `/workspaces/${session.default_workspace_id}`
              : "/workspaces",
          );
        }, 1200);
      } catch (error: unknown) {
        if (!active) {
          return;
        }

        setStatus("error");
        setMessage(
          error instanceof Error
            ? error.message
            : "Unable to verify your email. Please request a new verification link.",
        );
      }
    }

    void verify();
    return () => {
      active = false;
    };
  }, [router, setSession, tokenParam]);

  const isSuccess = status === "success";
  const isError = status === "error";

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(64,104,168,0.12),_transparent_28%),linear-gradient(180deg,_#f8f9fc,_#eef2fb)] px-6 py-10">
      <div className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-md items-center justify-center">
        <div className="w-full">
          <div className="text-center">
            <div className="inline-flex rounded-full bg-canvas px-5 py-3 shadow-sm">
              <Logo size={42} withWordmark showTagline={false} />
            </div>
          </div>

          <div className="mt-8 rounded-[2rem] border border-navy-100 bg-white p-8 shadow-soft">
            <div className="text-center">
              <div
                className={`mx-auto flex size-16 items-center justify-center rounded-full text-white shadow-lg ${
                  isSuccess
                    ? "bg-emerald-600 shadow-emerald-700/20"
                    : isError
                      ? "bg-rose-600 shadow-rose-700/20"
                      : "bg-navy-800 shadow-navy-900/20"
                }`}
              >
                {isSuccess ? (
                  <CheckCircle2 size={30} />
                ) : isError ? (
                  <AlertTriangle size={30} />
                ) : (
                  <MailCheck size={30} />
                )}
              </div>

              <h1 className="mt-5 text-4xl font-semibold text-navy-900">
                {isSuccess ? "Email Verified" : isError ? "Verification Failed" : "Verifying Email"}
              </h1>
              <p className="mt-3 text-sm text-subtle">{message}</p>
            </div>

            <div className="mt-8 text-center">
              {status === "loading" ? (
                <div className="rounded-xl border border-navy-100 bg-canvas px-4 py-6 text-sm text-subtle">
                  Please wait while we confirm your account.
                </div>
              ) : isError ? (
                <div className="space-y-4">
                  <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-4 text-sm text-rose-700">
                    {message}
                  </div>
                  <Link
                    href="/login"
                    className="inline-flex h-12 items-center justify-center rounded-xl bg-navy-800 px-6 text-sm font-semibold text-white shadow-lg shadow-navy-900/20 transition-transform hover:-translate-y-0.5 hover:bg-navy-700"
                  >
                    Back to Login
                  </Link>
                </div>
              ) : (
                <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-6 text-sm text-emerald-700">
                  Your account is active now. We&apos;re taking you to your workspace.
                </div>
              )}
            </div>
          </div>

          <p className="mt-6 text-center text-sm text-subtle">
            © {new Date().getFullYear()} Aryx. All rights reserved.
          </p>
        </div>
      </div>
    </div>
  );
}
