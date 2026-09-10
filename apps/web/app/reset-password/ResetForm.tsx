import type { FormEvent } from "react";
import { Eye, EyeOff, Lock } from "lucide-react";
import { PasswordRequirements } from "@/components/auth/PasswordRequirements";
import { PASSWORD_REQUIREMENT_LABELS } from "@/lib/password-policy";

export function ResetForm({
  newPassword,
  confirmPassword,
  showNewPassword,
  showConfirmPassword,
  saving,
  error,
  passwordFlags,
  onNewPasswordChange,
  onConfirmPasswordChange,
  onToggleShowNewPassword,
  onToggleShowConfirmPassword,
  onSubmit,
}: {
  newPassword: string;
  confirmPassword: string;
  showNewPassword: boolean;
  showConfirmPassword: boolean;
  saving: boolean;
  error: string | null;
  passwordFlags: readonly boolean[];
  onNewPasswordChange: (value: string) => void;
  onConfirmPasswordChange: (value: string) => void;
  onToggleShowNewPassword: () => void;
  onToggleShowConfirmPassword: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="mt-8 space-y-5">
      <label className="block space-y-2">
        <span className="text-sm font-semibold text-navy-900">New Password</span>
        <div className="relative">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-4 text-subtle">
            <Lock size={18} />
          </div>
          <input
            type={showNewPassword ? "text" : "password"}
            value={newPassword}
            onChange={(event) => onNewPasswordChange(event.target.value)}
            placeholder="Enter your new password"
            className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 pr-12 text-sm text-navy-900 placeholder:text-slate-400"
          />
          <button
            type="button"
            onClick={onToggleShowNewPassword}
            className="absolute inset-y-0 right-0 pr-4 text-subtle transition-colors hover:text-navy-700"
          >
            {showNewPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>
      </label>

      <PasswordRequirements
        flags={passwordFlags}
        labels={PASSWORD_REQUIREMENT_LABELS}
      />

      <label className="block space-y-2">
        <span className="text-sm font-semibold text-navy-900">Confirm Password</span>
        <div className="relative">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-4 text-subtle">
            <Lock size={18} />
          </div>
          <input
            type={showConfirmPassword ? "text" : "password"}
            value={confirmPassword}
            onChange={(event) => onConfirmPasswordChange(event.target.value)}
            placeholder="Confirm your new password"
            className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 pr-12 text-sm text-navy-900 placeholder:text-slate-400"
          />
          <button
            type="button"
            onClick={onToggleShowConfirmPassword}
            className="absolute inset-y-0 right-0 pr-4 text-subtle transition-colors hover:text-navy-700"
          >
            {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>
      </label>

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
        {saving ? "Resetting..." : "Reset Password"}
      </button>
    </form>
  );
}
