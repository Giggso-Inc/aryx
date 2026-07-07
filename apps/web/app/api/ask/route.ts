import { NextRequest, NextResponse } from "next/server";
import { Agent, fetch as undiciFetch } from "undici";

/**
 * Proxy for /ask — CPU LLM inference (Ollama llama3.2:3b) takes 90–300+ seconds.
 *
 * WHY undici Agent instead of global fetch + AbortSignal:
 * Node's global fetch (undici under the hood) has a hardcoded default
 * headersTimeout of 300 s that AbortSignal.timeout() does NOT override.
 * When the ask pipeline crosses 5 minutes (large graphs, complex questions),
 * undici kills the socket and throws "fetch failed" (ECONNRESET) — even though
 * FastAPI is still running and will eventually persist the answer to history.
 *
 * The fix: pass an explicit undici Agent with headersTimeout and bodyTimeout
 * both raised to 900 s. AbortSignal is kept as the outer ceiling (15 min) so
 * runaway requests are still cancelled.
 *
 * Trust model: for production deployments exposed via a reverse proxy, set
 * ARYX_PROXY_SECRET and configure the proxy to inject the x-aryx-key header.
 */

// Module-level singleton — allocated once, reused across requests.
const slowLlmAgent = new Agent({
  headersTimeout: 900_000,   // wait up to 15 min for first response byte
  bodyTimeout: 900_000,      // wait up to 15 min for full response body
  keepAliveTimeout: 10_000,
});

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
    const upstream = await undiciFetch(`${target}/ask`, {
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
