import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { day30, GraduationsSeen, MoneyIn, PoolTrades } from "./page";

describe("graduations seen", () => {
  it("shows every graduation since the start, bought or not", () => {
    render(<GraduationsSeen count={6843} />);
    expect(screen.getByTestId("graduations-seen")).toHaveTextContent("6,843");
    expect(screen.getByText(/graduations seen/i)).toHaveTextContent("taken or not");
  });

  it("stays out of the way against an older API that does not send it", () => {
    const { container } = render(<GraduationsSeen count={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});

const trade = (pool: string | null, pnl: string) => ({
  symbol: "X", opened_at: "2026-09-27T10:00:00Z", closed_at: null, pct: "1", pnl_usd: pnl, pool_usd: pool,
});

describe("trades by pool floor", () => {
  it("counts every trade at or above each pool floor, with what they made", () => {
    render(<PoolTrades trades={[trade("80000", "1.50"), trade("99999", "-0.50"), trade("620000", "2")]} />);
    const box = screen.getByTestId("pool-trades");
    expect(box).toHaveTextContent("$75k+3+$3.00");           // all three
    expect(box).toHaveTextContent("$100k+1+$2.00");          // only the $620k pool
    expect(box).toHaveTextContent("$200k+1+$2.00");
    expect(box).not.toHaveTextContent("$300k+");        // floors stop at $200k (2026-09-30)
    expect(box).not.toHaveTextContent("$500k+");
  });

  it("shows nothing before the first trade", () => {
    const { container } = render(<PoolTrades trades={[trade(null, "1")]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("rugs and money in", () => {
  it("says how many graduations rugged in their first hour", () => {
    render(<GraduationsSeen count={4200} rugs={{ rugged: 2614, measured: 4046, window_minutes: 60 }} />);
    expect(screen.getByTestId("graduations-rugged")).toHaveTextContent(
      "2,614 rugged (65%) · fell 80%+ in their first hour, of 4,046 checked");
  });

  it("splits the money in our coins between owners and other traders", () => {
    render(<MoneyIn flows={{
      trades: 226, measured: 120, insider_buy_usd: "1500.4", insider_sell_usd: "90000",
      other_buy_usd: "412345.6", other_sell_usd: "300000", insider_sold_trades: 5, other_buyers: 5400,
    }} />);
    const box = screen.getByTestId("money-in");
    expect(box).toHaveTextContent("Owners & related wallets$1,500$90,000");
    expect(box).toHaveTextContent("Other traders$412,346$300,000");
    expect(box).toHaveTextContent("Owners sold in 5 of 120 trades");
    expect(box).toHaveTextContent("120 of 226 trades read so far");
  });

  it("says in how many trades the owners bought, when the API sends it", () => {
    render(<MoneyIn flows={{
      trades: 230, measured: 230, insider_buy_usd: "1", insider_sell_usd: "0", other_buy_usd: "1",
      other_sell_usd: "0", insider_sold_trades: 4, insider_bought_trades: 76, other_buyers: 1,
    }} />);
    expect(screen.getByTestId("money-in")).toHaveTextContent("Owners bought in 76 and sold in 4 of 230 trades");
  });

  it("stays hidden until a trade has been read", () => {
    const { container } = render(<MoneyIn flows={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("day 30", () => {
  const day = (n: number, pnl: string, balance: string, running = false) => ({
    n, from: "", to: "", running, trades: 50, pnl_usd: pnl, pct: "1", balance_usd: balance,
  });

  it("adds the average finished day for every day left, and shows the worst pace", () => {
    const now = Date.parse("2026-09-28T12:00:00Z");
    const judge = "2026-10-23T12:00:00Z";                      // 25 days left
    const guess = day30([day(6, "5", "400", true), day(5, "60", "395"), day(4, "40", "335"),
                         day(3, "20", "295")], judge, now)!;
    expect(guess.avg).toBe(40);
    expect(guess.expected).toBe(400 + 40 * 25);
    expect(guess.worstPace).toBe(400 + 20 * 25);
    expect(guess.basedOn).toBe(3);
  });

  it("guesses nothing before the first full day", () => {
    expect(day30([day(1, "5", "105", true)], "2026-10-23T12:00:00Z")).toBeNull();
  });
});
