import { NextRequest, NextResponse } from "next/server";
import { Agent, fetch as undiciFetch } from "undici";

import {
  aryxTarget,
  requireInternalApiKey,
  requireShayBearerAuth,
} from "../_aryxProxy";

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
 * Trust model: browser calls must carry a valid Shay bearer token; this route
 * validates that token and then forwards the request to Aryx with the internal
 * service key only.
 */

// Module-level singleton — allocated once, reused across requests.
const slowLlmAgent = new Agent({
  headersTimeout: 900_000,   // wait up to 15 min for first response byte
  bodyTimeout: 900_000,      // wait up to 15 min for full response body
  keepAliveTimeout: 10_000,
});

// Drain keep-alive sockets on graceful shutdown so in-flight LLM requests are
// not cut mid-stream by Node's forced exit after SIGTERM.
process.once("SIGTERM", () => slowLlmAgent.close());
process.once("SIGINT",  () => slowLlmAgent.close());

export async function POST(req: NextRequest) {
  const auth = await requireShayBearerAuth(req);
  if (auth instanceof NextResponse) {
    return auth;
  }
  const internalApiKey = requireInternalApiKey();
  if (internalApiKey instanceof NextResponse) {
    return internalApiKey;
  }

  const body = await req.text();
  try {
    const upstream = await undiciFetch(`${aryxTarget()}/ask`, {
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
