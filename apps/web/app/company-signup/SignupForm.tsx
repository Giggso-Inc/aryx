import type { FormEvent } from "react";
import { BasicInfoFields } from "./BasicInfoFields";
import { PasswordFields } from "./PasswordFields";

interface FormErrors {
  companyName?: string;
  domain?: string;
  contactEmail?: string;
  userName?: string;
  password?: string;
  confirmPassword?: string;
}

export function SignupForm({
  companyName,
  domain,
  userName,
  contactEmail,
  password,
  confirmPassword,
  showPassword,
  showConfirmPassword,
  saving,
  errors,
  error,
  passwordFlags,
  onCompanyNameChange,
  onDomainChange,
  onUserNameChange,
  onContactEmailChange,
  onPasswordChange,
  onConfirmPasswordChange,
  onToggleShowPassword,
  onToggleShowConfirmPassword,
  onSubmit,
}: {
  companyName: string;
  domain: string;
  userName: string;
  contactEmail: string;
  password: string;
  confirmPassword: string;
  showPassword: boolean;
  showConfirmPassword: boolean;
  saving: boolean;
  errors: FormErrors;
  error: string | null;
  passwordFlags: readonly boolean[];
  onCompanyNameChange: (value: string) => void;
  onDomainChange: (value: string) => void;
  onUserNameChange: (value: string) => void;
  onContactEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onConfirmPasswordChange: (value: string) => void;
  onToggleShowPassword: () => void;
  onToggleShowConfirmPassword: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="mt-10 space-y-5">
      <BasicInfoFields
        companyName={companyName}
        domain={domain}
        userName={userName}
        contactEmail={contactEmail}
        errors={errors}
        onCompanyNameChange={onCompanyNameChange}
        onDomainChange={onDomainChange}
        onUserNameChange={onUserNameChange}
        onContactEmailChange={onContactEmailChange}
      />

      <PasswordFields
        password={password}
        confirmPassword={confirmPassword}
        showPassword={showPassword}
        showConfirmPassword={showConfirmPassword}
        errors={errors}
        passwordFlags={passwordFlags}
        onPasswordChange={onPasswordChange}
        onConfirmPasswordChange={onConfirmPasswordChange}
        onToggleShowPassword={onToggleShowPassword}
        onToggleShowConfirmPassword={onToggleShowConfirmPassword}
      />

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
  );
}
