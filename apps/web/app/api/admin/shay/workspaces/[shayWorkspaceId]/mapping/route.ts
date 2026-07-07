import { NextRequest, NextResponse } from "next/server";

function target() {
  return process.env.NODE_ENV === "development"
    ? "http://localhost:8088"
    : process.env.ARYX_API_URL_INTERNAL ?? "http://api:8000";
}

function forwardHeaders(req: NextRequest) {
  const headers = new Headers();
  const internalApiKey = process.env.ARYX_INTERNAL_API_KEY;
  if (internalApiKey) {
    headers.set("x-aryx-api-key", internalApiKey);
  }
  return headers;
}

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ shayWorkspaceId: string }> },
) {
  const secret = process.env.ARYX_PROXY_SECRET;
  if (!secret) {
    return NextResponse.json({ detail: "ARYX_PROXY_SECRET is not configured" }, { status: 500 });
  }
  if (req.headers.get("x-aryx-key") !== secret) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }
  if (!process.env.ARYX_INTERNAL_API_KEY) {
    return NextResponse.json({ detail: "ARYX_INTERNAL_API_KEY is not configured" }, { status: 500 });
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
