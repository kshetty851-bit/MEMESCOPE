import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LiveTab } from "./live";
import { RangeChart } from "./charts";
import { book, candles, signal, status, waitSignal } from "./fixtures";

afterEach(cleanup);

const heroIds = () =>
  Array.from(screen.getByTestId("hero").querySelectorAll('[data-testid^="hero-"]')).map(
    (el) => el.getAttribute("data-testid"),
  );

describe("hero strip", () => {
  it("reads price, range, call, entry, TP, SL, confidence, P&L in that order", () => {
    render(<LiveTab status={status()} />);
    expect(heroIds()).toEqual([
      "hero-price",
      "hero-range",
      "hero-call",
      "hero-entry",
      "hero-tp",
      "hero-sl",
      "hero-confidence",
      "hero-pnl",
    ]);

    expect(screen.getByTestId("hero-price")).toHaveTextContent("$66,123.45");
    expect(screen.getByTestId("hero-range")).toHaveTextContent("$65,800–$67,200");
    expect(screen.getByTestId("hero-range")).toHaveTextContent("width 2.13%");
    expect(screen.getByTestId("hero-call")).toHaveTextContent("Paper strategy call");
    expect(screen.getByTestId("hero-call")).toHaveTextContent("LONG");
    expect(screen.getByTestId("hero-entry")).toHaveTextContent("$66,120.00");
    expect(screen.getByTestId("hero-tp")).toHaveTextContent("$66,950.00");
    expect(screen.getByTestId("hero-sl")).toHaveTextContent("$65,700.00");
    expect(screen.getByTestId("hero-confidence")).toHaveTextContent("72");
    expect(screen.getByTestId("hero-pnl")).toHaveTextContent("+$125.50");
    expect(screen.getByTestId("hero-pnl")).toHaveTextContent("+1.26% return");
  });

  it("shows a dash, never an estimate, for entry / TP / SL on WAIT", () => {
    render(<LiveTab status={status({ signal: waitSignal() })} />);
    expect(screen.getByTestId("hero-call")).toHaveTextContent("WAIT");
    for (const id of ["hero-entry", "hero-tp", "hero-sl"]) {
      expect(screen.getByTestId(id)).toHaveTextContent("—");
      expect(screen.getByTestId(id)).not.toHaveTextContent("$");
    }
  });

  it("tones the chip by call", () => {
    const { rerender } = render(
      <LiveTab status={status({ signal: signal({ call: "short" }) })} />,
    );
    expect(within(screen.getByTestId("hero-call")).getByText("SHORT").className).toMatch(
      /text-down/,
    );
    rerender(<LiveTab status={status({ signal: waitSignal() })} />);
    expect(within(screen.getByTestId("hero-call")).getByText("WAIT").className).not.toMatch(
      /text-(up|down)\b/,
    );
  });

  it("copes with a null signal and a null book", () => {
    render(<LiveTab status={status({ signal: null, book: null, price: null })} />);
    expect(screen.getByTestId("hero-call")).toHaveTextContent("—");
    expect(screen.getByTestId("hero-pnl")).toHaveTextContent("—");
    expect(screen.getByTestId("no-book")).toBeInTheDocument();
    expect(screen.getByText("No signal has been computed yet.")).toBeInTheDocument();
  });
});

describe("states", () => {
  it("shows the server's reason when the lab is not running", () => {
    render(
      <LiveTab
        status={status({
          running: false,
          reason: "LAB_BTC_RANGE_ENABLED is off.",
          signal: null,
          book: null,
        })}
      />,
    );
    expect(screen.getByText("The BTC Range Lab is not running")).toBeInTheDocument();
    expect(screen.getByText("LAB_BTC_RANGE_ENABLED is off.")).toBeInTheDocument();
    expect(screen.queryByTestId("hero")).not.toBeInTheDocument();
  });

  it("flags stale data", () => {
    render(
      <LiveTab
        status={status({
          data: {
            candles: 192,
            first_at: null,
            last_closed_at: "2026-10-08T00:00:00Z",
            stale: true,
          },
        })}
      />,
    );
    expect(screen.getByText("Stale data")).toBeInTheDocument();
  });

  it("notes a server reason while running", () => {
    render(<LiveTab status={status({ reason: "Only 40 candles are stored." })} />);
    expect(screen.getByText("Only 40 candles are stored.")).toBeInTheDocument();
  });

  it("renders the server's reason sentences verbatim", () => {
    render(<LiveTab status={status()} />);
    const list = screen.getByTestId("reasons");
    expect(list).toHaveTextContent("Price is in the lower fifth of the range.");
    expect(list).toHaveTextContent("Support has been touched 3 times.");
  });
});

