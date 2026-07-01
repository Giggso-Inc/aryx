import { NextRequest, NextResponse } from "next/server";

import {
  attachWorkspaceBridge,
  attachWorkspaceBridges,
  forwardHeaders,
  jsonResponse,
  readJsonOrThrow,
  shayTarget,
  type WorkspaceListPayload,
  type WorkspacePayload,
} from "./_shared";

export async function GET(req: NextRequest) {
  try {
    const upstream = await fetch(`${shayTarget()}/api/v1/workspaces/`, {
      method: "GET",
      headers: forwardHeaders(req),
      cache: "no-store",
    });
    const body = await readJsonOrThrow<WorkspaceListPayload>(upstream);
    return jsonResponse(await attachWorkspaceBridges(req, body));
  } catch (error) {
    return jsonResponse(
      { detail: error instanceof Error ? error.message : "Workspace proxy failed" },
      502,
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.text();
    const upstream = await fetch(`${shayTarget()}/api/v1/workspaces/`, {
      method: "POST",
      headers: forwardHeaders(req),
      body,
      cache: "no-store",
    });
    const workspace = await readJsonOrThrow<WorkspacePayload>(upstream);
    return jsonResponse(await attachWorkspaceBridge(req, workspace), upstream.status);
  } catch (error) {
    return jsonResponse(
      { detail: error instanceof Error ? error.message : "Workspace proxy failed" },
      502,
    );
  }
}
