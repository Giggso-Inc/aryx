"use client";

import { Suspense, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, Eye, EyeOff, Info, Lock, Mail, User } from "lucide-react";
import { PasswordRequirements } from "@/components/auth/PasswordRequirements";
import SsoProviderButtons from "@/components/auth/SsoProviderButtons";
import { Logo } from "@/components/brand/Logo";
import { decodeRegistrationToken } from "@/lib/auth-crypto";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import {
  getPasswordRequirementFlags,
  isPasswordPolicyValid,
  PASSWORD_POLICY_ERROR_MESSAGE,
  PASSWORD_REQUIREMENT_LABELS,
} from "@/lib/password-policy";

interface FieldProps {
  label: string;
  required?: boolean;
  icon: ReactNode;
  note?: string;
  children: ReactNode;
}

function Field({ label, required = false, icon, note, children }: FieldProps) {
  return (
    <label className="block space-y-2">
      <span className="text-sm font-semibold text-navy-900">
        {label} {required ? <span className="text-rose-500">*</span> : null}
      </span>
      <div className="relative">
        <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-4 text-subtle">
          {icon}
        </div>
        {children}
      </div>
      {note ? (
        <p className="flex items-start gap-1.5 text-xs text-blue-700">
          <Info size={14} className="mt-0.5 shrink-0" />
          <span>{note}</span>
        </p>
      ) : null}
    </label>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={<RegisterPageFallback />}>
      <RegisterPageContent />
    </Suspense>
  );
}

function RegisterPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setSession } = useShayAuth();

  const [email, setEmail] = useState(searchParams.get("email") || "");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [inviteId, setInviteId] = useState(searchParams.get("invite_id") || "");
  const [companyId, setCompanyId] = useState(searchParams.get("company_id") || "");
  const [role, setRole] = useState(searchParams.get("role") || "user");
  const [encryptedInvite] = useState(searchParams.get("e") || "");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const passwordFlags = useMemo(
    () => getPasswordRequirementFlags(password),
    [password],
  );
  const emailLocked = !!encryptedInvite;

  const routeToOnboarding = () => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("aryx.workspaceId");
    }
    router.push("/start");
  };

  useEffect(() => {
    let active = true;

    async function preloadInvite() {
      if (!encryptedInvite) {
        return;
      }

      const decoded = await decodeRegistrationToken(encryptedInvite);
      if (!active || !decoded.valid) {
        return;
      }

      setEmail(decoded.email);
      setInviteId(decoded.invite_code);
      setCompanyId(decoded.company_id);
      setRole(decoded.role || "user");
    }

    void preloadInvite();
    return () => {
      active = false;
    };
  }, [encryptedInvite]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!email.trim()) {
      setError("Email address is required.");
      return;
    }
    if (!name.trim()) {
      setError("Full name is required.");
      return;
    }
    if (!password || !confirmPassword) {
      setError("Please enter and confirm your password.");
      return;
    }
    if (!isPasswordPolicyValid(password)) {
      setError(PASSWORD_POLICY_ERROR_MESSAGE);
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setSaving(true);
    try {
      const auth = await shayApi.register({
        email_id: email.trim(),
        password,
        name: name.trim(),
        company_id: companyId || undefined,
        invite_id: inviteId || undefined,
        encrypted_param: encryptedInvite || undefined,
        role: role || undefined,
      });
      setSession(auth);
      routeToOnboarding();
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Registration failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-screen bg-canvas px-6 py-10">
      <div className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-2xl items-center justify-center">
        <div className="w-full rounded-[2rem] border border-navy-100 bg-white/96 p-8 shadow-[0_24px_70px_rgba(15,31,61,0.12)] backdrop-blur">
          <div className="text-center">
            <div className="inline-flex rounded-full bg-canvas px-5 py-3 shadow-sm">
              <Logo size={42} withWordmark showTagline={false} />
            </div>
            <h1 className="mt-6 text-4xl font-semibold text-navy-900">Create your Aryx account</h1>
            <p className="mt-3 text-sm text-subtle">
              Join your organization workspace and start using Aryx Ask, ingest, and graph.
            </p>
          </div>

          <form onSubmit={submit} className="mt-8 space-y-5">
            <Field label="Full Name" required icon={<User size={18} />}>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="John Doe"
                className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 text-sm text-navy-900 placeholder:text-slate-400"
              />
            </Field>

            <Field
              label="Email Address"
              required
              icon={<Mail size={18} />}
              note={emailLocked ? "Email from invitation link (cannot be changed)" : undefined}
            >
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="shay@giggso.com"
                readOnly={emailLocked}
                aria-readonly={emailLocked}
                className={[
                  "focus-ring h-12 w-full rounded-xl border px-12 text-sm text-navy-900 placeholder:text-slate-400",
                  emailLocked
                    ? "cursor-not-allowed border-blue-100 bg-blue-50/70"
                    : "border-navy-100 bg-white",
                ].join(" ")}
              />
            </Field>

            <Field label="Password" required icon={<Lock size={18} />}>
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Password"
                className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 pr-12 text-sm text-navy-900 placeholder:text-slate-400"
              />
              <button
                type="button"
                onClick={() => setShowPassword((value) => !value)}
                className="absolute inset-y-0 right-0 flex items-center pr-4 text-subtle transition-colors hover:text-navy-700"
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </Field>

            <PasswordRequirements flags={passwordFlags} labels={PASSWORD_REQUIREMENT_LABELS} />

            <Field label="Confirm Password" required icon={<Lock size={18} />}>
              <input
                type={showConfirmPassword ? "text" : "password"}
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                placeholder="Confirm Password"
                className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 pr-12 text-sm text-navy-900 placeholder:text-slate-400"
              />
              <button
                type="button"
                onClick={() => setShowConfirmPassword((value) => !value)}
                className="absolute inset-y-0 right-0 flex items-center pr-4 text-subtle transition-colors hover:text-navy-700"
                aria-label={showConfirmPassword ? "Hide confirm password" : "Show confirm password"}
              >
                {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </Field>

            {error ? (
              <div className="flex items-start gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                <AlertCircle size={16} className="mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            ) : null}

            <button
              type="submit"
              disabled={!email.trim() || !name.trim() || !password || !confirmPassword || saving}
              className="focus-ring inline-flex h-12 w-full items-center justify-center rounded-2xl bg-navy-800 text-sm font-semibold text-white shadow-lg shadow-navy-900/20 transition-transform hover:-translate-y-0.5 hover:bg-navy-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? "Creating account..." : "Create account"}
            </button>
          </form>

          <div className="mt-6 flex items-center gap-4 text-[11px] font-semibold uppercase tracking-[0.22em] text-subtle">
            <span className="h-px flex-1 bg-navy-100" />
            <span>OR</span>
            <span className="h-px flex-1 bg-navy-100" />
          </div>

          <div className="mt-6">
            <SsoProviderButtons
              inviteId={inviteId || undefined}
              onError={(message) => setError(message || null)}
            />
          </div>

          <div className="mt-6 border-t border-navy-100 pt-6 text-center text-sm text-subtle">
            Already have an account?{" "}
            <Link href="/login" className="font-semibold text-navy-700 transition-colors hover:text-navy-900">
              Sign in
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

function RegisterPageFallback() {
  return (
    <div className="min-h-screen bg-canvas px-6 py-10">
      <div className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-2xl items-center justify-center">
        <div className="w-full rounded-[2rem] border border-navy-100 bg-white/96 p-8 shadow-[0_24px_70px_rgba(15,31,61,0.12)] backdrop-blur">
          <p className="text-sm text-subtle">Loading registration...</p>
        </div>
      </div>
    </div>
  );
}
