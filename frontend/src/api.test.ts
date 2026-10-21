import { describe, expect, it, vi } from "vitest";

import { API_KEY_HEADER, ApiError, createClient, errorMessage } from "./api";
import { sortIncidents } from "./components/IncidentsPanel";
import type { Incident } from "./types";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("createClient", () => {
  it("sends the API key on every request", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, []));
    await createClient("isk_test", fetchMock).targets();
    const [path, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe("/api/v1/targets?limit=500");
    expect((init.headers as Record<string, string>)[API_KEY_HEADER]).toBe("isk_test");
  });

  it("sends JSON bodies for writes", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(201, { id: "1" }));
    await createClient("k", fetchMock).createTarget({ name: "a", url: "http://testtarget/", interval_seconds: 5 });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ name: "a", url: "http://testtarget/", interval_seconds: 5 });
  });

  it("handles 204 No Content", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    await expect(createClient("k", fetchMock).deleteTarget("abc")).resolves.toBeUndefined();
  });

  it("escapes ids in paths", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, []));
    await createClient("k", fetchMock).results("../api-keys", 5);
    const [path] = fetchMock.mock.calls[0] as unknown as [string];
    expect(path).toBe("/api/v1/targets/..%2Fapi-keys/results?limit=5");
  });

  it("raises ApiError with the server's detail", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(422, { detail: "URL rejected: host 'x' is not in the monitoring allowlist" }));
    const call = createClient("k", fetchMock).createTarget({ name: "a", url: "http://x/", interval_seconds: 5 });
    await expect(call).rejects.toBeInstanceOf(ApiError);
    await expect(call).rejects.toMatchObject({ status: 422, message: expect.stringContaining("allowlist") });
  });
});

describe("errorMessage", () => {
  it("reads string and validation-list details", () => {
    expect(errorMessage({ detail: "nope" }, "fb")).toBe("nope");
    expect(
      errorMessage({ detail: [{ loc: ["body", "interval_seconds"], msg: "must be >= 5" }] }, "fb"),
    ).toBe("interval_seconds: must be >= 5");
    expect(errorMessage(null, "fallback")).toBe("fallback");
    expect(errorMessage({ detail: [] }, "fallback")).toBe("fallback");
  });
});

describe("sortIncidents", () => {
  const base = { target_id: "t", target_name: "t", failure_reason: "x", resolution_reason: null, resolved_at: null };
  it("puts open incidents first, then newest first", () => {
    const incidents: Incident[] = [
      { ...base, id: "old-resolved", status: "RESOLVED", opened_at: "2026-10-21T01:00:00Z" },
      { ...base, id: "new-resolved", status: "RESOLVED", opened_at: "2026-10-21T03:00:00Z" },
      { ...base, id: "open", status: "OPEN", opened_at: "2026-10-21T00:00:00Z" },
    ];
    expect(sortIncidents(incidents).map((i) => i.id)).toEqual(["open", "new-resolved", "old-resolved"]);
  });
});
