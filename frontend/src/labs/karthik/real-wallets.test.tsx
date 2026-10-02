import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RealWallets } from "./page";

const wallet = (label: string, all: string) => ({
  label, today_trades: 0, today_won: 0, today_pnl_usd: "0", all_trades: 9, all_pnl_usd: all,
});

describe("the real wallets box", () => {
  it("lists each wallet's profit since it began, then a total with its % of the $250 put in", () => {
    render(<RealWallets totalValue="331.87" wallets={[
      wallet("Karthik", "40.32"), wallet("USER 1", "43.78"), wallet("USER 2", "-4.56"),
    ]} />);
    const box = screen.getByTestId("real-wallets");
    expect(box).toHaveTextContent(
      "Karthik+$40.32Paper 1+$43.78Paper 2-$4.56Total+$79.54 (+31.82% on $250.00)Total value$331.87");
    expect(box).not.toHaveTextContent("today");
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
