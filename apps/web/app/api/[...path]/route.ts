import { NextRequest, NextResponse } from "next/server";

import {
  buildAryxForwardHeaders,
  requireInternalApiKey,
  requireShayBearerAuth,
  requireShayWorkspaceAccess,
  aryxTarget,
} from "../_aryxProxy";

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
  const auth = await requireShayBearerAuth(req);
  if (auth instanceof NextResponse) {
    return auth;
  }
  const internalApiKey = requireInternalApiKey();
  if (internalApiKey instanceof NextResponse) {
    return internalApiKey;
  }

  const { path: pathSegments } = await params;
  const path = pathSegments.join("/");
  if (path === "ask/threads" || path.startsWith("ask/threads/")) {
    const workspaceAuth = await requireShayWorkspaceAccess(
      req,
      req.nextUrl.searchParams.get("shay_workspace_id"),
    );
    if (workspaceAuth instanceof NextResponse) {
      return workspaceAuth;
    }
  }
  const url = `${aryxTarget()}/${path}${req.nextUrl.search}`;

  const init: RequestInit = {
    method: req.method,
    headers: buildAryxForwardHeaders(req, internalApiKey),
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
