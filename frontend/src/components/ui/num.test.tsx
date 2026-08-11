import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Delta } from "@/components/ui/delta";
import { Absent, Num } from "@/components/ui/num";
import { RiskChip } from "@/components/ui/risk-chip";
import { ScoreBadge } from "@/components/ui/score-badge";

/**
 * These assert the product rules, not the styling.
 *
 * Every one of them protects a claim the interface makes about the data: that
 * a dash means "not measured", that a risk band is never invented, and that a
 * direction is never carried by colour alone.
 */

describe("Num", () => {
  it("renders a dash for an absent figure, never a zero", () => {
    for (const value of [null, undefined, ""]) {
      const { unmount } = render(<Num value={value} />);
      expect(screen.getByText("—")).toBeInTheDocument();
      expect(screen.queryByText("0")).not.toBeInTheDocument();
      unmount();
    }
  });

  it("announces absence in words for assistive tech", () => {
    render(<Num value={null} absentLabel="no price recorded" />);
    expect(screen.getByText("no price recorded")).toBeInTheDocument();
  });

  it("renders a real zero as zero", () => {
    render(<Num value="0" format={(v) => `$${Number(v).toFixed(2)}`} />);
    expect(screen.getByText("$0.00")).toBeInTheDocument();
  });

  it("passes the unparsed value to the formatter so precision survives", () => {
    const seen: (string | number)[] = [];
    render(
      <Num
        value="0.000000000000123456"
        format={(value) => {
          seen.push(value);
          return "formatted";
        }}
      />,
    );
    expect(seen).toEqual(["0.000000000000123456"]);
  });

  it("falls back to a dash when a present value cannot be a figure", () => {
    render(<Num value="banana" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("marks every figure as numeric so the mono rule cannot be skipped", () => {
    const { container } = render(<Num value="42" />);
    expect(container.querySelector("[data-numeric]")).not.toBeNull();
  });

  it("derives tone from the sign when asked", () => {
    const { container: up } = render(<Num value="5" signed />);
    expect(up.firstElementChild?.className).toContain("text-up");

    const { container: down } = render(<Num value="-5" signed />);
    expect(down.firstElementChild?.className).toContain("text-down");

    // 0.3x is a loss when the pivot is 1, and a gain when it is 0.
    const { container: multiple } = render(<Num value="0.3" signed pivot={1} />);
    expect(multiple.firstElementChild?.className).toContain("text-down");
  });
});

describe("Absent", () => {
  it("gives absence exactly one appearance", () => {
    render(<Absent />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("not available")).toBeInTheDocument();
  });
});

describe("Delta", () => {
  it("carries direction as a glyph as well as a colour", () => {
    render(<Delta value="12.5" />);
    expect(screen.getByText("▲")).toBeInTheDocument();
    expect(screen.getByText(/up/)).toBeInTheDocument();
  });

  it("renders a dash for an unmeasured change, not 0%", () => {
    render(<Delta value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/0\.00%/)).not.toBeInTheDocument();
  });

  it("treats a multiple below 1 as a loss", () => {
    render(<Delta value="0.3" pivot={1} format={(v) => `${v.toFixed(2)}x`} />);
    expect(screen.getByText("▼")).toBeInTheDocument();
  });
});

describe("ScoreBadge", () => {
  it("prints the band word beside the numeral", () => {
    render(<ScoreBadge score="71" grade="strong" />);
    expect(screen.getByText("71")).toBeInTheDocument();
    expect(screen.getByText("Strong")).toBeInTheDocument();
  });

  it("says 'Not scored' rather than showing a zero", () => {
    render(<ScoreBadge score={null} grade={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
    // Exactly once: the dash is aria-hidden so the state is announced as one
    // fact rather than "dash, not scored, not scored".
    expect(screen.getAllByText("Not scored")).toHaveLength(1);
  });

  it("exposes the score as a meter in the dial variant", () => {
    render(<ScoreBadge score="88" grade="high_conviction" variant="dial" />);
    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuenow", "88");
    expect(meter).toHaveAttribute("aria-valuetext", "88 of 100, High conviction");
  });
});

describe("RiskChip", () => {
  it("prints a letter alongside the colour", () => {
    render(<RiskChip band="extreme" />);
    expect(screen.getByText("X")).toBeInTheDocument();
    expect(screen.getByText("Extreme")).toBeInTheDocument();
  });

  it("never renders an unassessed risk as a band", () => {
    render(<RiskChip band={null} />);
    expect(screen.getByText("Risk —")).toBeInTheDocument();
    expect(
      screen.getByText("Risk was not assessed for this token"),
    ).toBeInTheDocument();
  });

  it("exposes the backend's reasons as the accessible description", () => {
    render(<RiskChip band="high" reasons={["Liquidity is thin", "Creator holds 40%"]} />);
    expect(
      screen.getByText("High risk. Liquidity is thin. Creator holds 40%"),
    ).toBeInTheDocument();
  });
});
