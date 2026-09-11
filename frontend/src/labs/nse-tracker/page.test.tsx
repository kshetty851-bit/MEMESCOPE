import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./api";
import { TrackerChart } from "./chart";
import * as mock from "./mock";
import { NseTrackerPage } from "./page";
import type { BreakoutRow, Health, NearRow, Stats, StockView } from "./types";

/**
 * The page against its own fixtures.
 *
 * Every fetcher is stubbed at the CLIENT boundary rather than at `fetch`, so
 * these tests assert what the page does with a response SHAPE — which is the
 * thing that breaks when the backend renames a field. The fixtures are the
 * same ones mock mode serves and they are typed against `types.ts`, so a
 * rename fails the build before it reaches a test.
 *
 * `fireEvent`, not `@testing-library/user-event`: that package is not a
 * dependency of this repo and a lab may not add one.
 */

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function stub(overrides: {
  health?: Health;
  near?: NearRow[];
  breakouts?: BreakoutRow[];
  stock?: StockView;
  replay?: Stats;
  live?: Stats;
} = {}) {
  vi.spyOn(api, "fetchHealth").mockResolvedValue(overrides.health ?? mock.MOCK_HEALTH);
  vi.spyOn(api, "fetchNear").mockResolvedValue(overrides.near ?? mock.MOCK_NEAR);
  vi.spyOn(api, "fetchBreakouts").mockResolvedValue(
    overrides.breakouts ?? mock.MOCK_BREAKOUTS);
  vi.spyOn(api, "fetchStock").mockResolvedValue(overrides.stock ?? mock.MOCK_STOCK);
  vi.spyOn(api, "fetchStats").mockImplementation((source = "replay") =>
    Promise.resolve(
      source === "live"
        ? (overrides.live ?? mock.MOCK_STATS_LIVE)
        : (overrides.replay ?? mock.MOCK_STATS)));
}

beforeEach(() => {
  // jsdom implements no layout, so it has no `scrollIntoView`. Stubbed HERE
  // rather than in the shared `vitest.setup.ts`, which belongs to the whole
  // repo — this lab edits nothing outside its own folder.
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

afterEach(() => vi.restoreAllMocks());

describe("the board", () => {
  it("puts NEAR before WATCH and orders by score inside each", async () => {
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() => expect(screen.getAllByTestId("near-row").length).toBe(5));

    const badges = screen.getAllByTestId("state-badge").map((b) => b.textContent);
    expect(badges).toEqual(["NEAR", "NEAR", "NEAR", "WATCH", "WATCH"]);
    const symbols = screen.getAllByTestId("near-row")
      .map((row) => within(row).getAllByRole("cell")[0]?.textContent ?? "");
    expect(symbols[0]).toContain("JSWINFRA");   // score 90
    expect(symbols[2]).toContain("GLAND");      // score 72, still NEAR
    expect(symbols[3]).toContain("CASTROLIND"); // score 68, WATCH
  });

  it("marks the tight ranges and the 52-week highs", async () => {
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() => expect(screen.getAllByTestId("near-row").length).toBe(5));
    expect(screen.getAllByTestId("tight-marker")).toHaveLength(3);
    expect(screen.getAllByTestId("high-marker")).toHaveLength(2);
  });

  it("says nothing is near rather than showing an empty table", async () => {
    stub({ near: mock.EMPTY_NEAR });
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getByText(/nothing is near a level today/i)).toBeInTheDocument());
    expect(screen.queryAllByTestId("near-row")).toHaveLength(0);
  });
});

