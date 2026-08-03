import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OpportunityDrawer } from "@/components/opportunity/opportunity-drawer";
import type { Opportunity, OpportunitySignal } from "@/types/opportunity";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

function signal(overrides: Partial<OpportunitySignal> = {}): OpportunitySignal {
  return {
    signal_type: "fresh_graduation",
    provider: "fresh_graduation",
    status: "active",
    severity: "major",
    strength: "100.00",
    confidence: "55.00",
    confirmations: 2,
    observations: 12,
    detected_at: "2026-08-02T12:00:00Z",
    last_confirmed_at: "2026-08-02T12:05:00Z",
    expires_at: "2026-08-04T12:00:00Z",
    expires_in_seconds: 172_800,
    reason_codes: ["graduated_from_bonding_curve"],
    evidence: [{ label: "Previous venue", value: "pumpfun", detail: "Bonding curve" }],
    explanation: {
      headline: "Freshly graduated",
      trigger: "This token has left its bonding curve and now trades on an open pool.",
      boundary: "The venue reporting this token's market changed between observations.",
      delta: ["Previous venue: pumpfun (Bonding curve)"],
      corroboration: [],
      limits: ["Liquidity could not be verified before graduation."],
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
    status: "pending_confirmation",
    stage: "fresh_graduation",
    priority: "26.91",
    priority_band: "medium",
    confidence: "31.65",
    detected_at: "2026-08-02T12:00:00Z",
    last_confirmed_at: "2026-08-02T12:05:00Z",
    confirmed_age_seconds: 300,
    signals: [signal()],
    ...overrides,
  };
}

afterEach(cleanup);

describe("OpportunityDrawer", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <OpportunityDrawer opportunity={null} onClose={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("is an accessible modal dialog", () => {
    render(<OpportunityDrawer opportunity={opportunity()} onClose={vi.fn()} />);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName(/NWRDN/);
  });

  it("shows the full mint, not just the shortened identity", () => {
    render(<OpportunityDrawer opportunity={opportunity()} onClose={vi.fn()} />);

    expect(
      screen.getByText("HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"),
    ).toBeInTheDocument();
  });

  it("shows strength alongside confidence", () => {
    // Strength is the provider's claim about the transition; confidence is what
    // the engine derived from it. Showing both is what stops a confident-looking
    // card hiding a single unconfirmed observation.
    render(<OpportunityDrawer opportunity={opportunity()} onClose={vi.fn()} />);

    expect(screen.getByText("Strength")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("Confirmations")).toBeInTheDocument();
  });

  it("renders the full explanation including what was not checked", () => {
    render(<OpportunityDrawer opportunity={opportunity()} onClose={vi.fn()} />);

    expect(screen.getByText(/left its bonding curve/)).toBeInTheDocument();
    expect(screen.getByText(/venue reporting this token/)).toBeInTheDocument();
    expect(screen.getByText(/Previous venue: pumpfun/)).toBeInTheDocument();
    expect(screen.getByText(/Liquidity could not be verified/)).toBeInTheDocument();
  });

  it("does not badge a first-generation opportunity", () => {
    // Generation only carries meaning past the first: it says this token has
    // been called before and the earlier call is still on the record.
    render(<OpportunityDrawer opportunity={opportunity()} onClose={vi.fn()} />);
    expect(screen.queryByText(/Generation/)).not.toBeInTheDocument();
  });

  it("badges a reopened opportunity", () => {
    render(
      <OpportunityDrawer opportunity={opportunity({ generation: 3 })} onClose={vi.fn()} />,
    );
    expect(screen.getByText("Generation 3")).toBeInTheDocument();
  });

  it("says so when every signal has lapsed", () => {
    render(
      <OpportunityDrawer opportunity={opportunity({ signals: [] })} onClose={vi.fn()} />,
    );
    expect(screen.getByText(/stays on the record/)).toBeInTheDocument();
  });

  it("closes on the close control", () => {
    const onClose = vi.fn();
    render(<OpportunityDrawer opportunity={opportunity()} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalled();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<OpportunityDrawer opportunity={opportunity()} onClose={onClose} />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalled();
  });

  it("stops listening for Escape once closed", () => {
    // Otherwise a stale listener fires against a drawer that is already gone.
    const onClose = vi.fn();
    const { rerender } = render(
      <OpportunityDrawer opportunity={opportunity()} onClose={onClose} />,
    );
    rerender(<OpportunityDrawer opportunity={null} onClose={onClose} />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).not.toHaveBeenCalled();
  });
});
