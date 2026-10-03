import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type * as ApiClientModule from "@/lib/api-client";
import { api } from "@/lib/api-client";
import { NAV_GROUPS } from "@/lib/design/nav";

import { DataHealthPanel } from "./data-health-panel";
import { MeasuredValue } from "./display";
import { DETAIL, MEMES, MEME_QUALITY, OVERVIEW, SOURCES, m } from "./fixtures";
import { LifecycleOverlayChart } from "./overlay-chart";
import { LifecycleLabPage, LifecycleMemeDetailPage } from "./page";
import { formatNumber } from "./display";

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClientModule>()),
  api: { get: vi.fn(), post: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ slug: "frogceo" }),
}));

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

afterEach(() => {
  cleanup();
  vi.mocked(api.get).mockReset();
});

function routeApi() {
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === "/lifecycle-lab/overview") return OVERVIEW;
    if (path === "/lifecycle-lab/health") return { generated_at: "x", sources: SOURCES };
    if (path === "/lifecycle-lab/memes") return MEMES;
    if (path === "/lifecycle-lab/memes/frogceo") return DETAIL;
    if (path === "/lifecycle-lab/memes/frogceo/quality") return MEME_QUALITY;
    throw new Error(`unexpected ${path}`);
  });
}

const FORBIDDEN = /\b(buy|sell|hold|consider)\b/i;

describe("unavailable is never zero", () => {
  it("renders a null Measured as the word 'unavailable' with its reason, not 0", () => {
    const { container } = render(
      <MeasuredValue measured={m(null, "no_source")} format={formatNumber} />,
    );
    expect(screen.getByText("unavailable")).toBeInTheDocument();
    expect(container.textContent).toContain("no source");
    expect(container.textContent).not.toMatch(/(^|\s)0(\s|$)/);
  });

  it("still renders a genuine zero as 0", () => {
    render(<MeasuredValue measured={m("0")} format={formatNumber} />);
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.queryByText("unavailable")).not.toBeInTheDocument();
  });

  it("shows the radar's missing attention figures as unavailable", async () => {
    routeApi();
    render(<LifecycleLabPage />, { wrapper });
    const row = (await screen.findByRole("link", { name: "FROGCEO" })).closest("tr")!;
    // velocity, acceleration and liquidity are all null on this fixture row
    expect(within(row).getAllByText("unavailable").length).toBeGreaterThanOrEqual(3);
  });
});

describe("data health", () => {
  it("shows Reddit and X as disabled with a reason, not as empty rows", () => {
    render(<DataHealthPanel sources={SOURCES} />);
    for (const key of ["reddit", "x"]) {
      const row = screen.getByTestId(`source-${key}`);
      expect(within(row).getByText("disabled")).toBeInTheDocument();
      expect(within(row).getByText("disabled by config")).toBeInTheDocument();
    }
    // collecting source reads as collecting, backfill source is labelled exploratory
    expect(within(screen.getByTestId("source-gdelt")).getByText("collecting")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("source-geckoterminal")).getByText("EXPLORATORY (backfill)"),
    ).toBeInTheDocument();
  });
});

describe("lab overview", () => {
  it("states the portfolio is unavailable plainly and keeps PAPER ONLY on screen", async () => {
    routeApi();
    render(<LifecycleLabPage />, { wrapper });
    expect(await screen.findByText("No forward replay yet")).toBeInTheDocument();
    expect(screen.getAllByText(/PAPER ONLY — no real trading/).length).toBeGreaterThan(0);
    expect(screen.getByText("split not yet meaningful")).toBeInTheDocument();
    expect(screen.getAllByText("AUTHORITATIVE (forward)").length).toBeGreaterThan(0);
    expect(screen.getByText("$1,000.00")).toBeInTheDocument();
  });
});