describe("recent breakouts", () => {
  it("colours the return since the breakout by its sign", async () => {
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getAllByTestId("breakout-row").length).toBe(3));

    const cells = screen.getAllByTestId("ret-since");
    expect(cells[0]).toHaveTextContent("+6.8%");
    expect(cells[0]?.className).toContain("text-up");
    expect(cells[1]).toHaveTextContent("−4.1%");
    expect(cells[1]?.className).toContain("text-down");
  });

  it("flags the ones that closed back under the level", async () => {
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getAllByTestId("breakout-row").length).toBe(3));
    expect(screen.getAllByTestId("false-flag")).toHaveLength(1);
  });

  it("refetches when the window changes", async () => {
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getAllByTestId("breakout-row").length).toBe(3));

    fireEvent.click(screen.getByRole("button", { name: "7d" }));
    await waitFor(() =>
      expect(api.fetchBreakouts).toHaveBeenCalledWith(7, "live"));
  });

  it("explains the empty window rather than leaving a blank panel", async () => {
    stub({ breakouts: mock.EMPTY_BREAKOUTS });
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getByText(/no confirmed breakouts in this window/i))
        .toBeInTheDocument());
  });
});

describe("the stock view", () => {
  it("opens from a board row and draws the ladder and the zone", async () => {
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() => expect(screen.getAllByTestId("near-row").length).toBe(5));

    fireEvent.click(screen.getAllByTestId("near-row")[0]!);
    // The chart, not just the panel: the panel renders a skeleton while the
    // stock query is still in flight.
    await waitFor(() =>
      expect(screen.getByTestId("tracker-chart")).toBeInTheDocument());

    // Three clusters in the fixture: one broken, and of the two unbroken the
    // NEAREST is drawn as its own thing.
    expect(screen.getAllByTestId("level-broken")).toHaveLength(1);
    expect(screen.getAllByTestId("level-nearest")).toHaveLength(1);
    expect(screen.getAllByTestId("level-unbroken")).toHaveLength(1);
    expect(screen.getByTestId("near-zone")).toBeInTheDocument();
    expect(screen.getByTestId("breakout-marker")).toBeInTheDocument();
  });

  it("shows the score taken apart into its five components", async () => {
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() => expect(screen.getAllByTestId("near-row").length).toBe(5));
    fireEvent.click(screen.getAllByTestId("near-row")[0]!);

    await waitFor(() =>
      expect(screen.getByTestId("score-components")).toBeInTheDocument());
    const components = screen.getByTestId("score-components");
    const labels = within(components).getAllByRole("term")
      .map((node) => node.textContent);
    // Heaviest weight first. `Object.entries` on the payload gives whatever
    // key order the JSON carried, which puts the 10% component above the 30%
    // one as often as not.
    expect(labels).toEqual([
      "Proximity", "Compression", "Trend", "Volume", "Touches"]);
  });

  it("lists the stock's episode history", async () => {
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() => expect(screen.getAllByTestId("near-row").length).toBe(5));
    fireEvent.click(screen.getAllByTestId("near-row")[0]!);
    await waitFor(() =>
      expect(screen.getAllByTestId("episode-row").length).toBe(3));
  });

  it("scrolls the panel into view, because it opens below a long board", async () => {
    // The board runs to a hundred rows and the panel renders under it. Without
    // the scroll the click opens a chart nobody can see, and reads as broken —
    // which is how it was reported on the live site.
    const scrollIntoView = window.HTMLElement.prototype
      .scrollIntoView as ReturnType<typeof vi.fn>;
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() => expect(screen.getAllByTestId("near-row").length).toBe(5));

    expect(scrollIntoView).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByTestId("near-row")[0]!);
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
    expect(scrollIntoView.mock.calls[0]![0]).toMatchObject({ block: "start" });
  });

  it("closes again", async () => {
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() => expect(screen.getAllByTestId("near-row").length).toBe(5));
    fireEvent.click(screen.getAllByTestId("near-row")[0]!);
    await waitFor(() =>
      expect(screen.getByTestId("stock-panel")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    await waitFor(() =>
      expect(screen.queryByTestId("stock-panel")).not.toBeInTheDocument());
  });
});

