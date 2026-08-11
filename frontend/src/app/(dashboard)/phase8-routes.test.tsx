import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import TrendingPage from "@/app/(dashboard)/trending/page";
import NewLaunchesPage from "@/app/(dashboard)/launches/page";
import WatchlistPage from "@/app/(dashboard)/watchlist/page";
import { api } from "@/lib/api-client";
import { NAV_FOOTER, NAV_GROUPS, activeItem } from "@/lib/design/nav";
import type { FreshDetectedToken } from "@/types/radar";
import type * as ApiClientModule from "@/lib/api-client";

/**
 * The three Phase 8 surfaces, rendered from realistic backend payloads.
 *
 * The through-line in every assertion: these screens may only show what their
 * endpoint actually returned. Trending has no score because scores are not on
 * `/market/trending`; New Launches shows a stage rather than a row of dashes;
 * the watchlist shows a mint because the API sends no name.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof ApiClientModule>("@/lib/api-client");
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), patch: vi.fn() } };
});

vi.mock("@/hooks/use-live-updates", () => ({
  useLiveUpdates: () => ({ status: "offline", subscribe: () => () => {} }),
}));

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const MINT = "So11111111111111111111111111111111111111112";

/* -------------------------------------------------------------------------- */

const trendingPayload = {
  items: [
    {
      token: {
        id: "t1",
        mint_address: MINT,
        name: "Test Token",
        symbol: "TEST",
        decimals: 6,
        metadata_uri: null,
        image_url: null,
        creator_address: null,
        signature: "sig",
        slot: 1,
        block_time: null,
        discovered_at: "2026-08-10T00:00:00Z",
        source_program: "pump",
        metadata_status: "resolved",
      },
      market: {
        id: "m1",
        mint_address: MINT,
        captured_at: new Date().toISOString(),
        price_usd: "0.0021",
        price_native: "0.00001",
        liquidity_usd: "8000",
        fully_diluted_valuation: "25000",
        market_cap: "20400",
        volume_24h: "120000",
        volume_1h: "9000",
        volume_5m: "1200",
        buy_count_24h: 68,
        sell_count_24h: 32,
        dex_name: "Raydium",
        trading_pair: "TEST/SOL",
        pool_address: "pool",
        trading_status: "trading",
        is_verified: false,
        provider: "dexscreener",
        provider_latency_ms: 100,
      },
    },
  ],
  total: 1,
  page: 1,
  page_size: 50,
  pages: 1,
  sort_by: "volume_24h",
};

describe("Trending", () => {
  it("renders rows from the real payload and links the token inward", async () => {
    vi.mocked(api.get).mockResolvedValue(trendingPayload);
    render(<TrendingPage />, { wrapper });

    const link = await screen.findByRole("link", { name: /TEST/ });
    expect(link).toHaveAttribute("href", `/tokens/${MINT}`);
  });

  it("names the ranking rather than asserting a trend", async () => {
    vi.mocked(api.get).mockResolvedValue(trendingPayload);
    render(<TrendingPage />, { wrapper });

    // "Ranked by Volume 24h" is a fact. "Hot" would be a claim the endpoint
    // does not support. The disclaimer legitimately contains the word
    // "momentum" — to say the ranking is *not* one — so this checks the
    // headline, not the whole document.
    expect(await screen.findByText(/Ranked by/)).toBeInTheDocument();
    expect(screen.getByText("Volume 24h")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Where the market is active" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /hot|trending now|surging/i })).toBeNull();
  });

  it("shows transaction counts without calling them wallets", async () => {
    vi.mocked(api.get).mockResolvedValue(trendingPayload);
    render(<TrendingPage />, { wrapper });

    await screen.findByRole("link", { name: /TEST/ });
    expect(screen.getByText("68")).toBeInTheDocument();
    expect(screen.queryByText(/buyers|holders|wallets/i)).not.toBeInTheDocument();
  });

  it("infers no score or risk, which this endpoint does not carry", async () => {
    vi.mocked(api.get).mockResolvedValue(trendingPayload);
    render(<TrendingPage />, { wrapper });

    await screen.findByRole("link", { name: /TEST/ });
    expect(screen.queryByRole("columnheader", { name: /score/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /risk/i })).not.toBeInTheDocument();
  });

  it("issues exactly one request for the whole table", async () => {
    vi.mocked(api.get).mockResolvedValue(trendingPayload);
    render(<TrendingPage />, { wrapper });

    await screen.findByRole("link", { name: /TEST/ });
    // No N+1: one list call, not one per token.
    expect(vi.mocked(api.get)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.get).mock.calls[0]?.[0]).toContain("/market/trending");
  });
});

/* -------------------------------------------------------------------------- */

function fresh(overrides: Partial<FreshDetectedToken> = {}): FreshDetectedToken {
  return {
    mint_address: MINT,
    name: "Brand New",
    symbol: "NEW",
    image_url: null,
    discovered_at: new Date().toISOString(),
    block_time: null,
    metadata_status: "resolved",
    current_market_cap: null,
    current_liquidity: null,
    current_price: null,
    market_observed_at: null,
    radar_score: null,
    radar_category: null,
    radar_status: null,
    ...overrides,
  };
}

