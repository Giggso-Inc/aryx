import { NextRequest, NextResponse } from "next/server";

import {
  aryxTarget,
  requireInternalApiKey,
  requireShayBearerAuth,
} from "../../../../../_aryxProxy";

function forwardHeaders() {
  const headers = new Headers();
  const internalApiKey = requireInternalApiKey();
  if (internalApiKey instanceof NextResponse) return internalApiKey;
  headers.set("x-aryx-api-key", internalApiKey);
  return headers;
}

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ shayWorkspaceId: string }> },
) {
  const auth = await requireShayBearerAuth(req);
  if (auth instanceof NextResponse) {
    return auth;
  }
  const headers = forwardHeaders();
  if (headers instanceof NextResponse) return headers;

  const { shayWorkspaceId } = await context.params;
  try {
    const upstream = await fetch(`${aryxTarget()}/admin/shay/workspaces/${shayWorkspaceId}/mapping`, {
      method: "GET",
      headers,
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
