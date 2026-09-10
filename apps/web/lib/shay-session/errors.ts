export class HttpStatusError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "HttpStatusError";
    this.status = status;
  }
}

function detailFromPayload(payload: unknown): string {
  if (typeof payload === "string") return payload;
  if (!payload || typeof payload !== "object") return "Request failed";
  const value = payload as Record<string, unknown>;
  if (typeof value.message === "string") return value.message;
  if (typeof value.detail === "string") return value.detail;
  if (value.detail && typeof value.detail === "object") {
    return detailFromPayload(value.detail);
  }
  return JSON.stringify(payload);
}

export function createHttpStatusError(
  status: number,
  statusText: string,
  detail = "",
) {
  return new HttpStatusError(
    status,
    detail ? `${status} ${statusText}: ${detail}` : `${status} ${statusText}`,
  );
}

export function isHttpStatusError(error: unknown, status?: number) {
  return error instanceof HttpStatusError
    && (status === undefined || error.status === status);
}

export async function readErrorDetail(response: Response) {
  const text = await response.text().catch(() => "");
  if (!text) {
    return "";
  }
  try {
    return detailFromPayload(JSON.parse(text));
  } catch {
    return text;
  }
}
