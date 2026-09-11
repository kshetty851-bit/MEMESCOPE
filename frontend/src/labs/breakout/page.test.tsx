import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./api";
import { BreakoutChart } from "./chart";
import * as mock from "./mock";
import { BreakoutLabPage } from "./page";
import type { Account, BreakoutHealth, Setup } from "./types";

/**
 * The page against its own fixtures.
 *
 * Every fetcher is stubbed at the client boundary rather than at `fetch`, so
 * these tests assert what the PAGE does with a response shape — which is the
 * thing that breaks when the backend renames a field. The fixtures are the
 * same ones mock mode serves, and they are typed against `types.ts`, so a
 * rename fails the build before it reaches a test.
 */

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function stub(overrides: {
  health?: BreakoutHealth;
  setups?: Setup[];
  account?: Account;
  positions?: typeof mock.MOCK_POSITIONS;
  trades?: typeof mock.MOCK_TRADES;
  episodes?: typeof mock.MOCK_EPISODES;
  stats?: typeof mock.MOCK_STATS;
} = {}) {
  vi.spyOn(api, "fetchHealth").mockResolvedValue(overrides.health ?? mock.MOCK_HEALTH);
  vi.spyOn(api, "fetchSetups").mockResolvedValue(overrides.setups ?? mock.MOCK_SETUPS);
  vi.spyOn(api, "fetchAccount").mockResolvedValue(overrides.account ?? mock.MOCK_ACCOUNT);
  vi.spyOn(api, "fetchPositions").mockResolvedValue(
    overrides.positions ?? mock.MOCK_POSITIONS);
  vi.spyOn(api, "fetchTrades").mockResolvedValue(overrides.trades ?? mock.MOCK_TRADES);
  vi.spyOn(api, "fetchEpisodes").mockResolvedValue(
    overrides.episodes ?? mock.MOCK_EPISODES);
  vi.spyOn(api, "fetchStats").mockResolvedValue(overrides.stats ?? mock.MOCK_STATS);
  vi.spyOn(api, "fetchEquity").mockResolvedValue(mock.MOCK_EQUITY);
  vi.spyOn(api, "fetchTradeStats").mockResolvedValue(mock.MOCK_TRADE_STATS);
  vi.spyOn(api, "fetchSetupDetail").mockResolvedValue(mock.MOCK_DETAIL);
}

beforeEach(() => stub());
afterEach(() => vi.restoreAllMocks());

describe("the disabled panel", () => {
  it("says the lab is not running rather than showing an empty book", async () => {
    // "Not running" and "ran and found nothing" are different facts. A zeroed
    // header would render them identically.
    vi.spyOn(api, "fetchHealth").mockResolvedValue({ running: false });
    render(<BreakoutLabPage />, { wrapper });
    expect(await screen.findByText(/the lab is not running/i)).toBeInTheDocument();
    expect(screen.queryByText(/^Equity$/)).not.toBeInTheDocument();
  });

  it("does not fetch anything else while it is off", async () => {
    vi.spyOn(api, "fetchHealth").mockResolvedValue({ running: false });
    render(<BreakoutLabPage />, { wrapper });
    await screen.findByText(/the lab is not running/i);
    expect(api.fetchSetups).not.toHaveBeenCalled();
    expect(api.fetchAccount).not.toHaveBeenCalled();
  });
});

describe("the header strip", () => {
  it("always shows the paper tag, because this is not real money", async () => {
    render(<BreakoutLabPage />, { wrapper });
    expect(await screen.findByText("paper")).toBeInTheDocument();
  });

  it("shows the equity, slots and slot size", async () => {
    render(<BreakoutLabPage />, { wrapper });
    expect(await screen.findByText("$963.41")).toBeInTheDocument();
    expect(screen.getByText("2/10")).toBeInTheDocument();
    expect(screen.getByText("$96.34")).toBeInTheDocument();
  });

  it("raises a halted banner in an alert role", async () => {
    stub({ account: mock.MOCK_ACCOUNT_HALTED });
    render(<BreakoutLabPage />, { wrapper });
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/HALTED/);
    expect(banner).toHaveTextContent(/42.4%/);
    expect(banner).toHaveTextContent(/reset-halt/);
  });

  it("says so when trading is off but the lab is running", async () => {
    stub({ account: mock.MOCK_ACCOUNT_EMPTY });
    render(<BreakoutLabPage />, { wrapper });
    expect(await screen.findByText("trading off")).toBeInTheDocument();
  });
});

