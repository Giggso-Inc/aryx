import { NextRequest, NextResponse } from "next/server";

function target() {
  return process.env.NODE_ENV === "development"
    ? "http://localhost:8088"
    : process.env.ARYX_API_URL_INTERNAL ?? "http://api:8000";
}

function forwardHeaders(req: NextRequest) {
  const headers = new Headers();
  const authorization = req.headers.get("authorization");
  if (authorization) {
    headers.set("Authorization", authorization);
  }
  return headers;
}

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ shayWorkspaceId: string }> },
) {
  const secret = process.env.ARYX_PROXY_SECRET;
  if (secret && req.headers.get("x-aryx-key") !== secret) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  const { shayWorkspaceId } = await context.params;
  try {
    const upstream = await fetch(`${target()}/admin/shay/workspaces/${shayWorkspaceId}/mapping`, {
      method: "GET",
      headers: forwardHeaders(req),
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
