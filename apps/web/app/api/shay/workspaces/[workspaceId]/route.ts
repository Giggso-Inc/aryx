import { NextRequest, NextResponse } from "next/server";

import {
  aryxTarget,
  attachWorkspaceBridge,
  forwardHeaders,
  jsonResponse,
  readJsonOrThrow,
  shayTarget,
  type WorkspacePayload,
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
    const workspace = await readJsonOrThrow<WorkspacePayload>(upstream);
    return jsonResponse(await attachWorkspaceBridge(req, workspace), upstream.status);
  } catch (error) {
    return jsonResponse(
      { detail: error instanceof Error ? error.message : "Workspace proxy failed" },
      502,
    );
  }
}

async function deleteWorkspace(req: NextRequest, workspaceId: string) {
  try {
    let aryxWorkspaceId: number | null = null;
    const mappingResponse = await fetch(
      `${aryxTarget()}/admin/shay/workspaces/${workspaceId}/mapping`,
      {
        method: "GET",
        headers: forwardHeaders(req),
        cache: "no-store",
      },
    );
    if (mappingResponse.ok) {
      const mapping = await readJsonOrThrow<{ aryx_workspace_id: number }>(mappingResponse);
      aryxWorkspaceId = mapping.aryx_workspace_id;
    }

    const shayResponse = await fetch(`${shayTarget()}/api/v1/workspaces/${workspaceId}`, {
      method: "DELETE",
      headers: forwardHeaders(req),
      cache: "no-store",
    });
    const shayBody = await readJsonOrThrow<Record<string, unknown>>(shayResponse);

    if (aryxWorkspaceId !== null) {
      const aryxResponse = await fetch(`${aryxTarget()}/admin/workspaces/${aryxWorkspaceId}`, {
        method: "DELETE",
        headers: forwardHeaders(req),
        cache: "no-store",
      });
      await readJsonOrThrow<Record<string, unknown>>(aryxResponse);
    }

    return jsonResponse(shayBody, shayResponse.status);
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
  return deleteWorkspace(req, workspaceId);
}
