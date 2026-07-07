import { NextRequest, NextResponse } from "next/server";

/**
 * Proxy for /ask — CPU LLM inference (Ollama llama3.2:3b) takes 90+ seconds,
 * which exceeds Node.js fetch's default socket timeout and triggers a 502 in
 * deployed environments. AbortSignal.timeout(900_000) gives a 15-minute ceiling
 * so the request survives the full synthesis cycle.
 *
 * Trust model: these routes are only accessible from the browser via
 * same-origin requests. For production deployments exposed publicly, set
 * ARYX_PROXY_SECRET and configure your reverse proxy to inject the
 * x-aryx-key header — unauthenticated direct calls will be rejected.
 */
export async function POST(req: NextRequest) {
  const secret = process.env.ARYX_PROXY_SECRET;
  if (secret && req.headers.get("x-aryx-key") !== secret) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }
  const internalApiKey = process.env.ARYX_INTERNAL_API_KEY;
  if (!internalApiKey) {
    return NextResponse.json({ detail: "ARYX_INTERNAL_API_KEY is not configured" }, { status: 500 });
  }

  const target =
    process.env.NODE_ENV === "development"
      ? "http://localhost:8088"
      : process.env.ARYX_API_URL_INTERNAL ?? "http://api:8000";
  const body = await req.text();
  try {
    const upstream = await fetch(`${target}/ask`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-aryx-api-key": internalApiKey,
      },
      body,
      signal: AbortSignal.timeout(900_000),
    });
    const data = await upstream.text();
    return new NextResponse(data, {
      status: upstream.status,
      headers: {
        "Content-Type":
          upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch (err) {
    console.error(JSON.stringify({ route: "ask/proxy", error: err instanceof Error ? err.message : String(err) }));
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "upstream error" },
      { status: 502 },
    );
  }
}
