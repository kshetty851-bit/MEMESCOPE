import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RealWallets } from "./page";

const wallet = (label: string, all: string, value: string | null) => ({
  label, today_trades: 0, today_won: 0, today_pnl_usd: "0", all_trades: 9, all_pnl_usd: all,
  value_usd: value,
});

describe("the real wallets box", () => {
  it("shows each wallet's value and profit, the totals, and Karthik's share", () => {
    render(<RealWallets totalValue="458.83" wallets={[
      wallet("Karthik", "103.94", "209.30"), wallet("USER 1", "45.00", "148.67"),
      wallet("USER 2", "-3.37", "100.86"),
    ]} />);
    const box = screen.getByTestId("real-wallets");
    expect(box).toHaveTextContent(
      "Karthik$209.30+$103.94Paper 1$148.67+$45.00Paper 2$100.86-$3.37");
    expect(box).toHaveTextContent("Total$458.83+$145.57+48.52% on $300.00");
    // Half of main's profit (Rafiq owns the other half) plus both paper wallets.
    expect(box).toHaveTextContent("Your share+$93.60+37.44% on $250.00");
    expect(box).not.toHaveTextContent("USER");
  });

  it("shows a dash where a value could not be read", () => {
    render(<RealWallets totalValue={null} wallets={[wallet("Karthik", "1", null)]} />);
    expect(screen.getByTestId("real-wallets")).toHaveTextContent("Karthik—+$1.00Total—+$1.00");
  });

  it("shows nothing until there is something to show", () => {
    const { container } = render(<RealWallets wallets={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
