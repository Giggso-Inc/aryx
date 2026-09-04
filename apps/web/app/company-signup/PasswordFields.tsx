import { Eye, EyeOff, Lock } from "lucide-react";
import { PasswordRequirements } from "@/components/auth/PasswordRequirements";
import { PASSWORD_REQUIREMENT_LABELS } from "@/lib/password-policy";
import { Field } from "./Field";

interface FormErrors {
  password?: string;
  confirmPassword?: string;
}

export function PasswordFields({
  password,
  confirmPassword,
  showPassword,
  showConfirmPassword,
  errors,
  passwordFlags,
  onPasswordChange,
  onConfirmPasswordChange,
  onToggleShowPassword,
  onToggleShowConfirmPassword,
}: {
  password: string;
  confirmPassword: string;
  showPassword: boolean;
  showConfirmPassword: boolean;
  errors: FormErrors;
  passwordFlags: readonly boolean[];
  onPasswordChange: (value: string) => void;
  onConfirmPasswordChange: (value: string) => void;
  onToggleShowPassword: () => void;
  onToggleShowConfirmPassword: () => void;
}) {
  return (
    <>
      <Field
        label="Password"
        required
        error={errors.password}
        icon={<Lock size={18} />}
        trailing={(
          <button
            type="button"
            onClick={onToggleShowPassword}
            className="text-subtle transition-colors hover:text-navy-700"
          >
            {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        )}
      >
        <input
          type={showPassword ? "text" : "password"}
          value={password}
          onChange={(event) => onPasswordChange(event.target.value)}
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
            onClick={onToggleShowConfirmPassword}
            className="text-subtle transition-colors hover:text-navy-700"
          >
            {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        )}
      >
        <input
          type={showConfirmPassword ? "text" : "password"}
          value={confirmPassword}
          onChange={(event) => onConfirmPasswordChange(event.target.value)}
          placeholder="Confirm your password"
          className="focus-ring h-12 w-full rounded-xl border border-navy-100 px-12 pr-12 text-sm text-navy-900 placeholder:text-slate-400"
        />
      </Field>
    </>
  );
}
