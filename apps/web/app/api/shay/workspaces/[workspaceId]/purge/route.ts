import { NextRequest } from "next/server";

import { forwardHeaders, jsonResponse, readJsonOrThrow, shayTarget } from "../../_shared";

export async function POST(
  req: NextRequest,
  context: { params: Promise<{ workspaceId: string }> },
) {
  try {
    const { workspaceId } = await context.params;

    const purgeResponse = await fetch(
      `${shayTarget()}/api/v1/workspaces/${workspaceId}/purge`,
      {
        method: "POST",
        headers: forwardHeaders(req),
        body: "{}",
        cache: "no-store",
      },
    );
    const purgeResult = await readJsonOrThrow<Record<string, unknown>>(purgeResponse);

    return jsonResponse(purgeResult, purgeResponse.status);
  } catch (error) {
    return jsonResponse(
      { detail: error instanceof Error ? error.message : "Workspace purge proxy failed" },
      502,
    );
  }
}
