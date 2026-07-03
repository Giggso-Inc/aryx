import { NextRequest } from "next/server";

import {
  forwardHeaders,
  jsonResponse,
  readJsonOrThrow,
  shayTarget,
} from "../_shared";

async function proxyWorkspace(req: NextRequest, workspaceId: string) {
  try {
    const body = req.method === "GET" || req.method === "DELETE"
      ? undefined
      : await req.text();
    const upstream = await fetch(`${shayTarget()}/api/v1/workspaces/${workspaceId}`, {
      method: req.method,
      headers: forwardHeaders(req),
      body,
      cache: "no-store",
    });
    const payload = await readJsonOrThrow<Record<string, unknown>>(upstream);
    return jsonResponse(payload, upstream.status);
  } catch (error) {
    return jsonResponse(
      { detail: error instanceof Error ? error.message : "Workspace proxy failed" },
      502,
    );
  }
}

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ workspaceId: string }> },
) {
  const { workspaceId } = await context.params;
  return proxyWorkspace(req, workspaceId);
}

export async function PUT(
  req: NextRequest,
  context: { params: Promise<{ workspaceId: string }> },
) {
  const { workspaceId } = await context.params;
  return proxyWorkspace(req, workspaceId);
}

export async function DELETE(
  req: NextRequest,
  context: { params: Promise<{ workspaceId: string }> },
) {
  const { workspaceId } = await context.params;
  return proxyWorkspace(req, workspaceId);
}
