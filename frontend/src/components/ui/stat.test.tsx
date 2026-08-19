import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Num } from "@/components/ui/num";
import { Stat } from "@/components/ui/stat";

/**
 * Regression cover for the Phase 7 paper-wallet blackout.
 *
 * `/wallet` formats its figures before
 * rendering — `usd()` returns "$1,234.56", `pct()` returns "12.5%". When their
 * local `Stat` was pointed at the shared one, it passed that formatted string
 * as BOTH `value` and `display`. `Num` parses `value` to decide whether a
 * figure exists, `Number("$1,234.56")` is `NaN`, and every number on the paper
 * wallet rendered as a dash.
 *
 * The dash rule was right; the input was a lie. These pin the display-only
 * contract so a pre-formatted caller cannot silently blank a screen again.
 */

afterEach(cleanup);

describe("Num — display-only callers", () => {
  it("renders a pre-formatted string with no raw value", () => {
    render(<Num display="$1,234.56" />);
    expect(screen.getByText("$1,234.56")).toBeInTheDocument();
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  it("still dashes when a display-only caller has nothing", () => {
    render(<Num display={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("keeps using the raw value for presence when one is given", () => {
    // A caller that supplies both is asserting the raw figure is the truth,
    // so an absent raw value must still win over a stale display string.
    render(<Num value={null} display="$99.00" />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("$99.00")).not.toBeInTheDocument();
  });

  it("does not treat an unparseable raw value as present", () => {
    render(<Num value="banana" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("Stat — the paper wallet's call shape", () => {
  it("shows a formatted currency figure", () => {
    render(<Stat label="Equity" display="$10,482.31" />);
    expect(screen.getByText("$10,482.31")).toBeInTheDocument();
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  it("shows a formatted percentage", () => {
    render(<Stat label="Return" display="-4.82%" tone="down" />);
    expect(screen.getByText("-4.82%")).toBeInTheDocument();
  });

  it("shows a formatted duration", () => {
    render(<Stat label="Average hold" display="6.4h" />);
    expect(screen.getByText("6.4h")).toBeInTheDocument();
  });

  it("dashes an absent figure rather than inventing zero", () => {
    render(<Stat label="Largest winner" display={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("renders raw values with a formatter as before", () => {
    render(<Stat label="Score" value="71.4" display="71" />);
    expect(screen.getByText("71")).toBeInTheDocument();
  });

  it("keeps children taking precedence over the figure", () => {
    render(
      <Stat label="Change">
        <span>custom</span>
      </Stat>,
    );
    expect(screen.getByText("custom")).toBeInTheDocument();
  });
});
