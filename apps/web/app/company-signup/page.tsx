"use client";

import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Building2,
  Eye,
  EyeOff,
  Globe,
  Lock,
  Mail,
  User,
} from "lucide-react";
import { PasswordRequirements } from "@/components/auth/PasswordRequirements";
import { Logo } from "@/components/brand/Logo";
import { shayApi } from "@/lib/shay-api";
import { useShayAuth } from "@/lib/shay-auth";
import {
  getPasswordRequirementFlags,
  isPasswordPolicyValid,
  PASSWORD_POLICY_ERROR_MESSAGE,
  PASSWORD_REQUIREMENT_LABELS,
} from "@/lib/password-policy";

interface FormErrors {
  companyName?: string;
  domain?: string;
  contactEmail?: string;
  userName?: string;
  password?: string;
  confirmPassword?: string;
}

const domainPattern = /^[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]*\.[a-zA-Z]{2,}$/;

function Field({
  label,
  required = false,
  error,
  icon,
  trailing,
  children,
}: {
  label: string;
  required?: boolean;
  error?: string;
  icon: ReactNode;
  trailing?: ReactNode;
  children: ReactNode;
}) {
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
        {trailing ? (
          <div className="absolute inset-y-0 right-0 flex items-center pr-4">
            {trailing}
          </div>
        ) : null}
      </div>
      {error ? <p className="text-sm text-rose-700">{error}</p> : null}
    </label>
  );
}

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
      router.push(auth.default_workspace_id ? `/workspaces/${auth.default_workspace_id}` : "/workspaces");
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

          <form onSubmit={submit} className="mt-10 space-y-5">
            <Field
              label="Company Name"
              required
              error={errors.companyName}
              icon={<Building2 size={18} />}
            >
              <input
                value={companyName}
                onChange={(event) => setCompanyName(event.target.value)}
                placeholder="Acme Corporation"
                className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 text-sm text-navy-900 placeholder:text-slate-400"
              />
            </Field>

            <Field
              label="Domain"
              required
              error={errors.domain}
              icon={<Globe size={18} />}
            >
              <input
                value={domain}
                onChange={(event) => setDomain(event.target.value)}
                placeholder="acme.com"
                className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 text-sm text-navy-900 placeholder:text-slate-400"
              />
            </Field>

            <Field
              label="Contact Email"
              required
              error={errors.contactEmail}
              icon={<Mail size={18} />}
            >
              <input
                type="email"
                value={contactEmail}
                onChange={(event) => setContactEmail(event.target.value)}
                placeholder="john@acme.com"
                className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 text-sm text-navy-900 placeholder:text-slate-400"
              />
            </Field>

            <Field
              label="Full Name"
              required
              error={errors.userName}
              icon={<User size={18} />}
            >
              <input
                value={userName}
                onChange={(event) => setUserName(event.target.value)}
                placeholder="John Doe"
                className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 text-sm text-navy-900 placeholder:text-slate-400"
              />
            </Field>

            <Field
              label="Password"
              required
              error={errors.password}
              icon={<Lock size={18} />}
              trailing={(
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  className="text-subtle transition-colors hover:text-navy-700"
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              )}
            >
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Enter your password"
                className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 pr-12 text-sm text-navy-900 placeholder:text-slate-400"
              />
            </Field>

            <PasswordRequirements
              flags={passwordFlags}
              labels={PASSWORD_REQUIREMENT_LABELS}
            />

            <Field
              label="Confirm Password"
              required
              error={errors.confirmPassword}
              icon={<Lock size={18} />}
              trailing={(
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword((value) => !value)}
                  className="text-subtle transition-colors hover:text-navy-700"
                >
                  {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              )}
            >
              <input
                type={showConfirmPassword ? "text" : "password"}
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                placeholder="Confirm your password"
                className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 pr-12 text-sm text-navy-900 placeholder:text-slate-400"
              />
            </Field>

            {error ? (
              <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {error}
              </div>
            ) : null}

            <button
              type="submit"
              disabled={saving}
              className="focus-ring inline-flex h-12 w-full items-center justify-center rounded-xl bg-navy-800 text-sm font-semibold text-white shadow-lg shadow-navy-900/20 transition-transform hover:-translate-y-0.5 hover:bg-navy-700 disabled:opacity-60"
            >
              {saving ? "Creating account..." : "Create Account"}
            </button>
          </form>

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
