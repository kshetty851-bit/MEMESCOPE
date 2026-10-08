import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";

import * as api from "./api";
import { backtest, config } from "./fixtures";
import { StrategyLab } from "./strategy-lab";

vi.mock("./api");

function wrap(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const field = (name: string) =>
  document.querySelector<HTMLInputElement>(`[name="${name}"]`)!;

beforeEach(() => {
  vi.mocked(api.runBacktest).mockResolvedValue(backtest());
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("Strategy Lab form", () => {
  it("builds one field per bound, grouped, with labels, help and defaults", () => {
    const cfg = config();
    wrap(<StrategyLab config={cfg} />);

    for (const group of ["range", "entries", "account"]) {
      expect(screen.getByTestId(`group-${group}`)).toBeInTheDocument();
    }
    expect(
      within(screen.getByTestId("group-range")).getByLabelText("Lookback candles"),
    ).toHaveValue(96);
    expect(
      within(screen.getByTestId("group-account")).getByLabelText("Starting balance"),
    ).toHaveValue(10000);

    const lookback = field("lookback");
    expect(lookback).toHaveAttribute("type", "number");
    expect(lookback).toHaveAttribute("min", "24");
    expect(lookback).toHaveAttribute("max", "500");
    expect(lookback).toHaveAttribute("step", "1");
    expect(screen.getByText(/Lookback candles help\./)).toBeInTheDocument();

    // bool kind renders a checkbox, defaulted on
    expect(screen.getByRole("checkbox", { name: /Allow LONG calls/ })).toBeChecked();
    // one input per numeric bound, plus the two dates
    const numeric = Object.values(cfg.bounds).filter((b) => b.kind !== "bool").length;
    expect(document.querySelectorAll('input[type="number"]')).toHaveLength(numeric);
  });

  it("defaults the window to the last 30 days, bounded by the stored data", () => {
    wrap(<StrategyLab config={config()} />);
    expect(field("start")).toHaveValue("2026-09-08");
    expect(field("end")).toHaveValue("2026-10-08");
    expect(field("start")).toHaveAttribute("min", "2026-08-01");
    expect(field("end")).toHaveAttribute("max", "2026-10-08");
  });

  it("posts the edited config and the window", async () => {
    wrap(<StrategyLab config={config()} />);
    fireEvent.change(field("lookback"), { target: { value: "120" } });
    fireEvent.change(field("min_reward_risk"), { target: { value: "2.0" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Allow SHORT calls/ }));
    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));

    await waitFor(() => expect(api.runBacktest).toHaveBeenCalledTimes(1));
    const body = vi.mocked(api.runBacktest).mock.calls[0]![0];
    expect(body.config).toMatchObject({
      lookback: 120, // int -> number
      min_reward_risk: "2.0", // decimal stays a string
      allow_short: false,
      allow_long: true,
      starting_balance: "10000",
    });
    expect(body.start).toBe("2026-09-08T00:00:00Z");
    // end of the last stored day is clamped to the latest stored candle
    expect(body.end).toBe("2026-10-08T03:00:00Z");
  });

  it("blocks the post and points at the field when a value is out of bounds", async () => {
    wrap(<StrategyLab config={config()} />);
    fireEvent.change(field("lookback"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));

    expect(await screen.findByText("Must be at least 24.")).toBeInTheDocument();
    expect(field("lookback")).toHaveAttribute("aria-invalid", "true");
    expect(api.runBacktest).not.toHaveBeenCalled();
  });

  it("blocks the post when the window is outside the stored data", () => {
    wrap(<StrategyLab config={config()} />);
    fireEvent.change(field("start"), { target: { value: "2026-07-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));
    expect(screen.getByText(/Stored candles begin on 2026-08-01/)).toBeInTheDocument();
    expect(api.runBacktest).not.toHaveBeenCalled();
  });

  it("resets every field and the window to the defaults", () => {
    wrap(<StrategyLab config={config()} />);
    fireEvent.change(field("lookback"), { target: { value: "300" } });
    fireEvent.change(field("start"), { target: { value: "2026-10-01" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Allow LONG calls/ }));
    fireEvent.click(screen.getByRole("button", { name: "Reset to defaults" }));
    expect(field("lookback")).toHaveValue(96);
    expect(field("start")).toHaveValue("2026-09-08");
    expect(screen.getByRole("checkbox", { name: /Allow LONG calls/ })).toBeChecked();
  });

  it("shows an API failure instead of a result", async () => {
    vi.mocked(api.runBacktest).mockRejectedValue(
      new ApiError(422, "validation_error", "lookback is too small"),
    );
    wrap(<StrategyLab config={config()} />);
    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));
    expect(await screen.findByText(/lookback is too small/)).toBeInTheDocument();
  });
});

describe("backtest results", () => {
  it("shows the reason, and nothing else, when the backtest is unavailable", async () => {
    vi.mocked(api.runBacktest).mockResolvedValue(
      backtest({ available: false, reason: "Only 12 candles are stored for this window." }),
    );
    wrap(<StrategyLab config={config()} />);
    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));

    const box = await screen.findByTestId("backtest-unavailable");
    expect(box).toHaveTextContent("Only 12 candles are stored for this window.");
    expect(screen.queryByTestId("backtest-results")).not.toBeInTheDocument();
  });

  it("shows metrics, LONG vs SHORT, call counts, WAIT reasons, trades and the config that ran", async () => {
    wrap(<StrategyLab config={config()} />);
    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));

    const results = await screen.findByTestId("backtest-results");
    expect(within(results).getByTestId("metrics-stats")).toHaveTextContent("$10,125.50");
    expect(within(results).getByTestId("side-table")).toHaveTextContent("-$74.50");

    const counts = within(results).getByTestId("signal-counts");
    expect(counts).toHaveTextContent("LONG14");
    expect(counts).toHaveTextContent("SHORT9");
    expect(counts).toHaveTextContent("WAIT2877");

    const waits = within(results).getByTestId("wait-reasons");
    expect(waits).toHaveTextContent("Price was in the middle of the range.");
    expect(waits).toHaveTextContent("1500");
    expect(waits).toHaveTextContent("No tradable range was found.");

    expect(within(results).getByText("Take profit")).toBeInTheDocument();
    // The config shown is the one the server reports it ran, not the form's.
    expect(
      within(results).getByTestId("config-run").querySelector('[data-key="lookback"]'),
    ).toHaveTextContent("120");
    expect(
      within(results).getByTestId("config-run").querySelector('[data-key="allow_long"]'),
    ).toHaveTextContent("Yes");
  });
});
