"use client";

import { Suspense, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, KeyRound } from "lucide-react";
import { Logo } from "@/components/brand/Logo";
import {
  getPasswordRequirementFlags,
  isPasswordPolicyValid,
  PASSWORD_POLICY_ERROR_MESSAGE,
} from "@/lib/password-policy";
import { shayApi } from "@/lib/shay-api";
import { ResetPasswordFallback } from "./Fallback";
import { ResetForm } from "./ResetForm";

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<ResetPasswordFallback />}>
      <ResetPasswordContent />
    </Suspense>
  );
}

function ResetPasswordContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const passwordFlags = useMemo(
    () => getPasswordRequirementFlags(newPassword),
    [newPassword],
  );

  const tokenError = token ? null : "Reset link is missing or invalid.";

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!newPassword || !confirmPassword) {
      setError("Please fill in both password fields.");
      return;
    }
    if (!isPasswordPolicyValid(newPassword)) {
      setError(PASSWORD_POLICY_ERROR_MESSAGE);
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setSaving(true);
    try {
      const response = await shayApi.resetPassword({
        token,
        new_password: newPassword,
        confirm_new_password: confirmPassword,
        encrypted: false,
      });

      if (!response.success) {
        throw new Error(response.message || "Password reset failed.");
      }

      setSuccess(response.message || "Password has been reset successfully.");
      setTimeout(() => {
        router.push("/login");
      }, 1600);
    } catch (nextError: unknown) {
      setError(nextError instanceof Error ? nextError.message : "Password reset failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(64,104,168,0.18),_transparent_30%),linear-gradient(145deg,_#1e5f95,_#2a78ba_55%,_#5b95d0)] px-6 py-10">
      <div className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-md items-center justify-center">
        <div className="w-full">
          <div className="text-center">
            <div className="inline-flex rounded-full bg-white px-5 py-3 shadow-lg">
              <Logo size={42} withWordmark />
            </div>
            <p className="mt-5 text-sm font-medium text-white/88">
              Set a fresh password for your Aryx workspace
            </p>
          </div>

          <div className="mt-8 rounded-[2rem] bg-white p-8 shadow-[0_24px_70px_rgba(10,21,48,0.22)]">
            <div className="text-center">
              <div className="mx-auto flex size-16 items-center justify-center rounded-full bg-[linear-gradient(135deg,_#2a78ba,_#0F1F3D)] text-white">
                {tokenError ? <AlertTriangle size={28} /> : <KeyRound size={28} />}
              </div>
              <h1 className="mt-5 text-4xl font-semibold text-navy-900">
                {tokenError ? "Reset Link Issue" : "Reset Password"}
              </h1>
              <p className="mt-3 text-sm text-subtle">
                {tokenError
                  ? tokenError
                  : "Choose a new password for your Aryx account."}
              </p>
            </div>

            {tokenError ? (
              <div className="mt-8 text-center">
                <Link
                  href="/forgot-password"
                  className="text-sm font-semibold text-steel-700 transition-colors hover:text-navy-900"
                >
                  Request a new reset link
                </Link>
              </div>
            ) : success ? (
              <div className="mt-8 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-6 text-center text-sm text-emerald-700">
                {success}
              </div>
            ) : (
              <ResetForm
                newPassword={newPassword}
                confirmPassword={confirmPassword}
                showNewPassword={showNewPassword}
                showConfirmPassword={showConfirmPassword}
                saving={saving}
                error={error}
                passwordFlags={passwordFlags}
                onNewPasswordChange={setNewPassword}
                onConfirmPasswordChange={setConfirmPassword}
                onToggleShowNewPassword={() => setShowNewPassword((value) => !value)}
                onToggleShowConfirmPassword={() => setShowConfirmPassword((value) => !value)}
                onSubmit={submit}
              />
            )}

            <div className="mt-7 border-t border-navy-100 pt-6 text-center">
              <Link
                href="/login"
                className="text-sm font-semibold text-steel-700 transition-colors hover:text-navy-900"
              >
                Back to Login
              </Link>
            </div>
          </div>

          <p className="mt-6 text-center text-sm text-white/82">
            © {new Date().getFullYear()} Aryx. All rights reserved.
          </p>
        </div>
      </div>
    </div>
  );
}
