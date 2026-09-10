import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";
import SsoProviderButtons from "@/components/auth/SsoProviderButtons";

export function LoginForm({
  email,
  password,
  showPassword,
  saving,
  error,
  mcpCallback,
  onEmailChange,
  onPasswordChange,
  onToggleShowPassword,
  onSubmit,
  onError,
}: {
  email: string;
  password: string;
  showPassword: boolean;
  saving: boolean;
  error: string | null;
  mcpCallback: string;
  onEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onToggleShowPassword: () => void;
  onSubmit: () => void;
  onError: (message: string | null) => void;
}) {
  return (
    <section className="rounded-[2rem] border border-navy-100 bg-white p-7 shadow-soft">
      <h2 className="mt-4 text-3xl font-semibold text-navy-900">Welcome back</h2>
      <p className="mt-2 text-sm text-subtle">
        Sign in with your Aryx credentials or continue with Google or Microsoft.
      </p>
      <div className="mt-6 space-y-3">
        <input
          value={email}
          onChange={(event) => onEmailChange(event.target.value)}
          placeholder="Email address"
          className="focus-ring w-full rounded-2xl border border-navy-100 px-4 py-3 text-sm text-navy-900"
        />
        <div className="relative">
          <input
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(event) => onPasswordChange(event.target.value)}
            placeholder="Password"
            className="focus-ring w-full rounded-2xl border border-navy-100 px-4 py-3 pr-12 text-sm text-navy-900"
            onKeyDown={(event) => {
              if (event.key === "Enter" && !saving) onSubmit();
            }}
          />
          <button
            type="button"
            onClick={onToggleShowPassword}
            className="focus-ring absolute right-3 top-1/2 inline-flex size-8 -translate-y-1/2 items-center justify-center rounded-full text-navy-500 hover:bg-navy-50 hover:text-navy-800"
            aria-label={showPassword ? "Hide password" : "Show password"}
            title={showPassword ? "Hide password" : "Show password"}
          >
            {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
          </button>
        </div>
        <div className="flex justify-end">
          <Link
            href="/forgot-password"
            className="text-sm font-medium text-navy-700 underline underline-offset-4 transition-colors hover:text-navy-900"
          >
            Forgot password?
          </Link>
        </div>
        <button
          type="button"
          onClick={onSubmit}
          disabled={!email.trim() || !password || saving}
          className="focus-ring inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-navy-800 px-4 py-3 text-sm font-semibold text-white hover:bg-navy-700 disabled:opacity-50"
        >
          {saving ? "Signing in..." : "Login"}
        </button>
        {error ? (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        ) : null}
      </div>
      <div className="mt-6 flex items-center gap-4 text-[11px] font-semibold uppercase tracking-[0.22em] text-subtle">
        <span className="h-px flex-1 bg-navy-100" />
        <span>OR</span>
        <span className="h-px flex-1 bg-navy-100" />
      </div>
      <div className="mt-6">
        <SsoProviderButtons
          onError={onError}
          mcpCallback={mcpCallback || undefined}
        />
      </div>
      <div className="mt-6 text-center text-sm text-subtle">
        If you don&apos;t have an account,&nbsp;
        <Link
          href="/company-signup"
          className="font-medium text-navy-700 underline underline-offset-4 hover:text-navy-900"
        >
          Sign Up
        </Link>
      </div>
    </section>
  );
}
