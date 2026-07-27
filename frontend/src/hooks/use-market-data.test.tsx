import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useMarketByMint } from "@/hooks/use-market-data";
import type { MarketSnapshot, TrendingPage } from "@/types/api";

function snapshot(mint: string, overrides: Partial<MarketSnapshot> = {}): MarketSnapshot {
  return {
    id: `snap-${mint}`,
    mint_address: mint,
    captured_at: "2026-07-27T12:00:00Z",
    price_usd: "0.0000042",
    price_native: "0.00000002",
    liquidity_usd: "12345.67",
    fully_diluted_valuation: "99000",
    market_cap: "88000",
    volume_24h: "5000",
    volume_1h: "400",
    volume_5m: "30",
    buy_count_24h: 120,
    sell_count_24h: 80,
    dex_name: "pumpfun",
    trading_pair: "TKN/SOL",
    pool_address: "pool123",
    trading_status: "trading",
    is_verified: false,
    provider: "dexscreener",
    provider_latency_ms: 42,
    ...overrides,
  };
}

function page(mints: string[]): TrendingPage {
  return {
    items: mints.map((mint) => ({
      token: {
        id: `id-${mint}`,
        mint_address: mint,
        name: `Token ${mint}`,
        symbol: "TKN",
        decimals: 6,
        metadata_uri: null,
        creator_address: "Wallet1",
        signature: "sig",
        slot: 1,
        block_time: null,
        discovered_at: "2026-07-27T11:59:00Z",
        source_program: "pump",
        metadata_status: "resolved",
      },
      market: snapshot(mint),
    })),
    total: mints.length,
    page: 1,
    page_size: 100,
    pages: 1,
    sort_by: "captured_at",
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useMarketByMint", () => {
  it("indexes trending entries by mint", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(page(["MintA", "MintB"])), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const { result } = renderHook(() => useMarketByMint(), { wrapper });

    await waitFor(() => expect(result.current.byMint.size).toBe(2));
    expect(result.current.byMint.get("MintA")?.dex_name).toBe("pumpfun");
    expect(result.current.byMint.get("MintB")?.market_cap).toBe("88000");
  });

  it("requests the recency-sorted ranking, not the volume one", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(page([])), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useMarketByMint(), { wrapper });

    // Ranking by volume would bury brand-new low-volume launches, which are
    // exactly the rows the live feed shows.
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(String(fetchMock.mock.calls[0]![0])).toContain("sort_by=captured_at");
  });

  it("yields an empty map when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 500 })));

    const { result } = renderHook(() => useMarketByMint(), { wrapper });

    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.byMint.size).toBe(0);
  });

  it("keeps money as strings so precision is not lost", async () => {
    const tiny = "0.000000000123456789";
    const payload = page(["MintTiny"]);
    payload.items[0]!.market.price_usd = tiny;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const { result } = renderHook(() => useMarketByMint(), { wrapper });

    await waitFor(() => expect(result.current.byMint.size).toBe(1));
    expect(result.current.byMint.get("MintTiny")?.price_usd).toBe(tiny);
  });
});
