import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RugsPreventedCard, RugsPreventedLine, type RugsPreventedData } from "./rugs-prevented";

const data: RugsPreventedData = {
  since: "2026-09-18T19:12:14+00:00", refused: 261, rugs_blocked: 32,
  saved_per_wallet_usd: "655.03", ticket_usd: "50",
  last_rug: { symbol: "GHOST", at: "2026-10-02T13:33:56+00:00" }, quiet_rugs_avoided: 8,
};

// Reduced motion: the count lands at once, so the figures can be read.
vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), addEventListener() {}, removeEventListener() {} }));

describe("rugs prevented", () => {
  it("shows the count, what it kept, the quiet rule's share and the last one", () => {
    render(<RugsPreventedCard data={data} />);
    expect(screen.getByTestId("rugs-prevented-count")).toHaveTextContent("32");
    const box = screen.getByTestId("rugs-prevented");
    expect(box).toHaveTextContent("of 261 coins the rug checks refused since 18 Sep");
    expect(box).toHaveTextContent("$655kept per $50-a-trade wallet");
    expect(box).toHaveTextContent("+8more avoided by the quiet rule");
    expect(box).toHaveTextContent("Last one stopped: GHOST, 2 Oct");
  });

  it("fits on one line on the real wallet page", () => {
    render(<RugsPreventedLine data={{ ...data, since_label: "the timer started" }} />);
    expect(screen.getByTestId("rugs-prevented-line")).toHaveTextContent(
      "32 rugs prevented since the timer started · $655 kept per $50-a-trade wallet");
  });

  it("shows nothing before the count arrives", () => {
    const { container } = render(<RugsPreventedCard data={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