describe("the outcomes card", () => {
  it("renders both sources side by side", async () => {
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getByTestId("outcomes-card")).toBeInTheDocument());

    const columns = screen.getAllByTestId("source-column");
    expect(columns).toHaveLength(2);
    expect(within(columns[0]!).getByText(/replay/i)).toBeInTheDocument();
    expect(within(columns[1]!).getByText("Live")).toBeInTheDocument();
  });

  it("shows the decile table, including its negative top bucket", async () => {
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getAllByTestId("decile-row").length).toBe(4));

    const rows = screen.getAllByTestId("decile-row");
    const top = within(rows[3]!).getAllByRole("cell");
    expect(top[0]).toHaveTextContent("90-99");
    expect(top[2]).toHaveTextContent("70.2%");   // reached breakout
    expect(top[3]).toHaveTextContent("−0.45%");  // and still lost money
    expect(top[3]?.className).toContain("text-down");
  });

  it("says a live window has not closed yet instead of printing zeros", async () => {
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getByTestId("not-measured-yet")).toBeInTheDocument());
    expect(screen.getByTestId("not-measured-yet"))
      .toHaveTextContent(/40 trading days/i);
  });

  it("carries the caveats with the numbers", async () => {
    stub();
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() => expect(screen.getByTestId("caveats")).toBeInTheDocument());
    expect(screen.getByTestId("caveats")).toHaveTextContent(/survivorship/i);
  });

  it("renders an empty record without inventing a rate", async () => {
    stub({ replay: mock.EMPTY_STATS, live: mock.EMPTY_STATS });
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getAllByTestId("source-column").length).toBe(2));
    expect(screen.getAllByText(/no episodes yet/i).length).toBeGreaterThan(0);
    expect(screen.queryAllByTestId("decile-row")).toHaveLength(0);
  });
});

describe("the flag", () => {
  it("says the tracker is off, which is not the same as empty", async () => {
    stub({ health: mock.EMPTY_HEALTH });
    render(<NseTrackerPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getByText(/the tracker is not running/i)).toBeInTheDocument());
    expect(screen.queryByTestId("near-row")).not.toBeInTheDocument();
    expect(api.fetchNear).not.toHaveBeenCalled();
  });
});

describe("the chart on its own", () => {
  it("draws nothing but a message when there are no bars", () => {
    render(
      <TrackerChart candles={[]} clusters={[]} nearestResistance={null}
        nearPct={4} />,
    );
    expect(screen.getByText(/no bars yet/i)).toBeInTheDocument();
  });

  it("labels the nearest level with its price", () => {
    // "Show me the resistance line" should be answered by the chart, not by
    // cross-referencing the panel beside it.
    render(
      <TrackerChart candles={mock.MOCK_STOCK.candles}
        clusters={mock.MOCK_STOCK.levels!.clusters}
        nearestResistance={2229.5} nearPct={4} />,
    );
    expect(screen.getByTestId("nearest-label")).toHaveTextContent("2230");
  });

  it("omits the zone when nothing unbroken sits above the close", () => {
    render(
      <TrackerChart candles={mock.MOCK_STOCK.candles} clusters={[]}
        nearestResistance={null} nearPct={4} />,
    );
    expect(screen.queryByTestId("near-zone")).not.toBeInTheDocument();
    expect(screen.getByTestId("tracker-chart"))
      .toHaveAttribute("aria-label", expect.stringContaining("no unbroken"));
  });

  it("draws no breakout marker when the break is outside the loaded window", () => {
    // Not a bug: a marker cannot be placed on a bar the chart was not given.
    // Drawing it at the edge would put the breakout on the wrong day.
    const episode = { ...mock.MOCK_EPISODES.items[0]!,
      breakout_date: "2019-01-01" };
    render(
      <TrackerChart candles={mock.MOCK_STOCK.candles} clusters={[]}
        nearestResistance={null} nearPct={4} episode={episode} />,
    );
    expect(screen.queryByTestId("breakout-marker")).not.toBeInTheDocument();
  });

  it("marks a bar that sits across a corporate action", () => {
    const candles = mock.MOCK_STOCK.candles.map((c, i) =>
      i === 10 ? { ...c, suspect: true } : c);
    render(
      <TrackerChart candles={candles} clusters={[]} nearestResistance={null}
        nearPct={4} />,
    );
    expect(screen.getAllByTestId("suspect-bar")).toHaveLength(1);
  });
});
