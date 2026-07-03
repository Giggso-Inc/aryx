"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2, Shield } from "lucide-react";
import { useShayAuth } from "@/lib/shay-auth";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { ready, session } = useShayAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!ready || session) return;
    const next = pathname && pathname !== "/" ? `?next=${encodeURIComponent(pathname)}` : "";
    router.replace(`/login${next}`);
  }, [pathname, ready, router, session]);

  if (!ready || !session) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-6">
        <div className="rounded-3xl border border-navy-100 bg-white px-8 py-10 text-center shadow-soft">
          <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-navy-50 text-navy-700">
            {ready ? <Shield size={20} /> : <Loader2 size={20} className="animate-spin" />}
          </div>
          <h1 className="mt-4 font-display text-2xl text-navy-900">
            Opening your Aryx workspace
          </h1>
          <p className="mt-2 max-w-sm text-sm text-subtle">
            We are checking your session and routing you to the right authenticated surface.
          </p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
