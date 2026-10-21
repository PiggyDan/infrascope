import type { ApiKeyInfo, CheckResult, Incident, Summary, Target, TargetInput } from "./types";

export const API_KEY_HEADER = "X-API-Key";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** FastAPI errors are either {detail: "text"} or {detail: [{loc, msg}, ...]} (422). */
export function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => {
          if (!item || typeof item !== "object") return null;
          const { loc, msg } = item as { loc?: unknown[]; msg?: string };
          const field = Array.isArray(loc) ? loc.filter((p) => p !== "body").join(".") : "";
          return msg ? (field ? `${field}: ${msg}` : msg) : null;
        })
        .filter(Boolean);
      if (messages.length) return messages.join("; ");
    }
  }
  return fallback;
}

export type ApiClient = ReturnType<typeof createClient>;

export function createClient(apiKey: string, fetchImpl: typeof fetch = fetch.bind(globalThis)) {
  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { [API_KEY_HEADER]: apiKey };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const response = await fetchImpl(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (response.status === 204) return undefined as T;
    const data: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      throw new ApiError(
        response.status,
        errorMessage(data, `${response.status} ${response.statusText}`),
      );
    }
    return data as T;
  }

  return {
    me: () => request<ApiKeyInfo>("GET", "/api/v1/auth/me"),
    summary: () => request<Summary>("GET", "/api/v1/summary"),
    targets: () => request<Target[]>("GET", "/api/v1/targets?limit=500"),
    results: (targetId: string, limit = 100) =>
      request<CheckResult[]>(
        "GET",
        `/api/v1/targets/${encodeURIComponent(targetId)}/results?limit=${limit}`,
      ),
    incidents: (limit = 50) => request<Incident[]>("GET", `/api/v1/incidents?limit=${limit}`),
    createTarget: (input: TargetInput) => request<Target>("POST", "/api/v1/targets", input),
    updateTarget: (targetId: string, changes: Partial<TargetInput & { enabled: boolean }>) =>
      request<Target>("PATCH", `/api/v1/targets/${encodeURIComponent(targetId)}`, changes),
    deleteTarget: (targetId: string) =>
      request<void>("DELETE", `/api/v1/targets/${encodeURIComponent(targetId)}`),
  };
}
