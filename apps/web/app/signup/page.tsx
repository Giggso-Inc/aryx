"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Header } from "@/components/brand/Header";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";

export default function SignupPage() {
  return (
    <Suspense fallback={<SignupPageFallback />}>
      <SignupPageContent />
    </Suspense>
  );
}

function SignupPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setSession } = useShayAuth();
  const [email, setEmail] = useState(searchParams.get("email") || "");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inviteId = searchParams.get("invite_id") || undefined;
  const companyId = searchParams.get("company_id") || undefined;
  const role = searchParams.get("role") || undefined;

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      const auth = await shayApi.register({
        email_id: email.trim(),
        password,
        name: name.trim() || undefined,
        company_id: companyId,
        invite_id: inviteId,
        role,
      });
      setSession(auth);
      router.push(auth.default_workspace_id ? `/workspaces/${auth.default_workspace_id}` : "/workspaces");
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Signup failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-screen bg-canvas">
      <Header />
      <main className="mx-auto max-w-3xl px-6 py-12">
        <section className="rounded-[2rem] border border-navy-100 bg-white p-8 shadow-soft">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-navy-700">
            Join a company workspace
          </p>
          <h1 className="mt-4 font-display text-4xl text-navy-900">
            Create your Aryx account
          </h1>
          <p className="mt-3 text-sm text-subtle">
            Use an invite link or a company id to join an existing company, then your workspace can be mapped into Aryx Ask and ingest.
          </p>
          <div className="mt-6 grid gap-4">
            <input
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="Email address"
              className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
            />
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
                placeholder="Full name"
                className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
              />
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Password"
              className="focus-ring rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
            />
            <div className="grid gap-3 rounded-2xl bg-navy-50 p-4 text-sm text-subtle md:grid-cols-3">
              <div>
                <p className="font-medium text-navy-900">Invite ID</p>
                <p>{inviteId || "Not provided"}</p>
              </div>
              <div>
                <p className="font-medium text-navy-900">Company ID</p>
                <p>{companyId || "Not provided"}</p>
              </div>
              <div>
                <p className="font-medium text-navy-900">Role</p>
                <p>{role || "user"}</p>
              </div>
            </div>
            <button
              type="button"
              onClick={submit}
              disabled={!email.trim() || !password || saving}
              className="focus-ring rounded-2xl bg-navy-800 px-4 py-3 text-sm font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
            >
              {saving ? "Creating account..." : "Create account"}
            </button>
            {error ? (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {error}
              </div>
            ) : null}
          </div>
          <div className="mt-6 flex flex-wrap items-center gap-3 text-sm text-subtle">
            <span>Need SSO instead?</span>
            <Link
                href={`/sso/google${inviteId ? `?invite_id=${encodeURIComponent(inviteId)}` : ""}`}
                className="font-medium text-navy-700 hover:text-navy-900"
              >
                Continue with Google
            </Link>
            <span>or</span>
            <Link
              href={`/sso/microsoft${inviteId ? `?invite_id=${encodeURIComponent(inviteId)}` : ""}`}
              className="font-medium text-navy-700 hover:text-navy-900"
            >
              Continue with Microsoft
            </Link>
          </div>
        </section>
      </main>
    </div>
  );
}

function SignupPageFallback() {
  return (
    <div className="min-h-screen bg-canvas">
      <Header />
      <main className="mx-auto max-w-3xl px-6 py-12">
        <section className="rounded-[2rem] border border-navy-100 bg-white p-8 shadow-soft">
          <p className="text-sm text-subtle">Loading signup...</p>
        </section>
      </main>
    </div>
  );
}
