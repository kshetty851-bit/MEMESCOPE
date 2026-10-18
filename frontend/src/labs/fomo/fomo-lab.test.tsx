import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api-client", () => ({ api: { get: (...a: unknown[]) => get(...a) } }));

import { FomoLabPage } from "./page";

const base = { enabled: true, configured: true, note: "Forward paper simulation. No real orders.",
               starting_usd: "500", trade_usd: "50" };

function show(board: object) {
  get.mockResolvedValue(board);
  render(<QueryClientProvider client={new QueryClient()}><FomoLabPage /></QueryClientProvider>);
}

afterEach(() => get.mockReset());

describe("FOMO Lab", () => {
  it("says plainly when a feed key is missing", async () => {
    show({ ...base, configured: false, running: false, reason: "feed_key_missing" });
    expect(await screen.findByText("Lab is not running")).toBeInTheDocument();
    expect(screen.getByText("The FOMO API key is required.")).toBeInTheDocument();
  });

  it("shows the feed times and every decision, copied or not", async () => {
    show({
      ...base, running: true, started_at: "2026-10-18T10:00:00Z", roster_at: "2026-10-18T11:30:00Z",
      source_captured_at: "2026-10-18T11:29:00Z", feed_at: "2026-10-18T11:58:00Z", feed_error: null,
      cash_usd: "450", open_value_usd: "52", equity_usd: "502", pnl_usd: "2", open_trades: 1, stale_marks: 0,
      leaders: [], positions: [],
      signals: [
        { signature: "Sig1111111111111111111111111111", wallet: "Wal11111111111111111111", mint: "Min1111111111111111111",
          side: "buy", traded_at: "2026-10-18T11:57:00Z", outcome: "opened" },
        { signature: "Sig2222222222222222222222222222", wallet: "Wal11111111111111111111", mint: "Min2222222222222222222",
          side: "buy", traded_at: "2026-10-18T11:50:00Z", outcome: "stale_signal" },
      ],
    });
    expect(await screen.findByText(/Roster fetched/)).toBeInTheDocument();
    expect(screen.getByText(/Source snapshot/)).toBeInTheDocument();
    expect(screen.getByText(/Last complete swap poll/)).toBeInTheDocument();
    expect(screen.getByText("opened")).toBeInTheDocument();
    expect(screen.getByText("stale signal")).toBeInTheDocument();
    // Every coin links to its chart, pump.fun page and explorer.
    const mint = "Min1111111111111111111";
    expect(screen.getByRole("link", { name: `Chart for ${mint}` })).toHaveAttribute(
      "href", `https://dexscreener.com/solana/${mint}`);
    expect(screen.getByRole("link", { name: `pump for ${mint}` })).toHaveAttribute(
      "href", `https://pump.fun/coin/${mint}`);
    expect(screen.getByRole("link", { name: `scan for ${mint}` })).toHaveAttribute(
      "href", `https://solscan.io/token/${mint}`);
  });
});
