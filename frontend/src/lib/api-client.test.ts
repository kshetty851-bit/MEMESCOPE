import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, getAccessToken, setAccessToken } from "@/lib/api-client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  setAccessToken(null);
  vi.restoreAllMocks();
});

describe("apiFetch", () => {
  it("attaches the bearer token when one is set", async () => {
    setAccessToken("token-abc");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await api.get("/users/me");

    const headers = fetchMock.mock.calls[0]![1].headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer token-abc");
  });

  it("throws a typed ApiError carrying the server error code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            error: { code: "conflict", message: "Already exists", details: {} },
            request_id: "req-1",
          },
          409,
        ),
      ),
    );

    await expect(api.post("/auth/register", {})).rejects.toMatchObject({
      status: 409,
      code: "conflict",
      requestId: "req-1",
    });
  });

  it("refreshes once on 401 and replays the original request", async () => {
    setAccessToken("stale-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ error: { code: "x", message: "" } }, 401))
      .mockResolvedValueOnce(jsonResponse({ access_token: "fresh-token" }))
      .mockResolvedValueOnce(jsonResponse({ email: "a@b.test" }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.get<{ email: string }>("/users/me");

    expect(result.email).toBe("a@b.test");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(getAccessToken()).toBe("fresh-token");
  });

  it("clears the token when the refresh itself fails", async () => {
    setAccessToken("stale-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ error: { code: "x", message: "" } }, 401)),
    );

    await expect(api.get("/users/me")).rejects.toBeInstanceOf(ApiError);
    expect(getAccessToken()).toBeNull();
  });

  it("shares a single refresh across concurrent 401s", async () => {
    setAccessToken("stale-token");
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(jsonResponse({ access_token: "fresh-token" }));
      }
      return Promise.resolve(
        getAccessToken() === "fresh-token"
          ? jsonResponse({ ok: true })
          : jsonResponse({ error: { code: "x", message: "" } }, 401),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    await Promise.all([api.get("/a"), api.get("/b"), api.get("/c")]);

    const refreshCalls = fetchMock.mock.calls.filter((call) =>
      String(call[0]).endsWith("/auth/refresh"),
    );
    expect(refreshCalls).toHaveLength(1);
  });
});
