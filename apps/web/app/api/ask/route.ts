import { NextRequest, NextResponse } from "next/server";

/**
 * Proxy for /ask — LLM-backed graph queries can take 10-30s, which exceeds
 * the default 30s TCP idle timeout in Docker WSL2 networking when routing
 * through the Next.js rewrite proxy. A proper route handler uses Node.js
 * undici fetch (no default timeout) and is not subject to socket reset.
 */
export async function POST(req: NextRequest) {
  const target = process.env.ARYX_API_URL_INTERNAL ?? "http://api:8000";
  const body = await req.text();
  try {
    const upstream = await fetch(`${target}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
    console.error("[ask proxy]", err);
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "upstream error" },
      { status: 502 },
    );
  }
}
