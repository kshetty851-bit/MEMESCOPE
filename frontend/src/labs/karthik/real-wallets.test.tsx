import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RealWallets } from "./page";

const wallet = (label: string, all: string) => ({
  label, today_trades: 0, today_won: 0, today_pnl_usd: "0", all_trades: 9, all_pnl_usd: all,
});

describe("the real wallets box", () => {
  it("lists each wallet, the total on $300, Karthik's share on his $250, and the value", () => {
    render(<RealWallets totalValue="459.77" wallets={[
      wallet("Karthik", "103.94"), wallet("USER 1", "45.00"), wallet("USER 2", "-3.37"),
    ]} />);
    const box = screen.getByTestId("real-wallets");
    expect(box).toHaveTextContent("Karthik+$103.94Paper 1+$45.00Paper 2-$3.37");
    expect(box).toHaveTextContent("Total+$145.57 (+48.52% on $300.00)");
    // Half of main's profit (Rafiq owns the other half) plus both paper wallets.
    expect(box).toHaveTextContent("Your share+$93.60 (+37.44% on $250.00)");
    expect(box).toHaveTextContent("Total value$459.77");
    expect(box).not.toHaveTextContent("USER");
  });

  it("leaves the total value out when it could not be read", () => {
    render(<RealWallets totalValue={null} wallets={[wallet("Karthik", "1")]} />);
    expect(screen.getByTestId("real-wallets")).not.toHaveTextContent("Total value");
  });

  it("shows nothing until there is something to show", () => {
    const { container } = render(<RealWallets wallets={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
