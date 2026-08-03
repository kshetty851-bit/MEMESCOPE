import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OpportunityCard } from "@/components/opportunity/opportunity-card";
import type { Opportunity, OpportunitySignal } from "@/types/opportunity";

function signal(overrides: Partial<OpportunitySignal> = {}): OpportunitySignal {
  return {
    signal_type: "fresh_graduation",
    provider: "fresh_graduation",
    status: "active",
    severity: "major",
    strength: "100.00",
    confidence: "55.00",
    confirmations: 2,
    observations: 6,
    detected_at: "2026-08-02T12:00:00Z",
    last_confirmed_at: "2026-08-02T12:05:00Z",
    expires_at: "2026-08-04T12:00:00Z",
    expires_in_seconds: 172_800,
    reason_codes: ["graduated_from_bonding_curve"],
    evidence: [],
    explanation: {
      headline: "Freshly graduated",
      trigger: "This token has left its bonding curve and now trades on an open pool.",
      boundary: "The venue reporting this token's market changed.",
      delta: ["Previous venue: pumpfun"],
      corroboration: [],
      limits: ["Holder distribution is not collected, so concentration was not checked."],
    },
    ...overrides,
  };
}

function opportunity(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    mint_address: "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump",
    name: "Inward Unrest",
    symbol: "NWRDN",
    generation: 1,
    status: "active",
    stage: "fresh_graduation",
    priority: "60.00",
    priority_band: "high",
    confidence: "55.00",
    detected_at: new Date(Date.now() - 3_600_000).toISOString(),
    last_confirmed_at: new Date(Date.now() - 300_000).toISOString(),
    confirmed_age_seconds: 300,
    signals: [signal()],
    ...overrides,
  };
}

afterEach(cleanup);

describe("OpportunityCard", () => {
  it("shows every field the board promises", () => {
    render(<OpportunityCard opportunity={opportunity()} onOpen={vi.fn()} />);

    expect(screen.getByText("NWRDN")).toBeInTheDocument();
    // Stage and signal are orthogonal axes that happen to share a label for
    // the one provider shipping today — the stage says where the token is, the
    // badge says what fired. They diverge as soon as a second provider exists.
    expect(screen.getAllByText("Fresh graduation")).toHaveLength(2);
    expect(screen.getByLabelText("Active signals")).toHaveTextContent(
      "Fresh graduation",
    );
    expect(screen.getByText("Confidence")).toBeInTheDocument();
    expect(screen.getByText("Priority")).toBeInTheDocument();
    expect(screen.getByText("Detected")).toBeInTheDocument();
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
    expect(screen.getByText("Expires in")).toBeInTheDocument();
    expect(screen.getByText("Why now?")).toBeInTheDocument();
  });

  it("renders the backend's explanation verbatim", () => {
    // The client never composes these sentences. A second opinion about the
    // same token, written here, can disagree with the engine that produced it.
    render(<OpportunityCard opportunity={opportunity()} onOpen={vi.fn()} />);

    expect(
      screen.getByText(
        "This token has left its bonding curve and now trades on an open pool.",
      ),
    ).toBeInTheDocument();
  });

  it("shows what could not be checked", () => {
    // The limits clause is the difference between honest coverage and a card
    // that quietly looks complete.
    render(<OpportunityCard opportunity={opportunity()} onOpen={vi.fn()} />);

    expect(screen.getByText(/Holder distribution is not collected/)).toBeInTheDocument();
  });

  it("renders several concurrent signals as one card", () => {
    render(
      <OpportunityCard
        opportunity={opportunity({
          signals: [signal(), signal({ signal_type: "pre_breakout", provider: "technical" })],
        })}
        onOpen={vi.fn()}
      />,
    );

    const badges = screen.getByLabelText("Active signals");
    expect(badges).toHaveTextContent("Fresh graduation");
    expect(badges).toHaveTextContent("Pre-breakout");
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("falls back to a shortened mint when the token has no identity", () => {
    render(
      <OpportunityCard
        opportunity={opportunity({ name: null, symbol: null })}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText("HHbR…pump")).toBeInTheDocument();
  });

  it("says so when every signal has lapsed rather than showing nothing", () => {
    render(
      <OpportunityCard opportunity={opportunity({ signals: [] })} onOpen={vi.fn()} />,
    );

    expect(screen.getByText("No live signals")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument(); // expires in
  });

  it("opens the drawer when activated", () => {
    const onOpen = vi.fn();
    const item = opportunity();
    render(<OpportunityCard opportunity={item} onOpen={onOpen} />);

    fireEvent.click(screen.getByRole("button"));

    expect(onOpen).toHaveBeenCalledWith(item);
  });

  it("exposes the card as a single focusable control", () => {
    // The whole card opens the drawer, so it is one button rather than a div
    // with a click handler — that is what makes it tabbable and Enter-able
    // without re-implementing keyboard handling.
    render(<OpportunityCard opportunity={opportunity()} onOpen={vi.fn()} />);

    const control = screen.getByRole("button");
    expect(control).toHaveAttribute("aria-haspopup", "dialog");
    expect(control.tagName).toBe("BUTTON");
  });
});
