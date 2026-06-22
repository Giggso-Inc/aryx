import { NextRequest, NextResponse } from "next/server";

/**
 * Proxy handler for the long-running draft-brief endpoint.
 *
 * The Next.js rewrite proxy gets ECONNRESET on long LLM calls because the
 * rewrite mechanism uses a streaming socket that can be reset mid-response.
 * A proper route handler uses Node.js `fetch` (undici) which buffers the full
 * response and is not subject to the same socket reset issue.
 */
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ workspace_id: string }> },
) {
  const secret = process.env.ARYX_PROXY_SECRET;
  if (secret && req.headers.get("x-aryx-key") !== secret) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  const { workspace_id } = await params;
  const target = process.env.ARYX_API_URL_INTERNAL ?? "http://api:8000";
  const body = await req.text();

  try {
    const upstream = await fetch(
      `${target}/admin/workspaces/${workspace_id}/draft-brief`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        // undici (Node.js built-in fetch) has no default timeout — safe for
        // LLM calls that may take 30-90 s depending on model and hardware.
      },
    );
    const data = await upstream.text();
    return new NextResponse(data, {
      status: upstream.status,
      headers: {
        "Content-Type":
          upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch (err) {
    console.error(JSON.stringify({ route: "draft-brief/proxy", error: err instanceof Error ? err.message : String(err) }));
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "upstream error" },
      { status: 502 },
    );
  }
}
