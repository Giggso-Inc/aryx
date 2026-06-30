import { NextRequest, NextResponse } from "next/server";

/**
 * Proxy for /ask — LLM-backed graph queries can take 10-30s, which exceeds
 * the default 30s TCP idle timeout in Docker WSL2 networking when routing
 * through the Next.js rewrite proxy. A proper route handler uses Node.js
 * undici fetch (no default timeout) and is not subject to socket reset.
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

  const target =
    process.env.NODE_ENV === "development"
      ? "http://localhost:8088"
      : process.env.ARYX_API_URL_INTERNAL ?? "http://api:8000";
  const body = await req.text();
  try {
    const authorization = req.headers.get("authorization");
    const upstream = await fetch(`${target}/ask`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authorization ? { Authorization: authorization } : {}),
      },
      body,
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
