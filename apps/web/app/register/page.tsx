"use client";

import { Suspense, useMemo, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Logo } from "@/components/brand/Logo";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import {
  getPasswordRequirementFlags,
  isPasswordPolicyValid,
  PASSWORD_POLICY_ERROR_MESSAGE,
} from "@/lib/password-policy";
import { RegisterForm } from "./RegisterForm";
import { RegisterPageFallback } from "./RegisterFallback";
import { useInviteLoader } from "./useInviteLoader";

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
  const [inviteLoaded, setInviteLoaded] = useState(!encryptedInvite);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const passwordFlags = useMemo(
    () => getPasswordRequirementFlags(password),
    [password],
  );
  const routeToOnboarding = () => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("aryx.workspaceId");
    }
    router.push("/start");
  };

  useInviteLoader({
    encryptedInvite,
    onLoaded: (invite) => {
      setEmail(invite.email_id);
      setInviteId(invite.invite_id);
      setCompanyId(invite.company_id);
      setRole(invite.role);
    },
    onError: setError,
    onDone: () => setInviteLoaded(true),
  });

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

          <RegisterForm
            name={name}
            email={email}
            password={password}
            confirmPassword={confirmPassword}
            encryptedInvite={encryptedInvite}
            inviteId={inviteId}
            showPassword={showPassword}
            showConfirmPassword={showConfirmPassword}
            saving={saving}
            inviteLoaded={inviteLoaded}
            error={error}
            passwordFlags={passwordFlags}
            onNameChange={setName}
            onEmailChange={setEmail}
            onPasswordChange={setPassword}
            onConfirmPasswordChange={setConfirmPassword}
            onToggleShowPassword={() => setShowPassword((value) => !value)}
            onToggleShowConfirmPassword={() => setShowConfirmPassword((value) => !value)}
            onError={(message) => setError(message || null)}
            onSubmit={submit}
          />
        </div>
      </div>
    </div>
  );
}
