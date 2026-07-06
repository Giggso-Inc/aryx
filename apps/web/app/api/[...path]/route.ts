import { NextRequest, NextResponse } from "next/server";

/**
 * Catch-all proxy for Aryx API calls. Specific route handlers (ask,
 * draft-brief, shay/*) take precedence over this handler because Next.js
 * resolves more-specific routes first. This handler covers everything else:
 * /data/*, /graph/*, /ontology/*, /admin/*, /rules/*, /entities/*, etc.
 *
 * Injects x-aryx-api-key so the Aryx API accepts the request. The
 * Next.js afterFiles rewrite cannot inject request headers, which is
 * why those routes returned 401 before this handler was added.
 */
async function proxy(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const internalApiKey = process.env.ARYX_INTERNAL_API_KEY;
  if (!internalApiKey) {
    return NextResponse.json(
      { detail: "ARYX_INTERNAL_API_KEY is not configured" },
      { status: 500 },
    );
  }

  const target =
    process.env.NODE_ENV === "development"
      ? "http://localhost:8088"
      : (process.env.ARYX_API_URL_INTERNAL ?? "http://api:8000");

  const { path: pathSegments } = await params;
  const path = pathSegments.join("/");
  const url = `${target}/${path}${req.nextUrl.search}`;

  const forwardHeaders: Record<string, string> = {
    "x-aryx-api-key": internalApiKey,
  };
  // Do NOT forward Authorization — Aryx validates Bearer tokens as API keys
  // (see security.py _has_authenticated_header). A Shay JWT forwarded here
  // shadows the x-aryx-api-key check and causes 401.
  const contentType = req.headers.get("Content-Type");
  if (contentType) forwardHeaders["Content-Type"] = contentType;

  const init: RequestInit = {
    method: req.method,
    headers: forwardHeaders,
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.arrayBuffer();
  }

  try {
    const upstream = await fetch(url, init);
    const responseHeaders = new Headers();
    const ct = upstream.headers.get("Content-Type");
    if (ct) responseHeaders.set("Content-Type", ct);
    const cd = upstream.headers.get("Content-Disposition");
    if (cd) responseHeaders.set("Content-Disposition", cd);
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (err) {
    console.error(
      JSON.stringify({
        route: `api-proxy/${path}`,
        error: err instanceof Error ? err.message : String(err),
      }),
    );
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "upstream error" },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
