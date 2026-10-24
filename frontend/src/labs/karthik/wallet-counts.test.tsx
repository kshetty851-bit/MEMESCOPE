import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WalletCountsBox } from "./page";

describe("WalletCountsBox", () => {
  it("shows a row per wallet count, each wallet's profit, and day 30", () => {
    render(<WalletCountsBox w={{ start_usd: 300, days_elapsed: 24, days_target: 30, tickets_by_pool: [[null, 50]], counts: [
      { wallets: 1, put_in_usd: 300, per_wallet: [{ pnl_usd: 1445, trades: 829, rugs: 30 }], pnl_usd: 1445, balance_usd: 1745, return_pct: 481.7, day30_pnl_usd: 1806.25, day30_balance_usd: 2106.25 },
      { wallets: 2, put_in_usd: 600, per_wallet: [{ pnl_usd: 1445, trades: 829, rugs: 30 }, { pnl_usd: 1262, trades: 829, rugs: 30 }], pnl_usd: 2707, balance_usd: 3307, return_pct: 451.2, day30_pnl_usd: 3383.75, day30_balance_usd: 3983.75 },
    ] }} />);
    expect(screen.getByTestId("wallets-2")).toHaveTextContent("+$2,707");
    expect(screen.getByTestId("wallets-2")).toHaveTextContent("+$3,384");
    expect(screen.getByTestId("wallets-2")).toHaveTextContent("+$1,262");
    expect(screen.getByTestId("wallet-counts")).toHaveTextContent("with 2 wallets");
  });
});
