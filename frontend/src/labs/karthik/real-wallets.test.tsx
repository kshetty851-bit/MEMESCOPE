import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RealWallets } from "./page";

const wallet = (label: string, today: string, trades: number, all: string) => ({
  label, today_trades: trades, today_won: trades, today_pnl_usd: today, all_trades: 9, all_pnl_usd: all,
});

describe("the real wallets box", () => {
  it("shows each wallet today and all time, and a total", () => {
    render(<RealWallets wallets={[
      wallet("Karthik", "-8.92", 49, "97.45"),
      wallet("USER 1", "-12.52", 49, "41.10"),
      wallet("USER 2", "3.40", 6, "3.40"),
    ]} />);
    const box = screen.getByTestId("real-wallets");
    expect(box).toHaveTextContent("Karthik-$8.92today · 49 trades+$97.45 all time");
    expect(box).toHaveTextContent("USER 2+$3.40today · 6 trades+$3.40 all time");
    expect(box).toHaveTextContent("Total-$18.04today · 104 trades+$141.95 all time");
  });

  it("shows nothing until there is something to show", () => {
    const { container } = render(<RealWallets wallets={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