describe("the setups watchlist", () => {
  it("puts PRE_BREAKOUT first and then orders by score", async () => {
    // The fixture is deliberately out of order on score: a WATCHING at 68
    // outranks the PRE_BREAKOUT at 74 on score alone, and must still sort
    // below it.
    render(<BreakoutLabPage />, { wrapper });
    const rows = await screen.findAllByTestId("setup-row");
    expect(within(rows[0]!).getByText("SOLCEX")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("PRE-BREAKOUT")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("GORK")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("MOODENG")).toBeInTheDocument();
  });

  it("badges every state", async () => {
    render(<BreakoutLabPage />, { wrapper });
    await screen.findAllByTestId("setup-row");
    expect(screen.getByText("PRE-BREAKOUT")).toBeInTheDocument();
    expect(screen.getAllByText("WATCHING")).toHaveLength(2);
  });

  it("renders an empty state instead of a bare table", async () => {
    stub({ setups: [] });
    render(<BreakoutLabPage />, { wrapper });
    expect(await screen.findByText(/nothing is set up/i)).toBeInTheDocument();
  });

  it("opens the token panel when a row is clicked", async () => {
    render(<BreakoutLabPage />, { wrapper });
    const rows = await screen.findAllByTestId("setup-row");
    fireEvent.click(rows[0]!);
    expect(await screen.findByTestId("breakout-chart")).toBeInTheDocument();
    expect(api.fetchSetupDetail).toHaveBeenCalledWith(mock.MOCK_SETUPS[0]!.mint);
  });
});

