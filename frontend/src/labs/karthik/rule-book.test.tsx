import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RuleBook } from "./page";
import type { KarthikBook } from "./types";

describe("Karthik's Lab rule book", () => {
  it("states the rules in plain words, with the book's own numbers", () => {
    const book = {
      pools_usd: [75000, null], skip_pools_usd: [150000, 200000], skip_ai_pools_usd: [50000, 60000], rugged_name_hours: 48, rugged_name_skipped: 19, blocked_names: ["mrbeast"], blocked_name_skipped: 6, skip_spaced_names: true, spaced_name_skipped: 24, skip_unnamed_dubai_hours: [17, 24], unnamed_evening_skipped: 92, tickets_by_pool: [[150000, 75], [null, 25]], quiet_stake: [13, 100], quiet_max_txs: 100, max_entry_age_s: 120,
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
    expect(screen.getByText(/no name bought from 17:00 to midnight Dubai: .*92 skipped/)).toBeInTheDocument();
    expect(screen.getByText(/quiet small-pool coin \(at most 13 buys/)).toBeInTheDocument();
    expect(screen.getByText(/\$75 a trade in pools under \$150k, \$25 above/)).toBeInTheDocument();
    expect(screen.getByText(/Fewer than 100 trades/)).toBeInTheDocument();
    expect(screen.getByText(/within 2 minutes of the coin graduating/)).toBeInTheDocument();
    expect(screen.getByText(/Exactly 5 minutes after buying/)).toBeInTheDocument();
    expect(screen.getByText(/about 1 in 196 trades/)).toBeInTheDocument();
  });
});
