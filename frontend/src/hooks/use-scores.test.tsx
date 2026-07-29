import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useScoresByMint } from "@/hooks/use-scores";
import type { TokenScore, TopScorePage } from "@/types/score";

function score(mint: string, overrides: Partial<TokenScore> = {}): TokenScore {
  return {
    mint_address: mint,
    score: "71.40",
    opportunity_raw: "71.40",
    grade: "strong",
    is_elite: false,
    evidence: {
      evidence: "65.00",
      coverage: "65.00",
      observations: 9,
      freshness: "0.7824",
      confidence: "57.49",
    },
    risk: { market_risk: "0.00", has_veto: false, deduction: "0.00" },
    model_version: "v1",
    evaluated_at: "2026-07-28T09:00:00Z",
    latest_snapshot_at: "2026-07-28T08:59:00Z",
    previous_score: null,
    last_trigger: "first",
    components: [],
    reasons: [],
    ...overrides,
  };
}

function page(mints: string[]): TopScorePage {
  return {
    items: mints.map((mint) => ({
      token: { mint_address: mint, name: `Token ${mint}`, symbol: "TKN" },
      score: score(mint),
    })),
    total: mints.length,
    candidate_total: mints.length,
    page: 1,
    page_size: 100,
    pages: 1,
    applied_filters: {},
  };
}

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function respondWith(payload: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useScoresByMint", () => {
  it("indexes scores by mint", async () => {
    respondWith(page(["MintA", "MintB"]));

    const { result } = renderHook(() => useScoresByMint(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.byMint.size).toBe(2));
    expect(result.current.byMint.get("MintA")?.grade).toBe("strong");
  });

  it("shares one request across every consumer on a page", async () => {
    // The dedup guarantee: the Core, the cards, the log and the rail all call
    // this hook, and a page with a dozen scored cards must still issue exactly
    // one request rather than one per card.
    const fetchMock = respondWith(page(["MintA"]));
    const wrapper = makeWrapper();

    const { result } = renderHook(
      () => {
        useScoresByMint();
        useScoresByMint();
        return useScoresByMint();
      },
      { wrapper },
    );

    await waitFor(() => expect(result.current.byMint.size).toBe(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("includes vetoed tokens, which the ranking hides by default", async () => {
    // The feed has to be able to show a token the risk gate just condemned —
    // among the most important things it can tell a user.
    const fetchMock = respondWith(page([]));

    renderHook(() => useScoresByMint(), { wrapper: makeWrapper() });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(String(fetchMock.mock.calls[0]![0])).toContain("include_vetoed=true");
  });

  it("yields an empty map when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 500 })));

    const { result } = renderHook(() => useScoresByMint(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.byMint.size).toBe(0);
  });

  it("keeps score figures as strings so precision survives", async () => {
    const payload = page(["MintPrecise"]);
    payload.items[0]!.score.score = "71.40";
    respondWith(payload);

    const { result } = renderHook(() => useScoresByMint(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.byMint.size).toBe(1));
    // Not 71.4: the trailing zero is what makes a displayed contribution and a
    // displayed total reconcile.
    expect(result.current.byMint.get("MintPrecise")?.score).toBe("71.40");
  });
});
