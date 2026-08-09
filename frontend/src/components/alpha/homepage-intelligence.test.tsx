import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HomepageIntelligence } from "@/components/alpha/homepage-intelligence";
import { AGENTS } from "@/lib/design/agents";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

afterEach(cleanup);

describe("HomepageIntelligence", () => {
  it("renders every repository-defined analyst by its current user-facing name", () => {
    render(<HomepageIntelligence />);

    for (const analyst of Object.values(AGENTS)) {
      expect(screen.getByRole("heading", { name: analyst.name })).toBeInTheDocument();
    }
    expect(screen.queryByText("Snake")).not.toBeInTheDocument();
  });

  it("uses only existing dashboard routes for product calls to action", () => {
    render(<HomepageIntelligence />);

    expect(screen.getByRole("link", { name: "Open Radar" })).toHaveAttribute("href", "/command");
    expect(screen.getByRole("link", { name: /View track record/i })).toHaveAttribute(
      "href",
      "/record",
    );
    expect(screen.getByRole("link", { name: /Open Paper Wallet/i })).toHaveAttribute(
      "href",
      "/wallet",
    );
    expect(screen.getByRole("link", { name: /Strategy intelligence/i })).toHaveAttribute(
      "href",
      "/strategy-intelligence",
    );
  });

  it("distinguishes declared signals from active readouts", () => {
    render(<HomepageIntelligence />);

    expect(screen.getAllByText("Declared signal lane")).toHaveLength(2);
    expect(screen.getAllByText("Active readout")).toHaveLength(5);
  });
});
