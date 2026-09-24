import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SiteFooter, WhatRunsHere, dayOf } from "./what-runs-here";

vi.mock("@/lib/api-client", () => ({
  api: {
    get: vi.fn(async () => ({
      started_at: "2026-09-23T12:00:00+00:00",
      judge_at: "2026-10-23T12:00:00+00:00",
      capital_usd: "600",
      balance_usd: "781.01",
      pnl_usd: "181.01",
      pnl_pct: "30.17",
      trades: 64,
      rugs: 0,
    })),
  },
}));

const START = "2026-09-23T12:00:00Z";
const JUDGE = "2026-10-23T12:00:00Z";
const at = (iso: string) => new Date(iso).getTime();

describe("dayOf", () => {
  it("counts the first day as day one and stops at the judge date", () => {
    expect(dayOf(START, JUDGE, at("2026-09-23T12:00:01Z"))).toBe("Day 1 of 30");
    expect(dayOf(START, JUDGE, at("2026-09-24T11:59:59Z"))).toBe("Day 1 of 30");
    expect(dayOf(START, JUDGE, at("2026-09-24T12:00:00Z"))).toBe("Day 2 of 30");
    expect(dayOf(START, JUDGE, at("2026-11-30T00:00:00Z"))).toBe("Day 30 of 30");
    expect(dayOf(START, JUDGE, at("2026-09-01T00:00:00Z"))).toBe("Day 1 of 30");
  });
});

describe("the homepage's lower half", () => {
  it("names the creator", () => {
    render(<SiteFooter />);
    expect(screen.getByText("Karthik Shetty")).toBeInTheDocument();
  });

  it("links the four places that are actually used, with the lab's live figure", async () => {
    render(<WhatRunsHere />);
    const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(links).toEqual(["/graduation-lab", "/karthik-lab", "/real-wallet", "/hq"]);
    expect(await screen.findByText("$781.01")).toBeInTheDocument();
    expect(screen.getByText("+30.17%")).toBeInTheDocument();
    // The retired surfaces are gone from the homepage.
    expect(screen.queryByText(/radar/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/track record/i)).not.toBeInTheDocument();
  });
});
