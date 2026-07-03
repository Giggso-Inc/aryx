"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { KeyRound, Mail } from "lucide-react";
import { Logo } from "@/components/brand/Logo";
import { shayApi } from "@/lib/shay-api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const response = await shayApi.forgotPassword({
        email_id: email.trim(),
        base_url: window.location.origin,
        app_name: "Aryx",
      });
      setNotice(response.message || "Reset instructions were sent to your email.");
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Unable to send reset instructions.");
    } finally {
      setSaving(false);
    }
  };

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
              <div className="mx-auto flex size-16 items-center justify-center rounded-full bg-navy-800 text-white shadow-lg shadow-navy-900/20">
                <KeyRound size={30} />
              </div>
              <h1 className="mt-5 text-4xl font-semibold text-navy-900">Forgot Password?</h1>
              <p className="mt-3 text-sm text-subtle">
                No worries, we&apos;ll send you reset instructions.
              </p>
            </div>

            <form onSubmit={submit} className="mt-8 space-y-6">
              <label className="block space-y-2">
                <span className="text-sm font-semibold text-navy-900">Email Address</span>
                <div className="relative">
                  <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-4 text-subtle">
                    <Mail size={18} />
                  </div>
                  <input
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="you@example.com"
                    className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 text-sm text-navy-900 placeholder:text-slate-400"
                    required
                  />
                </div>
              </label>

              {error ? (
                <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                  {error}
                </div>
              ) : null}

              {notice ? (
                <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
                  {notice}
                </div>
              ) : null}

              <button
                type="submit"
                disabled={saving}
                className="focus-ring inline-flex h-12 w-full items-center justify-center rounded-xl bg-navy-800 text-sm font-semibold text-white shadow-lg shadow-navy-900/20 transition-transform hover:-translate-y-0.5 hover:bg-navy-700 disabled:opacity-60"
              >
                {saving ? "Sending..." : "Send Reset Instructions"}
              </button>
            </form>

            <div className="mt-7 border-t border-navy-100 pt-6 text-center">
              <Link
                href="/login"
                className="text-sm font-medium text-navy-700 underline underline-offset-4 transition-colors hover:text-navy-900"
              >
                Back to Login
              </Link>
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
