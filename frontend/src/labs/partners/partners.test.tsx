import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DayTable, PartnersSummary, StrategyTable, TradeTable, strategiesIn, type PartnersBook } from "./page";

const trade = (id: string, sid: string, closed: string, pnl: string) => ({
  id, mint_address: `M${id}`, symbol: `C${id}`, status: "CLOSED", strategy_id: sid, cost_usd: "10",
  realised_net_pnl_usd: pnl, realised_gross_pnl_usd: pnl, exit_reason: "time", opened_at: closed, closed_at: closed,
});
const d: PartnersBook = {
  partners: {
    started_at: "2026-09-28T11:00:00Z", capital_usd: "100.00", profit_usd: "41.84", balance_usd: "141.84", pct: "41.84",
    trades: 2, wins: 1, open: 0,
    partners: [{ name: "Karthik", put_in_usd: "50.00", profit_usd: "20.92", now_usd: "70.92" },
               { name: "Rafiq", put_in_usd: "50.00", profit_usd: "20.92", now_usd: "70.92" }],
    days: [{ n: 2, from: "2026-09-29T11:00:00Z", to: "2026-09-30T11:00:00Z", running: true, trades: 1, pnl_usd: "-2.00", pct: "-1.89", balance_usd: "103.66" },
           { n: 1, from: "2026-09-28T11:00:00Z", to: "2026-09-29T11:00:00Z", running: false, trades: 1, pnl_usd: "5.66", pct: "5.66", balance_usd: "105.66" }],
  },
  strategies: [{ id: "G-QUIET", name: "GRADUATION-QUIET-5MIN", pool_floor_usd: 75000, trades: 286, wins: 265, pnl_usd: "24.78",
                 first_at: "2026-09-28T11:44:00Z", last_at: "2026-10-03T20:20:00Z" }],
  trades: [trade("2", "G-Q50", "2026-09-29T12:00:00Z", "-2.00"), trade("1", "G-QUIET", "2026-09-28T12:00:00Z", "5.66")],
};

describe("Partners Wallet", () => {
  it("shows the balance and each partner's share", () => {
    render(<PartnersSummary d={d} />);
    const s = screen.getByTestId("partners-summary");
    expect(s).toHaveTextContent("$141.84");
    expect(s).toHaveTextContent("+41.84%");
    expect(s).toHaveTextContent("Rafiq +$20.92");
  });

  it("gives each day its profit, % and the strategy used", () => {
    render(<DayTable d={d} />);
    const t = screen.getByTestId("partners-days");
    expect(t).toHaveTextContent("+5.66%");
    expect(t).toHaveTextContent("-1.89%");
    expect(t).toHaveTextContent("so far");
    expect(strategiesIn(d.partners.days[1]!, d.trades)).toEqual(["G-QUIET"]);
  });

  it("names the strategy on every trade and in plain words", () => {
    render(<><StrategyTable d={d} /><TradeTable d={d} /></>);
    expect(screen.getByTestId("partners-strategies")).toHaveTextContent("Quiet pools $75k+, sold at 5 min");
    const t = screen.getByTestId("partners-trades");
    expect(t).toHaveTextContent("G-Q50");
    expect(t).toHaveTextContent("+56.60%");
  });
});
