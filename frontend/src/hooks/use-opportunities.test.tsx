import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BOARD_POLL_MS, useOpportunities } from "@/hooks/use-opportunities";
import type { OpportunityBoard } from "@/types/opportunity";

function board(overrides: Partial<OpportunityBoard> = {}): OpportunityBoard {
  return {
    items: [],
    page: 1,
    page_size: 100,
    has_more: false,
    applied_filters: { signal_type: null, stage: null, engine_enabled: true },
    observed_at: "2026-08-02T12:00:00Z",
    ...overrides,
  };
}

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "QueryWrapper";
  return Wrapper;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("useOpportunities", () => {
  it("polls once a minute", () => {
    // Detection rides enrichment writes, so a fresh-tier token can produce a
    // signal within thirty seconds. A minute sits close enough to feel live
    // without issuing sixty requests to observe one change.
    expect(BOARD_POLL_MS).toBe(60_000);
  });

  it("fetches the board", async () => {
    const fetchSpy = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify(board()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchSpy);

    const { result } = renderHook(() => useOpportunities(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.applied_filters.engine_enabled).toBe(true);

    const url = String(fetchSpy.mock.calls[0]?.[0]);
    expect(url).toContain("/opportunities");
    // The endpoint's maximum. Search, confidence, priority and sorting are all
    // applied client-side over this page, so fetching a partial page would make
    // a filter silently narrow something the user never saw.
    expect(url).toContain("page_size=100");
  });

  it("sends only the filters the endpoint supports", async () => {
    const fetchSpy = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify(board()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchSpy);

    const { result } = renderHook(
      () => useOpportunities({ stage: "fresh_graduation", signalType: "breakout" }),
      { wrapper: wrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = String(fetchSpy.mock.calls[0]?.[0]);
    expect(url).toContain("stage=fresh_graduation");
    expect(url).toContain("signal_type=breakout");
  });

  it("surfaces a failure rather than rendering an empty board", async () => {
    // An empty board means "nothing changed", which is information. A failed
    // request must never be presented as that.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ error: { code: "internal_error", message: "boom" } }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const { result } = renderHook(() => useOpportunities(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });

  it("reports the engine being switched off as a state, not an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify(
            board({
              applied_filters: { signal_type: null, stage: null, engine_enabled: false },
            }),
          ),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const { result } = renderHook(() => useOpportunities(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.applied_filters.engine_enabled).toBe(false);
  });
});
