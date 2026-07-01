import { NextRequest } from "next/server";

import { forwardHeaders, jsonResponse, shayTarget } from "../../_shared";

async function proxy(req: NextRequest, workspaceId: string) {
  try {
    const body = req.method === "GET" ? undefined : await req.text();
    const upstream = await fetch(`${shayTarget()}/api/v1/gg-workspaces/${workspaceId}/members`, {
      method: req.method,
      headers: forwardHeaders(req),
      body,
      cache: "no-store",
    });
    const responseBody = await upstream.text();
    return new Response(responseBody, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch (error) {
    return jsonResponse(
      { detail: error instanceof Error ? error.message : "Workspace member proxy failed" },
      502,
    );
  }
}

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ workspaceId: string }> },
) {
  const { workspaceId } = await context.params;
  return proxy(req, workspaceId);
}

export async function POST(
  req: NextRequest,
  context: { params: Promise<{ workspaceId: string }> },
) {
  const { workspaceId } = await context.params;
  return proxy(req, workspaceId);
}
