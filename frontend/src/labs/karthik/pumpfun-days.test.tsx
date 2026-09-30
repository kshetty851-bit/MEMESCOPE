import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PumpfunMoneyTable } from "./page";

describe("money into pump.fun, day by day", () => {
  it("shows each day's launches, graduations and money, newest first", () => {
    render(
      <PumpfunMoneyTable
        graduationSol={85}
        days={[
          { day: "2026-09-30", running: true, launches: 24916, graduations: 739,
            into_curves_usd: "7487688", pools_usd: "45733826", pools_75k: 44 },
          { day: "2026-09-29", running: false, launches: 36717, graduations: 1048,
            into_curves_usd: "10565641", pools_usd: "59638802", pools_75k: 89 },
        ]}
      />,
    );
    const rows = screen.getByTestId("pumpfun-days").querySelectorAll("tbody tr");
    expect(rows[0]).toHaveTextContent("30 Sep· so far24,916739$7.5M$45.7M44");
    expect(rows[1]).toHaveTextContent("29 Sep36,7171,048$10.6M$59.6M89");
  });

  it("shows nothing before there is a day", () => {
    const { container } = render(<PumpfunMoneyTable graduationSol={85} days={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
