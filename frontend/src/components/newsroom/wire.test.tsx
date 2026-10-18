import { fireEvent, render, screen, cleanup, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Newswire, SinceVisit } from "./wire";
import type { Coin, Story } from "./types";

vi.mock("./hooks", () => ({ useRevealOnce: () => ({ current: null }) }));
afterEach(cleanup);
const now = Date.parse("2026-10-18T16:00:00Z");
const story: Story = {
  id: "a",
  title: "Solana bridge coverage",
  summary: "A publisher reports a bridge pause.",
  url: "https://example.com/story",
  source: "Example",
  image: null,
  first_at: "2026-10-17T12:00:00Z",
  last_at: "2026-10-18T15:00:00Z",
  sources: 1,
  publishers: ["Example"],
  topics: ["solana", "security"],
  regions: ["US"],
  kind: "report",
  timeline: [],
};
const bitcoin: Story = {
  ...story,
  id: "b",
  title: "Bitcoin network update",
  topics: ["bitcoin"],
};
const coin: Coin = {
  id: "solana",
  symbol: "SOL",
  name: "Solana",
  image: null,
  price: 100,
  mcap: null,
  volume: null,
  ch1h: null,
  ch24h: null,
  ch7d: null,
  spark: [],
};
const watch = { ids: ["solana"], has: (id: string) => id === "solana", toggle: vi.fn() };
function wire() {
  return render(
    <Newswire
      stories={[story, bitcoin]}
      pending={0}
      onApply={vi.fn()}
      now={now}
      lastVisit={null}
      coins={[coin]}
      watch={watch}
    />,
  );
}

describe("newsroom reading", () => {
  it("counts an update to an older security story since the visit", () => {
    render(
      <SinceVisit
        last={{ at: "2026-10-18T10:00:00Z", btc: null }}
        stories={[story]}
        btc={null}
        now={now}
      />,
    );
    expect(screen.getByText(/security story new or updated/).textContent).toBe(
      "1 security story new or updated",
    );
    expect(screen.getByText(/new stories/).textContent).toBe("0 new stories");
  });
  it("opens a publisher brief for a single-source report", () => {
    wire();
    expect(screen.queryByText(story.summary)).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Story brief & sources" })[0]!);
    expect(screen.getByText(story.summary)).toBeVisible();
    expect(screen.getByRole("link", { name: /Read at Example/ })).toHaveAttribute(
      "href",
      story.url,
    );
    fireEvent.click(screen.getByRole("button", { name: "Close brief" }));
    expect(screen.queryByText(story.summary)).not.toBeInTheDocument();
  });
  it("filters the wire to watched assets", () => {
    wire();
    fireEvent.click(screen.getByRole("button", { name: "My watchlist" }));
    expect(screen.queryByRole("heading", { name: bitcoin.title })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: story.title })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("1 matching stories");
  });
  it("combines quick views with search", () => {
    wire();
    fireEvent.click(
      within(screen.getByRole("group", { name: "News view" })).getByRole("button", {
        name: "Solana",
      }),
    );
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Bitcoin" } });
    expect(screen.getByText("Nothing matches that filter right now.")).toBeVisible();
  });
});
