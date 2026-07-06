import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Inject x-aryx-api-key for all /api/* requests that are rewritten to the
// Aryx FastAPI backend. next.config.mjs rewrites don't carry headers, so
// middleware is the only place server-side env vars can reach the upstream.
//
// Applies only to paths matched by the Aryx rewrite (/api/:path*).
// Shay-api routes (/api/shay/*) receive the header too but ignore it — harmless.
// Next.js route handlers (app/api/**) already add the key themselves.
export function middleware(request: NextRequest) {
  const internalApiKey = process.env.ARYX_INTERNAL_API_KEY;
  if (!internalApiKey) {
    return NextResponse.next();
  }
  const headers = new Headers(request.headers);
  headers.set("x-aryx-api-key", internalApiKey);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/api/:path*"],
};
