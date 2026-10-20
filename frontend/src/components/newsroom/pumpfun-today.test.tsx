import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PumpfunToday } from "./markets";

const ours = {
  graduations_24h: 1051, graduations_1h: 30, rug_measured_24h: 835, rugged_24h: 550, rug_rate_24h: 65.9,
  recent_drains: [{ mint: "Drain1111111111111111111111111111111pump", symbol: "RUG", name: "Rug Coin", graduated_at: "2026-10-20T09:00:00Z" }],
  survivors: [{ mint: "Surv11111111111111111111111111111111pump", symbol: "Mii", name: null, graduated_at: "2026-10-20T08:00:00Z",
                liquidity_usd: 50869, change_1h_pct: 787.9 }],
  karthik_lab: { started_at: "", judge_at: "", balance_usd: "2034", pnl_usd: "1734.57", pnl_pct: "578", capital_usd: "300", trades: 932, wins: 800, rugs: 14 },
};

describe("Today on pump.fun", () => {
  it("leads with our own numbers, survivors and drains", () => {
    render(<PumpfunToday ours={ours} now={Date.parse("2026-10-20T12:00:00Z")} />);
    const s = screen.getByRole("region", { name: "Today on pump.fun" });
    expect(s).toHaveTextContent("1,051");
    expect(s).toHaveTextContent("65.9%");
    expect(s).toHaveTextContent("285");                 // survived hour one
    expect(s).toHaveTextContent("+$1.73K");             // the lab, paper
    expect(s).toHaveTextContent("Mii");
    expect(s).toHaveTextContent("+788%");
    expect(s).toHaveTextContent("RUG");
    expect(screen.getByRole("link", { name: "chart" })).toHaveAttribute(
      "href", "https://dexscreener.com/solana/Surv11111111111111111111111111111111pump");
  });

  it("shows nothing when our data is unavailable", () => {
    const { container } = render(<PumpfunToday ours={null} now={0} />);
    expect(container).toBeEmptyDOMElement();
  });
});
