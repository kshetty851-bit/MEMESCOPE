import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RuleBook } from "./page";
import type { KarthikBook } from "./types";

describe("Karthik's Lab rule book", () => {
  it("states the rules in plain words, with the book's own numbers", () => {
    const book = {
      pools_usd: [75000, null], quiet_max_txs: 100, max_entry_age_s: 120,
      max_entry_age_since: "2026-09-27T09:00:00Z", ticket_usd: "50", capital_usd: "100",
      hold_minutes: 5, rugs: 1, trades: 196,
    } as unknown as KarthikBook;
    render(<RuleBook data={book} />);
    expect(screen.getByText(/The pool must hold \$75,000 or more\./)).toBeInTheDocument();
    expect(screen.getByText(/Fewer than 100 trades/)).toBeInTheDocument();
    expect(screen.getByText(/within 2 minutes of the coin graduating/)).toBeInTheDocument();
    expect(screen.getByText(/\$50\.00 per trade, from a \$100\.00 balance\./)).toBeInTheDocument();
    expect(screen.getByText(/Exactly 5 minutes after buying/)).toBeInTheDocument();
    expect(screen.getByText(/about 1 in 196 trades/)).toBeInTheDocument();
  });
});
