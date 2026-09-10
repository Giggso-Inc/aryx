"use client";

import { useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Logo } from "@/components/brand/Logo";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import {
  getPasswordRequirementFlags,
  isPasswordPolicyValid,
  PASSWORD_POLICY_ERROR_MESSAGE,
} from "@/lib/password-policy";
import { SignupForm } from "./SignupForm";

interface FormErrors {
  companyName?: string;
  domain?: string;
  contactEmail?: string;
  userName?: string;
  password?: string;
  confirmPassword?: string;
}

const domainPattern = /^[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]*\.[a-zA-Z]{2,}$/;

export default function CompanySignupPage() {
  const router = useRouter();
  const { setSession } = useShayAuth();

  const [companyName, setCompanyName] = useState("");
  const [domain, setDomain] = useState("");
  const [userName, setUserName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});
  const [error, setError] = useState<string | null>(null);

  const passwordFlags = useMemo(() => getPasswordRequirementFlags(password), [password]);

  const routeToOnboarding = () => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("aryx.workspaceId");
    }
    router.push("/start");
  };

  const validate = () => {
    const nextErrors: FormErrors = {};

    if (!companyName.trim()) {
      nextErrors.companyName = "Company name is required.";
    }
    if (!domain.trim()) {
      nextErrors.domain = "Domain is required.";
    } else if (!domainPattern.test(domain.trim())) {
      nextErrors.domain = "Enter a valid company domain, like example.com.";
    }
    if (!contactEmail.trim()) {
      nextErrors.contactEmail = "Contact email is required.";
    }
    if (!userName.trim()) {
      nextErrors.userName = "Full name is required.";
    }
    if (!password) {
      nextErrors.password = "Password is required.";
    } else if (!isPasswordPolicyValid(password)) {
      nextErrors.password = PASSWORD_POLICY_ERROR_MESSAGE;
    }
    if (!confirmPassword) {
      nextErrors.confirmPassword = "Please confirm your password.";
    } else if (password !== confirmPassword) {
      nextErrors.confirmPassword = "Passwords do not match.";
    }

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!validate()) {
      return;
    }

    setSaving(true);
    try {
      await shayApi.companySignup({
        name: companyName.trim(),
        domain: domain.trim(),
        userName: userName.trim(),
        contactEmail: contactEmail.trim(),
        industry: undefined,
        password,
      });
      const auth = await shayApi.autoLogin(contactEmail.trim(), password);
      setSession(auth);
      routeToOnboarding();
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Company signup failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(64,104,168,0.12),_transparent_28%),linear-gradient(180deg,_#f8f9fc,_#eef2fb)] px-6 py-10">
      <div className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-xl items-center justify-center">
        <div className="w-full rounded-[2rem] border border-navy-100 bg-white/95 p-8 shadow-[0_24px_70px_rgba(15,31,61,0.12)] backdrop-blur">
          <div className="text-center">
            <div className="inline-flex rounded-full bg-canvas px-5 py-3 shadow-sm">
              <Logo size={42} withWordmark showTagline={false} />
            </div>
            <h1 className="mt-6 text-4xl font-semibold text-navy-900">Welcome to Aryx</h1>
          </div>

          <SignupForm
            companyName={companyName}
            domain={domain}
            userName={userName}
            contactEmail={contactEmail}
            password={password}
            confirmPassword={confirmPassword}
            showPassword={showPassword}
            showConfirmPassword={showConfirmPassword}
            saving={saving}
            errors={errors}
            error={error}
            passwordFlags={passwordFlags}
            onCompanyNameChange={setCompanyName}
            onDomainChange={setDomain}
            onUserNameChange={setUserName}
            onContactEmailChange={setContactEmail}
            onPasswordChange={setPassword}
            onConfirmPasswordChange={setConfirmPassword}
            onToggleShowPassword={() => setShowPassword((value) => !value)}
            onToggleShowConfirmPassword={() => setShowConfirmPassword((value) => !value)}
            onSubmit={submit}
          />

          <div className="mt-7 text-center text-sm text-subtle">
            Already have an account?{" "}
            <Link
              href="/login"
              className="font-medium text-navy-700 underline underline-offset-4 hover:text-navy-900"
            >
              Sign In
            </Link>
          </div>
          <p className="mt-5 text-center text-sm text-subtle">
            By creating an account, you agree to the Aryx terms of service and privacy policy.
          </p>
        </div>
      </div>

      <p className="mt-6 text-center text-sm text-subtle">
        © {new Date().getFullYear()} Aryx. All rights reserved.
      </p>
    </div>
  );
}
