import { NextRequest, NextResponse } from "next/server";

export type WorkspacePayload = {
  id: string;
  name: string;
  description?: string | null;
  company_id?: string | null;
  bridge?: WorkspaceBridge | null;
};

export type WorkspaceListPayload = {
  workspaces: WorkspacePayload[];
  total: number;
  page: number;
  size: number;
};

export type WorkspaceBridge = {
  shay_workspace_id: string;
  aryx_workspace_id: number;
  company_id?: string | null;
  sync_state?: Record<string, unknown>;
  created?: boolean;
};

export function shayTarget() {
  return process.env.NODE_ENV === "development"
    ? "http://localhost:8090"
    : process.env.SHAY_API_URL_INTERNAL ?? "http://shay-api:8000";
}

export function aryxTarget() {
  return process.env.NODE_ENV === "development"
    ? "http://localhost:8088"
    : process.env.ARYX_API_URL_INTERNAL ?? "http://api:8000";
}

export function forwardHeaders(req: NextRequest) {
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

export async function readJsonOrThrow<T>(response: Response): Promise<T> {
  const text = await response.text();
  if (!response.ok) {
    return Promise.reject(
      new Error(text || `${response.status} ${response.statusText}`),
    );
  }
  return JSON.parse(text) as T;
}

export function jsonResponse(payload: unknown, status = 200) {
  return NextResponse.json(payload, { status });
}
