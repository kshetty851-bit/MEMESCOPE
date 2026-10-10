import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NAV_GROUPS } from "@/lib/design/nav";

import * as api from "./api";
import {
  backtestDetail,
  compareResult,
  dataOut,
  importBatch,
  meta,
  quality,
  run,
} from "./fixtures";
import { PAPER_BANNER, ForexLabPage } from "./page";

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

/** Product rule: the page never advises. Held over everything it renders. */
const BANNED = /\b(buy|buying|sell|selling|should|consider|recommend\w*|advice)\b/i;

beforeEach(() => {
  vi.mocked(api.fetchMeta).mockResolvedValue(meta());
  vi.mocked(api.fetchData).mockResolvedValue(dataOut());
  vi.mocked(api.fetchQuality).mockResolvedValue(quality());
  vi.mocked(api.fetchVersions).mockResolvedValue({ versions: [] });
  vi.mocked(api.fetchRuns).mockResolvedValue({
    runs: [run(), run({ id: 8, kind: "compare", name: "All", summary: null })],
  });
});
afterEach(() => {
  vi.useRealTimers();
  cleanup();
  vi.resetAllMocks();
});

describe("Forex Lab page", () => {
  it("renders the six tabs and the paper-only notice", async () => {
    renderPage();
    for (const name of [
      "Data",
      "Configure",
      "Results",
      "Research",
      "Compare",
      "Experiments",
    ]) {
      expect(screen.getByRole("tab", { name })).toBeInTheDocument();
    }
    expect(screen.getByTestId("paper-banner")).toHaveTextContent(
      "Research and paper only — no broker connection, no live trading.",
    );
    expect(PAPER_BANNER).toContain("no live trading");
    expect(await screen.findByTestId("datasets")).toBeInTheDocument();
  });

  it("is listed in the navigation", () => {
    const items = NAV_GROUPS.flatMap((g) => g.items);
    const item = items.find((i) => i.href === "/forex-lab");
    expect(item?.label).toBe("Forex Lab");
    expect(item?.status).toBe("ready");
  });

  it("shows datasets, quality grade, gaps, providers and notes", async () => {
    renderPage();
    expect(await screen.findByText("74,000")).toBeInTheDocument();
    expect(await screen.findByTestId("quality-view")).toHaveTextContent("Coverage 99.33%");
    expect(screen.getByTestId("quality-notes")).toHaveTextContent(
      "Weekend closures are not counted as gaps.",
    );
    expect(screen.getByTestId("providers")).toHaveTextContent("no key");
    expect(screen.getByTestId("providers")).toHaveTextContent("free");
  });

  it("imports a CSV read in the browser and reports inserted and existing rows", async () => {
    vi.mocked(api.importCsv).mockResolvedValue(importBatch());
    renderPage();
    await screen.findByTestId("import-form");
    const file = new File(["time,open,high,low,close\n"], "eurusd.csv", {
      type: "text/csv",
    });
    fireEvent.change(document.getElementById("csv-file")!, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    await waitFor(() => expect(api.importCsv).toHaveBeenCalled());
    const body = vi.mocked(api.importCsv).mock.calls[0]![0];
    expect(body).toMatchObject({
      filename: "eurusd.csv",
      symbol: "EURUSD",
      fmt: "auto",
      utc_offset_minutes: 0,
    });
    expect(body.content).toContain("time,open,high,low,close");
    expect(await screen.findByTestId("rows-inserted")).toHaveTextContent("90");
    expect(screen.getByTestId("rows-existing")).toHaveTextContent("10");
    expect(screen.getByTestId("import-errors")).toHaveTextContent("Line 4: bad price");
  });

  it("starts a Dukascopy fetch and shows its progress", async () => {
    const fetchRun = run({
      id: 21,
      kind: "fetch",
      status: "running",
      progress: 35,
      message: "Fetching 2025-03",
    });
    vi.mocked(api.startFetch).mockResolvedValue(fetchRun);
    vi.mocked(api.fetchRun).mockResolvedValue({ run: fetchRun, result: null });
    renderPage();
    await screen.findByTestId("fetch-form");
    fireEvent.change(document.querySelector('[name="fetch-start"]')!, {
      target: { value: "2025-03-01" },
    });
    fireEvent.change(document.querySelector('[name="fetch-end"]')!, {
      target: { value: "2025-03-31" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Fetch" }));
    await waitFor(() =>
      expect(api.startFetch).toHaveBeenCalledWith({
        provider: "dukascopy",
        symbol: "EURUSD",
        start_date: "2025-03-01",
        end_date: "2025-03-31",
      }),
    );
    expect(await screen.findByText("Fetching 2025-03")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "35");
  });

  it("opens a saved experiment from the list into Results", async () => {
    vi.mocked(api.fetchRun).mockResolvedValue(backtestDetail());
    renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Experiments" }));
    fireEvent.click(await screen.findByRole("button", { name: "London breakout 2025" }));
    expect(await screen.findByTestId("backtest-view")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Results" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("compares all strategies and renders the ranked table", async () => {
    const queued = run({ id: 30, kind: "compare", status: "queued" });
    vi.mocked(api.createRun).mockResolvedValue(queued);
    vi.mocked(api.fetchRun).mockResolvedValue({
      run: { ...queued, status: "done", progress: 100 },
      result: compareResult(),
    });
    renderPage();
    // Wait for the default date range to arrive from the stored data.
    fireEvent.click(await screen.findByRole("tab", { name: "Compare" }));
    const button = screen.getByRole("button", { name: "Compare all strategies" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(api.createRun).toHaveBeenCalled());
    expect(vi.mocked(api.createRun).mock.calls[0]![0]).toMatchObject({ kind: "compare" });
    expect(await screen.findByTestId("compare-view")).toBeInTheDocument();
  });

  it("polls a running run every two seconds and stops once it is done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const running = {
      run: run({ status: "running", progress: 50, message: "Halfway" }),
      result: null,
    };
    vi.mocked(api.fetchRun)
      .mockResolvedValueOnce(running)
      .mockResolvedValue(backtestDetail());
    renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Experiments" }));
    fireEvent.click(await screen.findByRole("button", { name: "London breakout 2025" }));
    expect(await screen.findByText("Halfway")).toBeInTheDocument();
    expect(api.fetchRun).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(await screen.findByTestId("backtest-view")).toBeInTheDocument();
    const calls = vi.mocked(api.fetchRun).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(vi.mocked(api.fetchRun).mock.calls.length).toBe(calls);
  });

  it("never uses advisory language in what it renders", async () => {
    vi.mocked(api.fetchRun).mockResolvedValue(backtestDetail());
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Experiments" }));
    fireEvent.click(await screen.findByRole("button", { name: "London breakout 2025" }));
    await screen.findByTestId("backtest-view");
    expect(container.textContent).not.toMatch(BANNED);
  });
});