describe("New launches", () => {
  it("shows a just-detected token as Detected rather than as broken data", async () => {
    vi.mocked(api.get).mockResolvedValue([fresh()]);
    render(<NewLaunchesPage />, { wrapper });

    // "Detected" is also a filter option, so scope this to the row itself.
    const link = await screen.findByRole("link", { name: /NEW/ });
    const row = link.closest("tr")!;
    expect(within(row).getByText("Detected")).toBeInTheDocument();
  });

  it("leaves unpriced figures as dashes, never zero", async () => {
    vi.mocked(api.get).mockResolvedValue([fresh()]);
    render(<NewLaunchesPage />, { wrapper });

    // Wait for the data row, not the skeleton: `findAllByRole("row")` resolves
    // on the 12 pending rows, which carry no figures at all.
    const link = await screen.findByRole("link", { name: /NEW/ });
    const row = link.closest("tr")!;
    expect(within(row).queryByText("$0")).not.toBeInTheDocument();
    expect(within(row).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("distinguishes never-observed from stale", async () => {
    vi.mocked(api.get).mockResolvedValue([fresh()]);
    render(<NewLaunchesPage />, { wrapper });

    await screen.findByRole("link", { name: /NEW/ });
    expect(screen.getByText("Waiting for liquidity")).toBeInTheDocument();
  });

  it("promotes a token that reached the radar", async () => {
    vi.mocked(api.get).mockResolvedValue([
      fresh({
        current_price: "0.002",
        market_observed_at: new Date().toISOString(),
        radar_score: "71",
        radar_category: "early_momentum",
        radar_status: "radar",
      }),
    ]);
    render(<NewLaunchesPage />, { wrapper });

    expect(await screen.findByText("On radar")).toBeInTheDocument();
  });

  it("links the token to its dossier", async () => {
    vi.mocked(api.get).mockResolvedValue([fresh()]);
    render(<NewLaunchesPage />, { wrapper });

    expect(await screen.findByRole("link", { name: /NEW/ })).toHaveAttribute(
      "href",
      `/tokens/${MINT}`,
    );
  });
});

/* -------------------------------------------------------------------------- */

describe("Watchlist", () => {
  it("offers to create a list when the user has none", async () => {
    vi.mocked(api.get).mockResolvedValue([]);
    render(<WatchlistPage />, { wrapper });

    expect(await screen.findByText("No watchlists yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create watchlist/i })).toBeInTheDocument();
  });

  it("shows the score when added beside the score now", async () => {
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === "/watchlists") {
        return Promise.resolve([
          {
            id: "list-1",
            name: "Watching closely",
            description: null,
            alert_on: [],
            item_count: 1,
            created_at: "2026-08-01T00:00:00Z",
            updated_at: "2026-08-01T00:00:00Z",
          },
        ]);
      }
      return Promise.resolve([
        {
          mint_address: MINT,
          note: null,
          added_mission_state: null,
          added_priority: null,
          added_score: "58",
          created_at: "2026-08-01T00:00:00Z",
          current_mission_state: null,
          current_priority: "high",
          current_score: "71",
          last_change: "Score rose after a liquidity increase.",
          last_change_at: "2026-08-09T00:00:00Z",
        },
      ]);
    });

    render(<WatchlistPage />, { wrapper });

    // The pairing is the whole point of the screen.
    expect(await screen.findByText("58")).toBeInTheDocument();
    expect(screen.getByText("71")).toBeInTheDocument();
    expect(screen.getByText("+13")).toBeInTheDocument();
    // Backend prose, verbatim.
    expect(
      screen.getByText("Score rose after a liquidity increase."),
    ).toBeInTheDocument();
  });

  it("explains the auth-bypass conflict instead of showing a generic failure", async () => {
    const { ApiError } = await vi.importActual<typeof ApiClientModule>(
      "@/lib/api-client",
    );
    vi.mocked(api.get).mockResolvedValue([]);
    vi.mocked(api.post).mockRejectedValue(
      new ApiError(
        409,
        "conflict",
        "Watchlists belong to a real account, and this request is authenticated by the development auth bypass, whose principal is never persisted.",
      ),
    );

    render(<WatchlistPage />, { wrapper });

    await screen.findByText("No watchlists yet");
    // `fireEvent` rather than user-event: the suite already depends on the
    // former, and a test is not a reason to add a package.
    fireEvent.change(screen.getByLabelText("Watchlist name"), {
      target: { value: "Mine" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create watchlist/i }));

    await waitFor(() =>
      expect(screen.getByText("Watchlists need a real account")).toBeInTheDocument(),
    );
  });
});

/* -------------------------------------------------------------------------- */

describe("Navigation activation", () => {
  it("no destination is marked planned any more", () => {
    const planned = [...NAV_GROUPS.flatMap((g) => g.items), ...NAV_FOOTER].filter(
      (item) => item.status === "planned",
    );
    expect(planned).toEqual([]);
  });

  it("routes the three new destinations to real paths", () => {
    const items = NAV_GROUPS.flatMap((g) => g.items);
    const byLabel = (label: string) => items.find((i) => i.label === label);

    expect(byLabel("Trending")?.href).toBe("/trending");
    expect(byLabel("New launches")?.href).toBe("/launches");
    expect(byLabel("Watchlist")?.href).toBe("/watchlist");
  });

  it("marks each new route active when it is the current page", () => {
    expect(activeItem("/trending")?.label).toBe("Trending");
    expect(activeItem("/launches")?.label).toBe("New launches");
    expect(activeItem("/watchlist")?.label).toBe("Watchlist");
  });
});
