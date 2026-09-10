import type { FormEvent } from "react";
import { AlertCircle, Eye, EyeOff, Lock, Mail, User } from "lucide-react";
import { PasswordRequirements } from "@/components/auth/PasswordRequirements";
import { PASSWORD_REQUIREMENT_LABELS } from "@/lib/password-policy";
import { Field } from "./Field";
import { RegisterFooter } from "./RegisterFooter";

export function RegisterForm({
  name,
  email,
  password,
  confirmPassword,
  encryptedInvite,
  inviteId,
  showPassword,
  showConfirmPassword,
  saving,
  inviteLoaded,
  error,
  passwordFlags,
  onNameChange,
  onEmailChange,
  onPasswordChange,
  onConfirmPasswordChange,
  onToggleShowPassword,
  onToggleShowConfirmPassword,
  onError,
  onSubmit,
}: {
  name: string;
  email: string;
  password: string;
  confirmPassword: string;
  encryptedInvite: string;
  inviteId: string;
  showPassword: boolean;
  showConfirmPassword: boolean;
  saving: boolean;
  inviteLoaded: boolean;
  error: string | null;
  passwordFlags: readonly boolean[];
  onNameChange: (value: string) => void;
  onEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onConfirmPasswordChange: (value: string) => void;
  onToggleShowPassword: () => void;
  onToggleShowConfirmPassword: () => void;
  onError: (message: string | null) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <>
      <form onSubmit={onSubmit} className="mt-8 space-y-5">
        <Field label="Full Name" required icon={<User size={18} />}>
          <input
            value={name}
            onChange={(event) => onNameChange(event.target.value)}
            placeholder="John Doe"
            className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 text-sm text-navy-900 placeholder:text-slate-400"
          />
        </Field>

        <Field
          label="Email Address"
          required
          icon={<Mail size={18} />}
          note={encryptedInvite ? "This email was prefilled from your secure invitation and cannot be changed." : undefined}
        >
          <input
            type="email"
            value={email}
            onChange={(event) => onEmailChange(event.target.value)}
            placeholder="shay@giggso.com"
            className={[
              "focus-ring h-12 w-full rounded-xl border px-12 text-sm text-navy-900 placeholder:text-slate-400",
              encryptedInvite ? "border-blue-100 bg-blue-50/70" : "border-navy-100 bg-white",
              encryptedInvite ? "cursor-not-allowed" : "",
            ].join(" ")}
            readOnly={Boolean(encryptedInvite)}
            aria-readonly={Boolean(encryptedInvite)}
          />
        </Field>

        <Field label="Password" required icon={<Lock size={18} />}>
          <input
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(event) => onPasswordChange(event.target.value)}
            placeholder="Password"
            className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 pr-12 text-sm text-navy-900 placeholder:text-slate-400"
          />
          <button
            type="button"
            onClick={onToggleShowPassword}
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
            onChange={(event) => onConfirmPasswordChange(event.target.value)}
            placeholder="Confirm Password"
            className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 pr-12 text-sm text-navy-900 placeholder:text-slate-400"
          />
          <button
            type="button"
            onClick={onToggleShowConfirmPassword}
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
          disabled={!inviteLoaded || !email.trim() || !name.trim() || !password || !confirmPassword || saving}
          className="focus-ring inline-flex h-12 w-full items-center justify-center rounded-2xl bg-navy-800 text-sm font-semibold text-white shadow-lg shadow-navy-900/20 transition-transform hover:-translate-y-0.5 hover:bg-navy-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {saving ? "Creating account..." : "Create account"}
        </button>
      </form>

      <RegisterFooter inviteId={inviteId} onError={onError} />
    </>
  );
}