describe("paper book", () => {
  it("renders LONG vs SHORT from book.long and book.short", () => {
    render(<LiveTab status={status()} />);
    const table = screen.getByTestId("side-table");
    expect(within(table).getByRole("columnheader", { name: "Long" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Short" })).toBeInTheDocument();
    const netRow = within(table).getByRole("row", { name: /Net P&L/ });
    expect(netRow).toHaveTextContent("+$90.00");
    expect(netRow).toHaveTextContent("-$12.25");
    // No losing trade on SHORT: the profit factor is undefined, not infinite.
    expect(within(table).getByRole("row", { name: /Profit factor/ })).toHaveTextContent(
      "1.72—",
    );
  });

  it("shows the seven headline figures", () => {
    render(<LiveTab status={status()} />);
    const stats = screen.getByTestId("metrics-stats");
    for (const label of [
      "Net P&L",
      "Win rate",
      "Profit factor",
      "Expectancy",
      "Max drawdown",
      "Trades",
      "Ending equity",
    ]) {
      expect(within(stats).getByText(label)).toBeInTheDocument();
    }
    expect(stats).toHaveTextContent("60.0%");
    expect(stats).toHaveTextContent("$10,125.50");
  });

  it("lists trades with side, exit reason, fees, P&L and R", () => {
    render(<LiveTab status={status()} />);
    const rows = screen.getAllByRole("row");
    const text = rows.map((r) => r.textContent).join("\n");
    expect(text).toContain("Take profit");
    expect(text).toContain("Stop loss");
    expect(text).toContain("$6.60");
    expect(text).toContain("+1.87R");
    expect(text).toContain("-1.00R");
  });

  it("shows an open position card, or says none is open", () => {
    const { rerender } = render(<LiveTab status={status()} />);
    expect(screen.getByTestId("open-position")).toHaveTextContent("No position is open.");
    rerender(
      <LiveTab
        status={status({
          book: book({
            open_position: {
              side: "short",
              signal_at: "2026-10-08T02:45:00Z",
              entry_at: "2026-10-08T03:00:00Z",
              entry_price: "67100.00",
              take_profit: "66200.00",
              stop_loss: "67500.00",
              quantity: "0.05",
              notional: "3355.00",
              mark_price: "66900.00",
              unrealised_pnl: "10.00",
            },
          }),
        })}
      />,
    );
    const card = screen.getByTestId("open-position");
    expect(card).toHaveTextContent("SHORT");
    expect(card).toHaveTextContent("$66,900.00");
    expect(card).toHaveTextContent("+$10.00");
  });

  it("says so when there are no closed trades", () => {
    render(<LiveTab status={status({ book: book({ trades: [], equity_curve: [] }) })} />);
    expect(screen.getByText("No closed paper trades.")).toBeInTheDocument();
    expect(screen.getByTestId("equity-empty")).toBeInTheDocument();
  });

  it("draws the equity curve with an accessible label", () => {
    render(<LiveTab status={status()} />);
    expect(
      screen.getByRole("img", { name: /Paper equity from \$10,000\.00 to \$10,125\.50/ }),
    ).toBeInTheDocument();
  });
});

describe("range chart", () => {
  it("draws the band, entry zones and entry/TP/SL lines on an active call", () => {
    render(<RangeChart candles={candles()} signal={signal()} entryZone="0.2" />);
    expect(screen.getByTestId("range-band")).toBeInTheDocument();
    expect(screen.getByTestId("long-zone")).toBeInTheDocument();
    expect(screen.getByTestId("short-zone")).toBeInTheDocument();
    expect(screen.getByTestId("line-entry")).toBeInTheDocument();
    expect(screen.getByTestId("line-tp")).toBeInTheDocument();
    expect(screen.getByTestId("line-sl")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Paper call LONG/ })).toBeInTheDocument();
  });

  it("draws no entry/TP/SL lines on WAIT, and no zones without a config", () => {
    render(<RangeChart candles={candles()} signal={waitSignal()} />);
    expect(screen.getByTestId("range-band")).toBeInTheDocument();
    expect(screen.queryByTestId("line-entry")).not.toBeInTheDocument();
    expect(screen.queryByTestId("line-tp")).not.toBeInTheDocument();
    expect(screen.queryByTestId("long-zone")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Paper call WAIT/ })).toBeInTheDocument();
  });

  it("says so when there are too few candles", () => {
    render(<RangeChart candles={candles(1)} signal={signal()} />);
    expect(screen.getByTestId("range-chart-empty")).toBeInTheDocument();
  });
});
