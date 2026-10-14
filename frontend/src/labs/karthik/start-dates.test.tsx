import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StartDates } from "./page";

describe("If you had started on…", () => {
  it("shows each start's balance, profit and multiple", () => {
    render(<StartDates book="$50k book" capital={300} ticket={50} lines={[
      { start: "2026-10-12T20:00:00Z", days: 0.8, balance_usd: "255.61", pnl_usd: "-44.39", lowest_usd: "242.33", trades: 40, rugs: 2 },
      { start: "2026-10-01T20:00:00Z", days: 12.8, balance_usd: "936.99", pnl_usd: "636.99", lowest_usd: "300.00", trades: 834, rugs: 20 },
    ]} />);
    expect(screen.getByText(/\$50k book · if you had started on… · \$300 at \$50 a trade/)).toBeInTheDocument();
    const t = screen.getByTestId("start-dates");
    expect(t).toHaveTextContent("13 Oct");
    expect(t).toHaveTextContent("-$44.39");
    expect(t).toHaveTextContent("+$636.99");
    expect(t).toHaveTextContent("3.12×");
  });
});
