import { NextRequest, NextResponse } from "next/server";
import { Agent, fetch as undiciFetch } from "undici";

import {
  aryxTarget,
  requireInternalApiKey,
  requireShayWorkspaceAccess,
} from "../../../_aryxProxy";

const slowLlmAgent = new Agent({
  headersTimeout: 900_000,
  bodyTimeout: 900_000,
  keepAliveTimeout: 10_000,
});

process.once("SIGTERM", () => slowLlmAgent.close());
process.once("SIGINT", () => slowLlmAgent.close());

function readShayWorkspaceId(body: string): string | null {
  try {
    const payload = JSON.parse(body) as { shay_workspace_id?: unknown };
    return typeof payload.shay_workspace_id === "string"
      ? payload.shay_workspace_id
      : null;
  } catch {
    return null;
  }
}

export async function POST(req: NextRequest) {
  const body = await req.text();
  const auth = await requireShayWorkspaceAccess(req, readShayWorkspaceId(body));
  if (auth instanceof NextResponse) {
    return auth;
  }

  const internalApiKey = requireInternalApiKey();
  if (internalApiKey instanceof NextResponse) {
    return internalApiKey;
  }

  try {
    const upstream = await undiciFetch(`${aryxTarget()}/ask/threads/message`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-aryx-api-key": internalApiKey,
      },
      body,
      signal: AbortSignal.timeout(900_000),
      dispatcher: slowLlmAgent,
    });
    const data = await upstream.text();
    return new NextResponse(data, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch (err) {
    console.error(
      JSON.stringify({
        route: "ask/threads/message/proxy",
        error: err instanceof Error ? err.message : String(err),
      }),
    );
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "upstream error" },
      { status: 502 },
    );
  }
}
