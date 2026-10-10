import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CompareView } from "./compare";
import {
  DISCLAIMER,
  backtestDetail,
  backtestResult,
  compareResult,
  metrics,
  run,
  researchResult,
} from "./fixtures";
import { ResearchView } from "./research";
import { BacktestView } from "./results";
import { RunStatus } from "./run-status";
import { TargetPanel } from "./targets";
import { MetricTiles } from "./metrics";

afterEach(cleanup);

const METRIC_IDS = [
  "starting-balance",
  "ending-balance",
  "net-pnl",
  "net-return",
  "win-rate",
  "trades",
  "avg-win",
  "avg-loss",
  "profit-factor",
  "expectancy-usd",
  "expectancy-r",
  "max-drawdown",
  "sharpe",
  "loss-streak",
  "long-short",
  "costs",
  "margin",
  "frequency",
];

describe("backtest results", () => {
  it("renders all eighteen metric tiles, money as formatted strings", () => {
    render(<BacktestView detail={backtestDetail()} disclaimer={DISCLAIMER} />);
    for (const id of METRIC_IDS)
      expect(screen.getByTestId(`metric-${id}`)).toBeInTheDocument();
    expect(METRIC_IDS).toHaveLength(18);
    expect(
      within(screen.getByTestId("metric-ending-balance")).getByText("$1,062.40"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("metric-net-pnl")).getByText("+$62.40"),
    ).toBeInTheDocument();
  });

  it("shows 'not meaningful' and the API's note when Sharpe is null", () => {
    render(<MetricTiles metrics={metrics()} />);
    const tile = screen.getByTestId("metric-sharpe");
    expect(within(tile).getByText("not meaningful")).toBeInTheDocument();
    expect(
      within(tile).getByText(
        "Fewer than 30 daily returns, so a ratio would not be meaningful.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a dash, not a zero, for a null metric", () => {
    render(
      <MetricTiles metrics={metrics({ profit_factor: null, expectancy_usd: null })} />,
    );
    expect(
      within(screen.getByTestId("metric-profit-factor")).getByText("—"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("metric-expectancy-usd")).getByText("—"),
    ).toBeInTheDocument();
  });

  it("lists losing trades in the log, in the loss colour, and pages client-side", () => {
    render(<BacktestView detail={backtestDetail()} />);
    const log = screen.getByTestId("trade-log");
    const stops = within(log).getAllByText("Stop loss");
    expect(stops.length).toBeGreaterThan(0);
    const row = stops[0]!.closest("tr")!;
    expect(within(row).getByText("-$5.20")).toHaveClass("text-down");
    expect(within(row).getByText("-1.10")).toBeInTheDocument();
    expect(screen.getByTestId("trade-range")).toHaveTextContent("Trades 1–25 of 30");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByTestId("trade-range")).toHaveTextContent("Trades 26–30 of 30");
  });

  it("links the trades CSV at the API path for this run", () => {
    render(<BacktestView detail={backtestDetail()} />);
    expect(screen.getByTestId("export-trades").getAttribute("href")).toMatch(
      /\/api\/v1\/labs\/forex\/runs\/7\/trades\.csv$/,
    );
  });

  it("lists assumptions and skipped signals using the API's text", () => {
    render(<BacktestView detail={backtestDetail()} />);
    expect(
      screen.getByText("Entries fill at the open of the bar after the signal."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("The daily trade limit was already reached."),
    ).toBeInTheDocument();
  });

  it("draws a negative month as a negative bar", () => {
    render(<BacktestView detail={backtestDetail()} />);
    const bars = screen.getAllByTestId("month-bar");
    expect(bars.map((b) => b.getAttribute("data-negative"))).toEqual([
      "false",
      "true",
      "false",
    ]);
    expect(bars[1]).toHaveAttribute("fill", "var(--color-down)");
  });

  it("reads out the date and equity under the pointer", () => {
    render(<BacktestView detail={backtestDetail()} />);
    const svg = screen.getByTestId("equity-svg");
    svg.getBoundingClientRect = () =>
      ({
        left: 0,
        top: 0,
        width: 900,
        height: 240,
        right: 900,
        bottom: 240,
        x: 0,
        y: 0,
        toJSON() {},
      }) as DOMRect;
    expect(screen.queryByTestId("equity-cursor")).toBeNull();
    fireEvent.mouseMove(svg, { clientX: 0 });
    expect(screen.getByTestId("equity-cursor")).toBeInTheDocument();
    expect(screen.getByTestId("equity-readout")).toHaveTextContent("1 Mar 2025");
    expect(screen.getByTestId("equity-readout")).toHaveTextContent("$994.00");
    fireEvent.mouseMove(svg, { clientX: 900 });
    expect(screen.getByTestId("equity-readout")).toHaveTextContent("30 Mar 2025");
  });

  it("renders nothing but the progress while the run is still going", () => {
    const detail = {
      run: run({ status: "running", progress: 40, message: "Replaying candles" }),
      result: null,
    };
    render(<BacktestView detail={detail} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
    expect(screen.getByText("Replaying candles")).toBeInTheDocument();
  });
});

describe("run status", () => {
  it("shows a failed run's error verbatim", () => {
    render(
      <RunStatus
        run={run({
          status: "failed",
          error: "ValueError: no candles in window\n  at engine",
        })}
      />,
    );
    expect(screen.getByTestId("run-failed")).toHaveTextContent(
      "ValueError: no candles in window",
    );
  });
});

describe("monthly target analysis", () => {
  it("states the disclaimer prominently and lists every target row", () => {
    render(
      <TargetPanel
        title="Monthly target analysis"
        report={backtestResult().targets}
        disclaimer={DISCLAIMER}
      />,
    );
    expect(screen.getByTestId("target-disclaimer")).toHaveTextContent(DISCLAIMER.text);
    expect(screen.getByTestId("target-disclaimer")).toHaveTextContent(/not a forecast/i);
    for (const t of ["5%", "10%", "20%", "50%", "100%"])
      expect(screen.getByText(t)).toBeInTheDocument();
    expect(screen.getByText("Profitable months")).toBeInTheDocument();
    expect(screen.getByText("Jun 2025 +7.40%")).toBeInTheDocument();
    expect(screen.getByText("Sep 2025 -3.80%")).toBeInTheDocument();
    const ruin = screen.getByTestId("risk-of-ruin");
    expect(ruin).toHaveTextContent("0.20%");
    expect(ruin).toHaveTextContent("Trades are treated as independent draws");
  });

  it("falls back to the fixed disclaimer when none is supplied", () => {
    render(<TargetPanel title="t" report={{}} />);
    expect(screen.getByTestId("target-disclaimer")).toHaveTextContent(/not a forecast/i);
  });
});

describe("comparison", () => {
  it("orders scorecards by rank and shows flags and the API's verdict text", () => {
    render(
      <CompareView detail={{ run: run({ kind: "compare" }), result: compareResult() }} />,
    );
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("London breakout");
    expect(rows[1]).toHaveTextContent("RSI pullback");
    expect(rows[2]).toHaveTextContent("Bollinger reversion");
    expect(rows[1]).toHaveTextContent("Out-of-sample expectancy is negative.");
    expect(rows[0]).toHaveTextContent(
      "Verdict text for London breakout: the evidence is mixed.",
    );
  });

  it("never calls anything profitable", () => {
    const { container } = render(
      <CompareView detail={{ run: run({ kind: "compare" }), result: compareResult() }} />,
    );
    expect(container.textContent).not.toMatch(/profitable/i);
  });
});

describe("research", () => {
  it("labels the test window as untouched and renders the sections", () => {
    render(
      <ResearchView
        detail={{ run: run({ kind: "research" }), result: researchResult() }}
        disclaimer={DISCLAIMER}
      />,
    );
    expect(screen.getByTestId("period-test")).toHaveTextContent(
      "Untouched until this run; never used for selection.",
    );
    for (const id of [
      "period-development",
      "period-validation",
      "optimisation",
      "walk-forward",
      "sensitivity",
      "stability",
      "cost-stress",
      "regimes",
      "baseline",
      "monte-carlo",
      "bootstrap",
      "scorecard",
      "target-full",
      "target-oos",
    ]) {
      expect(screen.getByTestId(id)).toBeInTheDocument();
    }
    expect(screen.getByTestId("selection-note")).toHaveTextContent(
      "chosen on the development window only",
    );
    expect(screen.getByTestId("period-test")).toHaveTextContent("-0.80%");
  });
});
