import Link from "next/link";
import SsoProviderButtons from "@/components/auth/SsoProviderButtons";

export function RegisterFooter({
  inviteId,
  onError,
}: {
  inviteId: string;
  onError: (message: string | null) => void;
}) {
  return (
    <>
      <div className="mt-6 flex items-center gap-4 text-[11px] font-semibold uppercase tracking-[0.22em] text-subtle">
        <span className="h-px flex-1 bg-navy-100" />
        <span>OR</span>
        <span className="h-px flex-1 bg-navy-100" />
      </div>

      <div className="mt-6">
        <SsoProviderButtons
          inviteId={inviteId || undefined}
          onError={onError}
        />
      </div>

      <div className="mt-6 border-t border-navy-100 pt-6 text-center text-sm text-subtle">
        Already have an account?{" "}
        <Link href="/login" className="font-semibold text-navy-700 transition-colors hover:text-navy-900">
          Sign in
        </Link>
      </div>
    </>
  );
}
