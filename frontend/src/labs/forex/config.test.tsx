import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";

import * as api from "./api";
import { buildConfig, fieldsFor, initialValues, validate } from "./config";
import { dataOut, meta, run } from "./fixtures";
import { ForexLabPage } from "./page";

vi.mock("./api");

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ForexLabPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.fetchMeta).mockResolvedValue(meta());
  vi.mocked(api.fetchData).mockResolvedValue(dataOut());
  vi.mocked(api.fetchVersions).mockResolvedValue({ versions: [] });
  vi.mocked(api.fetchRuns).mockResolvedValue({ runs: [] });
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("config builder", () => {
  const m = meta();
  const strat = m.strategies[0]!;
  const fields = fieldsFor(m, strat);

  it("sends money as strings and counts as numbers", () => {
    const values = {
      ...initialValues(m, strat),
      "risk.initial_capital": "2500",
      "risk.max_leverage": "10",
    };
    const cfg = buildConfig(strat, fields, values);
    expect(cfg.risk["initial_capital"]).toBe("2500");
    expect(cfg.risk["risk_per_trade_pct"]).toBe("0.5");
    expect(cfg.risk["max_daily_loss_pct"]).toBe("3");
    expect(cfg.costs["commission_per_lot_side"]).toBe("3.50");
    expect(cfg.risk["max_leverage"]).toBe(10);
    expect(cfg.risk["max_trades_per_day"]).toBe(3);
    expect(cfg.costs["spread_pips"]).toBe(1);
    expect(cfg.costs["financing_enabled"]).toBe(true);
    expect(cfg.session_filter).toBeNull();
    // Untouched fields keep the server's defaults, including nested sessions.
    expect(cfg.params["trading_session"]).toEqual({
      start_hour: 7,
      end_hour: 10,
      start_minute: 0,
      end_minute: 0,
    });
  });

  it("builds a session filter from HH:MM-HH:MM", () => {
    const values = { ...initialValues(m, strat), session_filter: "08:30-11:00" };
    expect(buildConfig(strat, fields, values).session_filter).toEqual({
      start_hour: 8,
      start_minute: 30,
      end_hour: 11,
      end_minute: 0,
    });
  });

  it("refuses leverage above 20", () => {
    const errors = validate(fields, {
      ...initialValues(m, strat),
      "risk.max_leverage": "25",
    });
    expect(errors["risk.max_leverage"]).toBe("At most 20.");
  });
});

describe("configure and run", () => {
  async function openConfigure() {
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Configure" }));
    return screen.findByTestId("configure");
  }

  it("posts a backtest body with string money fields", async () => {
    vi.mocked(api.createRun).mockResolvedValue(run({ status: "queued", progress: 0 }));
    vi.mocked(api.fetchRun).mockResolvedValue({
      run: run({ status: "queued", progress: 0 }),
      result: null,
    });
    await openConfigure();

    const capital = document.querySelector<HTMLInputElement>(
      '[name="risk.initial_capital"]',
    )!;
    fireEvent.change(capital, { target: { value: "5000" } });
    // The date range defaults to what is stored for the chosen market.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Run backtest" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));

    await waitFor(() => expect(api.createRun).toHaveBeenCalled());
    const body = vi.mocked(api.createRun).mock.calls[0]![0];
    expect(body.kind).toBe("backtest");
    expect(body.start).toBe("2025-01-01T00:00:00Z");
    expect(body.end).toBe("2025-12-31T23:59:59Z");
    expect(body.config?.strategy).toBe("london_breakout");
    expect(body.config?.risk["initial_capital"]).toBe("5000");
    expect(typeof body.config?.risk["risk_per_trade_pct"]).toBe("string");
    expect(typeof body.config?.costs["commission_per_lot_side"]).toBe("string");
    expect(body.config?.risk["max_leverage"]).toBe(20);
    // On start the page moves to the run.
    expect(await screen.findByTestId("run-progress")).toBeInTheDocument();
  });

  it("sends research options with the strategy's grid", async () => {
    vi.mocked(api.createRun).mockResolvedValue(run({ kind: "research", status: "queued" }));
    vi.mocked(api.fetchRun).mockResolvedValue({
      run: run({ kind: "research", status: "queued" }),
      result: null,
    });
    await openConfigure();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Run research/ })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Run research/ }));
    await waitFor(() => expect(api.createRun).toHaveBeenCalled());
    const body = vi.mocked(api.createRun).mock.calls[0]![0];
    expect(body.kind).toBe("research");
    expect(body.options?.grid).toEqual({ "params.risk_reward": [1.5, 2, 3] });
    expect(body.options?.walk_forward).toEqual({ train_days: 90, test_days: 30 });
  });

  it("asks for a sign-in on a 401", async () => {
    vi.mocked(api.createRun).mockRejectedValue(
      new ApiError(401, "unauthorized", "Unauthorized"),
    );
    await openConfigure();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Run backtest" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Run backtest" }));
    expect(await screen.findByText("Sign in to run backtests.")).toBeInTheDocument();
  });

  it("blocks the run when leverage is over 20, and resets to defaults", async () => {
    await openConfigure();
    const lev = document.querySelector<HTMLInputElement>('[name="risk.max_leverage"]')!;
    fireEvent.change(lev, { target: { value: "30" } });
    expect(await screen.findByText("At most 20.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run backtest" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reset to defaults" }));
    await waitFor(() => expect(lev.value).toBe("20"));
  });

  it("saves a version and loads a saved one into the form", async () => {
    const saved = {
      id: 3,
      name: "tight",
      version: 1,
      strategy: "rsi_pullback",
      config: {
        ...meta().strategies[1]!.default_config,
        risk: { ...meta().strategies[1]!.default_config.risk, initial_capital: "777" },
      },
      notes: null,
      created_at: "2026-10-10T08:00:00Z",
    };
    vi.mocked(api.fetchVersions).mockResolvedValue({ versions: [saved] });
    vi.mocked(api.createVersion).mockResolvedValue({ ...saved, id: 4, name: "mine" });
    await openConfigure();

    fireEvent.click(await screen.findByRole("button", { name: "Load tight version 1" }));
    await waitFor(() =>
      expect(
        document.querySelector<HTMLInputElement>('[name="risk.initial_capital"]')!.value,
      ).toBe("777"),
    );
    expect((document.querySelector('[name="strategy"]') as HTMLSelectElement).value).toBe(
      "rsi_pullback",
    );

    fireEvent.change(document.querySelector('[name="version-name"]')!, {
      target: { value: "mine" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save as version" }));
    await waitFor(() => expect(api.createVersion).toHaveBeenCalled());
    const body = vi.mocked(api.createVersion).mock.calls[0]![0];
    expect(body.name).toBe("mine");
    expect(body.config.risk["initial_capital"]).toBe("777");
    expect(await screen.findByTestId("version-notice")).toHaveTextContent(
      "Saved mine version 1.",
    );
  });
});