describe("LifecycleOverlayChart", () => {
  const series = DETAIL.series;

  it("breaks the line at every null instead of interpolating or dropping to zero", () => {
    const { container } = render(
      <LifecycleOverlayChart series={series} markers={DETAIL.markers} />,
    );
    // attention: [2,5,null,9,12] -> a 2-point line, then a 2-point line
    const attention = container.querySelectorAll('path[data-series="attention"]');
    expect(attention).toHaveLength(2);
    // price: [a,b,c,null,d] -> a 3-point line, then a lone point drawn as a dot
    expect(container.querySelectorAll('path[data-series="price"]')).toHaveLength(1);
    expect(container.querySelectorAll('circle[data-series="price"]')).toHaveLength(1);
    // volume has no gaps -> one continuous path
    expect(container.querySelectorAll('path[data-series="volume"]')).toHaveLength(1);
    // no path ever moves through a gap: each attention path is exactly M..L (two points)
    attention.forEach((p) => expect(p.getAttribute("d")!.match(/[ML]/g)).toHaveLength(2));
  });

  it("draws one marker per input, each with an accessible title", () => {
    render(<LifecycleOverlayChart series={series} markers={DETAIL.markers} />);
    const markers = screen.getAllByTestId("chart-marker");
    expect(markers).toHaveLength(DETAIL.markers.length);
    expect(markers.map((n) => n.getAttribute("data-kind"))).toEqual([
      "token_launch", "attention_spike", "paper_entry",
    ]);
    expect(within(markers[2]!).getByText(/Paper entry/)).toBeInTheDocument();
    // legend names each kind present
    expect(screen.getByTestId("legend-marker-paper_entry")).toHaveTextContent("paper entry");
  });

  it("shades and labels the exploratory region before backfill_before", () => {
    render(<LifecycleOverlayChart series={series} markers={[]} />);
    const region = screen.getByTestId("backfill-region");
    expect(within(region).getByText("EXPLORATORY (backfill)")).toBeInTheDocument();
  });

  it("has no exploratory region when nothing is backfill", () => {
    render(
      <LifecycleOverlayChart series={{ ...series, backfill_before: null }} markers={[]} />,
    );
    expect(screen.queryByTestId("backfill-region")).not.toBeInTheDocument();
  });

  it("says a series is unavailable rather than drawing it flat when it has no points", () => {
    const { container } = render(
      <LifecycleOverlayChart
        series={{ ...series, attention: [{ t: series.attention[0]!.t, value: null }] }}
        markers={[]}
      />,
    );
    expect(container.querySelectorAll('[data-series="attention"]')).toHaveLength(0);
    expect(screen.getByTestId("legend-attention")).toHaveTextContent("unavailable");
  });
});

describe("meme detail", () => {
  it("labels exploratory data and shows linked_at, events and expandable evidence", async () => {
    routeApi();
    render(<LifecycleMemeDetailPage slug="frogceo" />, { wrapper });
    const banner = await screen.findByTestId("data-label-banner");
    expect(within(banner).getByTestId("data-boundary-exploratory")).toBeInTheDocument();
    expect(screen.getAllByText("2026-10-02 06:00Z").length).toBeGreaterThan(0); // linked_at
    // horizons not yet elapsed are unavailable, not 0%
    const eventsTable = screen.getByRole("table", { name: /Detected events/ });
    expect(within(eventsTable).getAllByText("unavailable").length).toBeGreaterThanOrEqual(2);
    expect(within(eventsTable).getByText("+40.00%")).toBeInTheDocument();

    expect(screen.queryByText(/Mentions rose to/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Show evidence/ }));
    expect(screen.getByText(/Mentions rose to 4.7x baseline/)).toBeInTheDocument();
  });
});

describe("wording", () => {
  it("never uses buy / sell / hold / consider on the board or the detail page", async () => {
    routeApi();
    const board = render(<LifecycleLabPage />, { wrapper });
    await screen.findByRole("link", { name: "FROGCEO" });
    expect(board.container.textContent).not.toMatch(FORBIDDEN);
    board.unmount();

    const detail = render(<LifecycleMemeDetailPage slug="frogceo" />, { wrapper });
    await screen.findByTestId("data-label-banner");
    fireEvent.click(screen.getByRole("button", { name: /Show evidence/ }));
    expect(detail.container.textContent).not.toMatch(FORBIDDEN);
    expect(detail.container.textContent).toMatch(/paper entry/i);
  });
});

describe("navigation", () => {
  it("lists the lab as a ready destination", () => {
    const item = NAV_GROUPS.flatMap((g) => g.items).find((i) => i.href === "/lifecycle-lab");
    expect(item).toBeDefined();
    expect(item?.status).toBe("ready");
    expect(`${item?.label} ${item?.note ?? ""}`).not.toMatch(FORBIDDEN);
  });
});
