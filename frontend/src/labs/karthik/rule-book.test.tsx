import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RuleBook } from "./page";
import type { KarthikBook } from "./types";

describe("Karthik's Lab rule book", () => {
  it("states the rules in plain words, with the book's own numbers", () => {
    const book = {
      pools_usd: [75000, null], skip_pools_usd: [150000, 200000], skip_ai_pools_usd: [50000, 60000], rugged_name_hours: 48, rugged_name_skipped: 19, blocked_names: ["mrbeast"], blocked_name_skipped: 6, skip_spaced_names: true, spaced_name_skipped: 24, skip_unnamed_dubai_hours: [17, 24], unnamed_evening_skipped: 92, skip_no_open_buy: true, no_open_buy_skipped: 22, tickets_by_pool: [[150000, 75], [null, 25]], quiet_stake: [13, 100], quiet_max_txs: 100, max_entry_age_s: 120,
      max_entry_age_since: "2026-09-27T09:00:00Z", ticket_usd: "50", capital_usd: "100",
      hold_minutes: 5, rugs: 1, trades: 196,
    } as unknown as KarthikBook;
    render(<RuleBook data={book} />);
    expect(screen.getByText(/The pool must hold \$75,000 or more\./)).toBeInTheDocument();
    expect(screen.getByText(/No pools between \$150,000 and \$200,000/)).toBeInTheDocument();
    expect(screen.getByText(/named after AI products/)).toBeInTheDocument();
    expect(screen.getByText(/48 hours after one of this book's coins/)).toBeInTheDocument();
    expect(screen.getByText(/Never buys coins named mrbeast/)).toBeInTheDocument();
    expect(screen.getByText(/name has a space/)).toBeInTheDocument();
    expect(screen.getByText(/nobody bought when it opened.*22 skipped/)).toBeInTheDocument();
    expect(screen.getByText(/no name bought from 17:00 to midnight Dubai: .*92 skipped/)).toBeInTheDocument();
    expect(screen.getByText(/quiet small-pool coin \(at most 13 buys/)).toBeInTheDocument();
    expect(screen.getByText(/\$75 a trade in pools under \$150k, \$25 above/)).toBeInTheDocument();
    expect(screen.getByText(/Fewer than 100 trades/)).toBeInTheDocument();
    expect(screen.getByText(/within 2 minutes of the coin graduating/)).toBeInTheDocument();
    expect(screen.getByText(/Exactly 5 minutes after buying/)).toBeInTheDocument();
    expect(screen.getByText(/about 1 in 196 trades/)).toBeInTheDocument();
  });

  it("drops the quiet-coin line once every small-pool coin gets the same $100", () => {
    const book = {
      tickets_by_pool: [[150000, 100], [null, 25]], quiet_stake: [13, 100], capital_usd: "300",
      hold_minutes: 5, rugs: 14, trades: 897,
    } as unknown as KarthikBook;
    render(<RuleBook data={book} />);
    expect(screen.getByText(/\$100 a trade in pools under \$150k, \$25 above/)).toBeInTheDocument();
    expect(screen.queryByText(/quiet small-pool coin/)).not.toBeInTheDocument();
  });

  it("states today's book truthfully: $40k with short names, flat $50, and the Pump Catcher's exit (24 Oct)", () => {
    const base = { pools_usd: [40000, null], short_name_pool: [50000, 5], tickets_by_pool: [[null, 50]],
      capital_usd: "300", hold_minutes: 5, rugs: 30, trades: 829 };
    const { unmount } = render(<RuleBook data={base as unknown as KarthikBook} />);
    expect(screen.getByText(/Below \$50,000 only coins with a name of 5 letters or fewer/)).toBeInTheDocument();
    expect(screen.getByText(/\$50 a trade on every coin, from a \$300\.00 balance\./)).toBeInTheDocument();
    expect(screen.getByText(/do not follow this book's newer rules/)).toBeInTheDocument();
    unmount();
    render(<RuleBook data={{ ...base, capital_usd: "500", pump_catcher: { target_pct: 30, hold_min: 10, check_min: 5, priced: 1, settling: 0 } } as unknown as KarthikBook} />);
    expect(screen.getByText(/up 30% \(at the next price reading\)\. If it is down at 5 minutes it sells then.*otherwise 10 minutes/)).toBeInTheDocument();
    expect(screen.queryByText(/Exactly 5 minutes/)).not.toBeInTheDocument();
    expect(screen.getByText(/No real wallet follows this lab/)).toBeInTheDocument();
  });
  it("explains the revised paper-only entry exception and both exits", () => {
    render(<RuleBook data={{ capital_usd: "500", ticket_usd: "50", rugs: 57, trades: 899,
      hold_minutes: 10, pump_catcher: { model: "independent-v3", target_pct: 100,
        hold_min: 10, priced: 899, settling: 0 } } as KarthikBook} />);
    expect(screen.getByText(/original paper entry is more than about 55 seconds/)).toBeInTheDocument();
    expect(screen.getByText(/Older signals: \+100% target/)).toBeInTheDocument();
    expect(screen.getByText(/20% fall from the observed peak once up at least 50%/)).toBeInTheDocument();
    expect(screen.getByText(/Younger signals: \+30% target/)).toBeInTheDocument();
    expect(screen.getByText(/No real wallet follows this lab/)).toBeInTheDocument();
  });

});
