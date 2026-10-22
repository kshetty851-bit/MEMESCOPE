import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api-client", () => ({ api: { get: (...a: unknown[]) => get(...a) } }));

import { TrackRecordPage } from "./page";

const mover = { mint: "Kim1111111111111111111111111111111111111pump", symbol: "Kimchi", name: null,
  graduated_at: "2026-10-20T23:00:00Z", pool_usd: 17250, peak_x: 922.37, peak_after_min: 1076.9, end_x: 850 };

describe("Track record", () => {
  it("shows the funnel, the multiples and which coin did how many x", async () => {
    get.mockResolvedValue({
      totals: { coins_seen: 2982061, seen_since: "2026-07-27T06:44:46Z", curve_tracked: 1281827, graduated: 45985,
        graduated_since: "2026-09-11T12:43:42Z", paper_coins: 9772, paper_trades: 44237, strategies: 185,
        real_trades: 2182, real_coins: 1426, real_wins: 1926, real_pnl_usd: -139.51, real_since: "2026-09-17T08:18:30Z",
        safety_checks: 2452, at: "2026-10-22T15:34:54Z" },
      best: { paper: [{ mint: "Wose", symbol: "WOSE", book: "KARTHIK_QUIET_5M", opened_at: "2026-10-10T10:00:00Z", x: 2.5, pool_usd: 60000 }], real: [] },
      reached: { "1.1": 20532, "1.5": 12095, "2": 7605, "5": 1501, "10": 391, "50": 9, "100": 2 },
      measured: 30181, ended_down_80: 20305, hall_of_fame: [mover], this_week: [mover],
      days: [{ date: "2026-10-21", graduated: 1050, measured: 990, x2: 260, x10: 20, best_x: 922.37, best_symbol: "Kimchi" }],
    });
    render(<QueryClientProvider client={new QueryClient()}><TrackRecordPage /></QueryClientProvider>);
    expect(await screen.findByRole("heading", { name: "Track record" })).toBeInTheDocument();
    expect(screen.getAllByText("922x").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Kimchi").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /Kimchi reached 922x/ })).toHaveAttribute("href", `https://dexscreener.com/solana/${mover.mint}`);
    expect(screen.getByText(/20,305 of the same 30,181 coins/)).toBeInTheDocument();
  });
});
