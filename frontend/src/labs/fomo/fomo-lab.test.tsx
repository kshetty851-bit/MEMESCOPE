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

  it("shows the multiple-traders book beside the main one", async () => {
    show({
      ...base, running: true, max_open_trades: 20, open_trades: 3, equity_usd: "520", pnl_usd: "20",
      cash_usd: "445", leaders: [], positions: [],
      signals: [{ signature: "Sig3333333333333333333333333333", wallet: "Wal11111111111111111111",
                  mint: "Min3333333333333333333", side: "buy", traded_at: "2026-10-19T11:57:00Z", outcome: "already_held" }],
      consensus: { started_at: "2026-10-19T10:00:00Z", cash_usd: "475", open_value_usd: "26", equity_usd: "501",
                   pnl_usd: "1", open_trades: 1, positions: [], decisions: { opened: 1, no_consensus: 12 } },
    });
    expect(await screen.findByText("Multiple-traders book")).toBeInTheDocument();
    expect(screen.getByText(/1 copied · 12 no 2nd trader/)).toBeInTheDocument();
    expect(screen.getByText("already held")).toBeInTheDocument();
    expect(screen.getByText("3 / 20")).toBeInTheDocument();
  });

  it("shows the crowd book on fresh graduations", async () => {
    show({
      ...base, running: true, max_open_trades: 20, open_trades: 0, equity_usd: "500", pnl_usd: "0",
      cash_usd: "500", leaders: [], positions: [], signals: [],
      crowd: { started_at: "2026-10-20T18:00:00Z", feed_at: "2026-10-20T18:10:00Z", feed_error: null, coins_seen: 4,
               cash_usd: "475", open_value_usd: "26", equity_usd: "501", pnl_usd: "1", open_trades: 1,
               positions: [], decisions: { opened: 1, first_buyer: 3 } },
    });
    expect(await screen.findByText("Crowd book · fresh graduations")).toBeInTheDocument();
    expect(screen.getByText(/1 bought · 3 first fomo buyer/)).toBeInTheDocument();
  });
});
