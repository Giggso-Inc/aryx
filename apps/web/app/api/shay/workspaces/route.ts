import { NextRequest, NextResponse } from "next/server";

function shayTarget() {
  return process.env.NODE_ENV === "development"
    ? "http://localhost:8090"
    : process.env.SHAY_API_URL_INTERNAL ?? "http://shay-api:8000";
}

function forwardHeaders(req: NextRequest) {
  const headers = new Headers();
  const authorization = req.headers.get("authorization");
  const contentType = req.headers.get("content-type");
  if (authorization) {
    headers.set("Authorization", authorization);
  }
  if (contentType) {
    headers.set("Content-Type", contentType);
  }
  return headers;
}

export async function GET(req: NextRequest) {
  try {
    const upstream = await fetch(`${shayTarget()}/api/v1/workspaces/`, {
      method: "GET",
      headers: forwardHeaders(req),
      cache: "no-store",
    });
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Workspace proxy failed" },
      { status: 502 },
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
    const responseBody = await upstream.text();
    return new NextResponse(responseBody, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Workspace proxy failed" },
      { status: 502 },
    );
  }
}
