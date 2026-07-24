import { NextRequest, NextResponse } from "next/server";

import {
  aryxTarget,
  requireInternalApiKey,
  requireShayBearerAuth,
} from "../../../../_aryxProxy";

function forwardHeaders(req: NextRequest) {
  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  const internalApiKey = requireInternalApiKey();
  if (internalApiKey instanceof NextResponse) return internalApiKey;
  if (contentType) headers.set("Content-Type", contentType);
  headers.set("x-aryx-api-key", internalApiKey);
  return headers;
}

export async function POST(req: NextRequest) {
  const auth = await requireShayBearerAuth(req);
  if (auth instanceof NextResponse) {
    return auth;
  }
  const headers = forwardHeaders(req);
  if (headers instanceof NextResponse) return headers;

  const body = await req.text();
  try {
    const upstream = await fetch(`${aryxTarget()}/admin/shay/workspaces/ensure`, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
    });
    const responseBody = await upstream.text();
    return new NextResponse(responseBody, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Workspace bridge proxy failed" },
      { status: 502 },
    );
  }
}
