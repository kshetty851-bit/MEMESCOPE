import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ScannerTable } from "@/components/scanner/scanner-table";
import { withRank, type RankedEntry } from "@/lib/scanner";
import type { RadarEntry } from "@/types/radar";

/**
 * These carry forward the integrity rules the card's own suite asserted, now
 * against the table that replaced it. Every one of them protects a claim the
 * scanner makes about the data rather than a piece of styling.
 */

function base(overrides: Partial<RadarEntry> = {}): RadarEntry {
  return {
    mint_address: "So11111111111111111111111111111111111111112",
    name: "Test Token",
    symbol: "TEST",
    image_url: null,
    category: "early_momentum",
    original_category: "early_momentum",
    opportunity_score: "71.4",
    confidence: "60",
    first_detected_at: "2026-08-01T00:00:00Z",
    first_price: "0.001",
    first_market_cap: "10000",
    first_liquidity: "5000",
    first_opportunity_score: "70",
    current_price: "0.002",
    current_market_cap: "20000",
    current_liquidity: "8000",
    current_multiple: "2.0",
    peak_multiple: "3.5",
    peak_price: "0.0035",
    peak_market_cap: "35000",
    peak_at: "2026-08-05T00:00:00Z",
    days_since_detection: "4",
    is_active: true,
    detection_reason: [],
    achieved_tiers: [],
    liveness: "alive",
    model_version: "v1",
    last_evaluated_at: "2026-08-09T00:00:00Z",
    base_rate: null,
    market: {
      price_usd: "0.002",
      market_cap: "20000",
      liquidity_usd: "8000",
      volume_24h: "12000",
      change_24h_pct: "14.2",
      captured_at: new Date().toISOString(),
      dex_name: "Raydium",
    },
    age_seconds: 7_200,
    risk_score: "62",
    risk_band: "medium",
    risk_reasons: [],
    evidence: "58",
    signal: null,
    why_now: null,
    ...overrides,
  };
}

function renderTable(entries: RadarEntry[] = [base()]) {
  const rows: RankedEntry[] = withRank(entries);
  return render(
    <ScannerTable
      rows={rows}
      sort={{ key: "rank", direction: "asc" }}
      onSortChange={vi.fn()}
      onInspect={vi.fn()}
      activeMint={null}
      isPending={false}
      paperStateOf={() => "not-held"}
      rankDeltaOf={() => 0}
    />,
  );
}

afterEach(cleanup);

describe("ScannerTable — navigation", () => {
  it("routes the token name to MEMESCOPE's own intelligence page", () => {
    renderTable();
    // The Phase 1 finding this fixes: the scanner previously offered no route
    // to /tokens/[mint] at all.
    const link = screen.getByRole("link", { name: /TEST/ });
    expect(link).toHaveAttribute(
      "href",
      "/tokens/So11111111111111111111111111111111111111112",
    );
  });

  it("keeps external destinations out of the row's primary link", () => {
    renderTable();
    const link = screen.getByRole("link", { name: /TEST/ });
    expect(link).not.toHaveAttribute("target");
    expect(link.getAttribute("href")).not.toMatch(/^https?:/);
  });

  it("renders a real anchor rather than a click handler on the row", () => {
    renderTable();
    // A row-as-button would be unreachable by keyboard and unopenable in a new
    // tab. The cell must contain a genuine link.
    expect(screen.getByRole("link", { name: /TEST/ }).tagName).toBe("A");
  });
});

describe("ScannerTable — absent data", () => {
  it("renders a dash for every market figure when nothing was ever observed", () => {
    renderTable([base({ market: null })]);
    const row = screen.getAllByRole("row")[1]!;
    // Never a zero. A price we do not have is not a price of zero.
    expect(within(row).queryByText("$0")).not.toBeInTheDocument();
    expect(within(row).queryByText("$0.00")).not.toBeInTheDocument();
    expect(within(row).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("does not render a 24h change of 0% when the window was never measured", () => {
    renderTable([
      base({ market: { ...base().market!, change_24h_pct: null } }),
    ]);
    const row = screen.getAllByRole("row")[1]!;
    expect(within(row).queryByText(/0\.00%/)).not.toBeInTheDocument();
  });

  it("says risk was not assessed rather than showing a band", () => {
    renderTable([base({ risk_band: null })]);
    expect(
      screen.getByText("Risk was not assessed for this token"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Extreme")).not.toBeInTheDocument();
  });

  it("does not render a score when the entry was never scored", () => {
    renderTable([base({ opportunity_score: "" })]);
    expect(screen.getByText("Not scored")).toBeInTheDocument();
  });
});

describe("ScannerTable — integrity of the numbers", () => {
  it("shows peak beside current, never one without the other", () => {
    renderTable();
    // A call that reached 18x and gave it back is not an 18x call.
    expect(screen.getByRole("columnheader", { name: /Current multiple/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Peak multiple/ })).toBeInTheDocument();
  });

  it("keeps the backend rank visible", () => {
    renderTable([base({ mint_address: "a" }), base({ mint_address: "b" })]);
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]!).getByText("1")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("2")).toBeInTheDocument();
  });

  it("marks every numeric cell as numeric so the mono rule holds", () => {
    const { container } = renderTable();
    expect(container.querySelectorAll("[data-numeric]").length).toBeGreaterThan(3);
  });

  it("exposes the score to assistive tech with its scale", () => {
    renderTable();
    expect(screen.getByText(/MEMESCOPE score 71 of 100/)).toBeInTheDocument();
  });

  it("carries risk as a letter as well as a colour", () => {
    renderTable([base({ risk_band: "extreme" })]);
    expect(screen.getByText("X")).toBeInTheDocument();
    expect(screen.getByText("Extreme")).toBeInTheDocument();
  });
});

describe("ScannerTable — table semantics", () => {
  it("names the table and marks sortable columns", () => {
    renderTable();
    expect(
      screen.getByRole("table", {
        name: "Radar opportunities, ranked by the MEMESCOPE score",
      }),
    ).toBeInTheDocument();

    const rank = screen.getByRole("columnheader", { name: /Radar rank/ });
    expect(rank).toHaveAttribute("aria-sort", "ascending");
  });

  it("renders an empty state rather than an empty table body", () => {
    render(
      <ScannerTable
        rows={[]}
        sort={null}
        onSortChange={vi.fn()}
        onInspect={vi.fn()}
        activeMint={null}
        isPending={false}
        paperStateOf={() => "not-held"}
        rankDeltaOf={() => 0}
        empty={<p>Nothing clears the floor</p>}
      />,
    );
    expect(screen.getByText("Nothing clears the floor")).toBeInTheDocument();
  });

  it("does not render figures while pending", () => {
    render(
      <ScannerTable
        rows={[]}
        sort={null}
        onSortChange={vi.fn()}
        onInspect={vi.fn()}
        activeMint={null}
        isPending
        paperStateOf={() => "not-held"}
        rankDeltaOf={() => 0}
      />,
    );
    // Skeletons must never carry values a reader could mistake for market data.
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
  });
});

describe("ScannerTable — paper wallet state", () => {
  it("reports a held token as a fact, not a control", () => {
    render(
      <ScannerTable
        rows={withRank([base()])}
        sort={null}
        onSortChange={vi.fn()}
        onInspect={vi.fn()}
        activeMint={null}
        isPending={false}
        paperStateOf={() => "open"}
        rankDeltaOf={() => 0}
      />,
    );
    expect(screen.getByText("Held")).toBeInTheDocument();
    // The strategy enters on its own published rule; there is nothing to click.
    expect(screen.queryByRole("button", { name: /buy/i })).not.toBeInTheDocument();
  });
});
