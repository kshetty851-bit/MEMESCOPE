import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./api";
import { backtest, config, signal, status, waitSignal } from "./fixtures";
import { BtcRangeLabPage } from "./page";

vi.mock("./api");

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BtcRangeLabPage />
    </QueryClientProvider>,
  );
}

/**
 * The product rule: explanations describe what was observed, and the page
 * never advises. Checked over every piece of text the page renders, not over
 * the strings in the source, so server-rendered prose and client copy are held
 * to the same rule.
 */
const BANNED =
  /\b(buy|buying|sell|selling|hold|holding|should|consider|recommend\w*|advice|advise\w*)\b|opportunity to/i;

beforeEach(() => {
  vi.mocked(api.fetchStatus).mockResolvedValue(status());
  vi.mocked(api.fetchConfig).mockResolvedValue(config());
  vi.mocked(api.runBacktest).mockResolvedValue(backtest());
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("BTC Range Lab page", () => {
  it("shows the paper banner and skeletons while loading", () => {
    vi.mocked(api.fetchStatus).mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByTestId("paper-banner")).toHaveTextContent(
      "Paper trading only — no wallet, no live orders.",
    );
    expect(screen.getByTestId("live-loading")).toBeInTheDocument();
  });

  it("renders the live tab once the status arrives", async () => {
    renderPage();
    expect(await screen.findByTestId("hero")).toBeInTheDocument();
    expect(screen.getByTestId("paper-banner")).toBeInTheDocument();
  });

  it("keeps the banner when the lab is off, with the server's reason", async () => {
    vi.mocked(api.fetchStatus).mockResolvedValue(
      status({
        running: false,
        reason: "The lab is switched off.",
        signal: null,
        book: null,
      }),
    );
    renderPage();
    expect(await screen.findByText("The lab is switched off.")).toBeInTheDocument();
    expect(screen.getByTestId("paper-banner")).toBeInTheDocument();
  });

  it("shows an error state, with a retry, when status fails", async () => {
    vi.mocked(api.fetchStatus).mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByText("Could not load the BTC Range Lab")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-establish link" })).toBeInTheDocument();
  });

  it("switches to the Strategy Lab and keeps its form when returning", async () => {
    renderPage();
    await screen.findByTestId("hero");
    fireEvent.click(screen.getByRole("tab", { name: "Strategy Lab" }));
    const lookback = await screen.findByLabelText("Lookback candles");
    fireEvent.change(lookback, { target: { value: "150" } });

    fireEvent.click(screen.getByRole("tab", { name: "Live (paper)" }));
    expect(await screen.findByTestId("hero")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Strategy Lab" }));
    expect(screen.getByLabelText("Lookback candles")).toHaveValue(150);
  });

  it("shows an error state when the config fails", async () => {
    vi.mocked(api.fetchConfig).mockRejectedValue(new Error("boom"));
    renderPage();
    await screen.findByTestId("hero");
    fireEvent.click(screen.getByRole("tab", { name: "Strategy Lab" }));
    expect(
      await screen.findByText("Could not load the strategy settings"),
    ).toBeInTheDocument();
  });

  it("draws the entry zones from the config's entry_zone", async () => {
    renderPage();
    expect(await screen.findByTestId("long-zone")).toBeInTheDocument();
  });
});

describe("wording", () => {
  it("never recommends: no buy / sell / hold / should / consider in any rendered text", async () => {
    // Live, LONG
    const { unmount } = renderPage();
    await screen.findByTestId("hero");
    expect(document.body.textContent ?? "").not.toMatch(BANNED);

    // Strategy Lab with a result
    fireEvent.click(screen.getByRole("tab", { name: "Strategy Lab" }));
    fireEvent.click(await screen.findByRole("button", { name: "Run backtest" }));
    await screen.findByTestId("backtest-results");
    expect(document.body.textContent ?? "").not.toMatch(BANNED);
    unmount();
    cleanup();

    // Live, WAIT and SHORT
    for (const sig of [waitSignal(), signal({ call: "short" })]) {
      vi.mocked(api.fetchStatus).mockResolvedValue(status({ signal: sig }));
      const view = renderPage();
      await screen.findByTestId("hero");
      expect(document.body.textContent ?? "").not.toMatch(BANNED);
      view.unmount();
    }
  });

  it("labels the call as the paper strategy's, not an instruction", async () => {
    renderPage();
    await screen.findByTestId("hero");
    expect(screen.getByText("Paper strategy call")).toBeInTheDocument();
  });
});
