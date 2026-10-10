import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Card, type CompanyCard } from "./page";

const card: CompanyCard = {
  name: "Acme Industries Ltd", symbol: "ACME", url: "https://www.screener.in/company/ACME/consolidated/",
  consolidated: true, about: "Acme makes widgets.",
  ratios: [{ name: "Market Cap", value: "₹ 1,234 Cr." }, { name: "Stock P/E", value: "21.2" }],
  growth: [{ title: "Compounded Sales Growth", rows: [["5 Years:", "18%"]] }],
  quarters: { Sales: { periods: ["Mar 2026", "Jun 2026"], values: ["100", "120"] }, "Net Profit": { periods: ["Mar 2026", "Jun 2026"], values: ["10", "12"] } },
  yearly: { Sales: null, "Net Profit": null }, borrowings: { periods: ["Mar 2026"], values: ["40"] },
  promoters: { periods: ["Jun 2026"], values: ["50.3%"] }, pros: ["Debt free"], cons: ["Low ROE"],
  fetched_at: "2026-10-10T12:00:00Z",
};

describe("NSE Lab card", () => {
  it("lays out the ratios, results, debt, promoters and the source link", () => {
    render(<Card c={card} />);
    const c = screen.getByTestId("nse-card");
    expect(screen.getByTestId("nse-ratios")).toHaveTextContent("Market Cap₹ 1,234 Cr.");
    expect(c).toHaveTextContent("Compounded Sales Growth");
    expect(c).toHaveTextContent("Net profit1012");
    expect(c).toHaveTextContent("Borrowings40");
    expect(c).toHaveTextContent("Promoters50.3%");
    expect(c).toHaveTextContent("+ Debt free");
    expect(screen.getByRole("link", { name: /screener\.in/ })).toHaveAttribute("href", card.url);
  });
});