describe("the token panel", () => {
  it("lists every score component with its value", async () => {
    render(<BreakoutLabPage />, { wrapper });
    fireEvent.click((await screen.findAllByTestId("setup-row"))[0]!);
    await screen.findByTestId("breakout-chart");
    for (const label of ["Volume", "Rising lows", "Range position",
      "Compression", "Hourly confirm"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("offers a daily/hourly toggle and starts on daily", async () => {
    render(<BreakoutLabPage />, { wrapper });
    fireEvent.click((await screen.findAllByTestId("setup-row"))[0]!);
    await screen.findByTestId("breakout-chart");
    expect(screen.getByRole("button", { name: "1D" })).toHaveAttribute(
      "aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "1H" }));
    expect(screen.getByRole("button", { name: "1H" })).toHaveAttribute(
      "aria-pressed", "true");
  });
});

describe("positions and trades", () => {
  it("shows the trailing stop value on every open position", async () => {
    render(<BreakoutLabPage />, { wrapper });
    expect(await screen.findByText("$84.32")).toBeInTheDocument();
    expect(screen.getByText("$77.26")).toBeInTheDocument();
  });

  it("renders an empty state with no positions", async () => {
    stub({ positions: [] });
    render(<BreakoutLabPage />, { wrapper });
    expect(await screen.findByText(/no open positions/i)).toBeInTheDocument();
  });

  it("labels the exit reason with words, not server codes", async () => {
    render(<BreakoutLabPage />, { wrapper });
    expect(await screen.findAllByText("Trailing stop")).toHaveLength(2);
    expect(screen.getByText("Setup failed")).toBeInTheDocument();
  });

  it("renders an empty state with no trades", async () => {
    stub({ trades: { total: 0, items: [] } });
    render(<BreakoutLabPage />, { wrapper });
    expect(await screen.findByText(/no closed trades/i)).toBeInTheDocument();
  });

  it("pages the trade list only when there is more than one page", async () => {
    render(<BreakoutLabPage />, { wrapper });
    await screen.findByText("Closed trades");
    // Three trades against a page size of 25 — one page, so no pager.
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();

    stub({ trades: { ...mock.MOCK_TRADES, total: 60 } });
    render(<BreakoutLabPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Next" }).length)
        .toBeGreaterThan(0));
  });

  it("fetches the next page when the pager advances", async () => {
    stub({ trades: { ...mock.MOCK_TRADES, total: 60 } });
    render(<BreakoutLabPage />, { wrapper });
    const next = (await screen.findAllByRole("button", { name: "Next" }))[0]!;
    fireEvent.click(next);
    await waitFor(() => expect(api.fetchTrades).toHaveBeenCalledWith(25, 25));
  });
});

describe("the verdict cards", () => {
  it("shows outcomes by score decile", async () => {
    render(<BreakoutLabPage />, { wrapper });
    const rows = await screen.findAllByTestId("decile-row");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText("50–59")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("70–79")).toBeInTheDocument();
  });

  it("says nothing has completed rather than drawing an empty table", async () => {
    stub({
      stats: {
        ...mock.MOCK_STATS,
        outcomes: { n: 0, mean_trail25_pct: null, median_trail25_pct: null,
          win_rate: null, by_score_decile: [] },
      },
    });
    render(<BreakoutLabPage />, { wrapper });
    expect(
      await screen.findByText(/no episode has completed its 72-hour window/i),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("decile-row")).not.toBeInTheDocument();
  });

  it("draws an em dash for a profit factor with no losses to divide by", async () => {
    vi.spyOn(api, "fetchTradeStats").mockResolvedValue({
      ...mock.MOCK_TRADE_STATS, profit_factor: null, avg_loss_pct: null });
    render(<BreakoutLabPage />, { wrapper });
    await screen.findByText("Profit factor");
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});

describe("the chart", () => {
  const bars = [
    { t: "2026-09-01T00:00:00Z", o: 1, h: 1.2, l: 0.9, c: 1.1, v: 10 },
    { t: "2026-09-02T00:00:00Z", o: 1.1, h: 1.4, l: 1.05, c: 1.3, v: 12 },
    { t: "2026-09-03T00:00:00Z", o: 1.3, h: 1.35, l: 1.2, c: 1.25, v: 9 },
  ];
  const clusters = [
    { level: 1.5, touches: 3, first: "x", last: "y", broken: false },
    { level: 0.8, touches: 2, first: "x", last: "y", broken: true },
  ];

  it("draws unbroken levels solid and broken ones dashed", () => {
    render(
      <BreakoutChart bars={bars} clusters={clusters} nearestResistance={1.5}
        preZonePct={6} timeframe="day" />,
    );
    expect(screen.getAllByTestId("level-unbroken")).toHaveLength(1);
    expect(screen.getAllByTestId("level-broken")).toHaveLength(1);
    expect(screen.getByTestId("level-broken")).toHaveAttribute("stroke-dasharray");
  });

  it("shades the pre-breakout zone under the nearest resistance", () => {
    render(
      <BreakoutChart bars={bars} clusters={clusters} nearestResistance={1.5}
        preZonePct={6} timeframe="day" />,
    );
    const zone = screen.getByTestId("pre-zone");
    expect(Number(zone.getAttribute("height"))).toBeGreaterThan(0);
  });

  it("draws no zone when there is no resistance above", () => {
    render(
      <BreakoutChart bars={bars} clusters={[]} nearestResistance={null}
        preZonePct={6} timeframe="day" />,
    );
    expect(screen.queryByTestId("pre-zone")).not.toBeInTheDocument();
  });

  it("marks the entry and the live trailing stop when a position is open", () => {
    render(
      <BreakoutChart bars={bars} clusters={clusters} nearestResistance={1.5}
        preZonePct={6} timeframe="day"
        position={mock.MOCK_POSITIONS[0]!} trades={[mock.MOCK_TRADES.items[0]!]} />,
    );
    expect(screen.getByTestId("entry-marker")).toBeInTheDocument();
    expect(screen.getByTestId("trail-marker")).toBeInTheDocument();
    expect(screen.getByTestId("exit-marker")).toBeInTheDocument();
  });

  it("says so rather than drawing an empty box with no candles", () => {
    render(
      <BreakoutChart bars={[]} clusters={[]} nearestResistance={null}
        preZonePct={6} timeframe="day" />,
    );
    expect(screen.getByText(/no candles yet/i)).toBeInTheDocument();
  });
});

describe("the mock fixtures", () => {
  it("carry every field the page reads, so mock mode is not a partial render", () => {
    // The types already enforce this at build time; this asserts the two
    // account fixtures the tests above depend on stay distinguishable.
    expect(mock.MOCK_ACCOUNT_HALTED.halted).toBe(true);
    expect(mock.MOCK_ACCOUNT_EMPTY.trading_enabled).toBe(false);
    expect(mock.MOCK_ACCOUNT_EMPTY.equity).toBe(1_000);
    expect(mock.MOCK_SETUPS.some((s) => s.state === "PRE_BREAKOUT")).toBe(true);
    expect(mock.MOCK_SETUPS.some((s) => s.components.hourly === null)).toBe(true);
  });
});
