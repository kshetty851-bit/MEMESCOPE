import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type * as ApiClientModule from "@/lib/api-client";
import { api } from "@/lib/api-client";

import { AuditTrailView } from "./audit-trail";
import {
  EXPLORATORY_BODY,
  EXPLORATORY_HEADLINE,
  FORWARD_BODY,
  FORWARD_HEADLINE,
  DataBoundaryBanner,
  boundaryKinds,
} from "./data-boundary-banner";
import { StatusPill } from "./display";
import {
  DETAIL,
  MEMES,
  MEME_QUALITY,
  OVERVIEW,
  QUALITY,
  RESEARCH_STATUS,
  SOURCES,
} from "./fixtures";
import { LifecycleLabPage, LifecycleMemeDetailPage } from "./page";
import { LifecycleQualityPage, QualityReportView } from "./quality-page";
import { ResearchStatusPanel } from "./research-status-panel";
import type { ResearchState, ResearchStatus, SourceStatus } from "./types";

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

const FORBIDDEN = /\b(buy|sell|hold|consider)\b/i;

const withState = (state: ResearchState, extra: Partial<ResearchStatus> = {}): ResearchStatus => ({
  ...RESEARCH_STATUS,
  state,
  ...extra,
});

function routeApi() {
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === "/lifecycle-lab/overview") return OVERVIEW;
    if (path === "/lifecycle-lab/health") return { generated_at: "x", sources: SOURCES };
    if (path === "/lifecycle-lab/memes") return MEMES;
    if (path === "/lifecycle-lab/memes/frogceo") return DETAIL;
    if (path === "/lifecycle-lab/memes/frogceo/quality") return MEME_QUALITY;
    if (path === "/lifecycle-lab/quality") return QUALITY;
    throw new Error(`unexpected ${path}`);
  });
}

describe("research status panel", () => {
  const NON_FINAL: ResearchState[] = [
    "NOT_STARTED",
    "COLLECTING",
    "INSUFFICIENT_DATA",
    "READY_FOR_ANALYSIS",
    "ANALYZING",
  ];

  it.each(NON_FINAL)("%s shows VERDICT: UNCERTAIN", (state) => {
    render(<ResearchStatusPanel status={withState(state)} />);
    expect(screen.getByTestId("research-verdict")).toHaveTextContent("VERDICT: UNCERTAIN");
    expect(screen.getByTestId("research-state")).toHaveTextContent(state.replace(/_/g, " "));
  });

  it("never prints EDGE / NO EDGE outside AUTHORITATIVE_RESULT, even if the API sends a verdict", () => {
    for (const state of NON_FINAL) {
      const { container, unmount } = render(
        <ResearchStatusPanel
          status={withState(state, { verdict: "EDGE_EXISTS", verdict_engine_available: true })}
        />,
      );
      expect(container.textContent).not.toMatch(/\bEDGE\b/i);
      expect(container.textContent).not.toMatch(/NO EDGE/i);
      expect(container.textContent).toContain("VERDICT: UNCERTAIN");
      unmount();
    }
  });

  it("shows the API verdict only for AUTHORITATIVE_RESULT with an available engine", () => {
    const { container, rerender } = render(
      <ResearchStatusPanel
        status={withState("AUTHORITATIVE_RESULT", { verdict: "NO_EDGE", verdict_engine_available: true })}
      />,
    );
    expect(screen.getByTestId("research-verdict")).toHaveTextContent("VERDICT: NO EDGE");
    // a final state without an engine is not a result
    rerender(
      <ResearchStatusPanel
        status={withState("AUTHORITATIVE_RESULT", { verdict: "NO_EDGE", verdict_engine_available: false })}
      />,
    );
    expect(container.textContent).toContain("VERDICT: UNCERTAIN");
    expect(container.textContent).not.toMatch(/NO EDGE/);
  });

  it("renders the requirements table with unmet rows, their reasons, and unavailable observed values", () => {
    render(<ResearchStatusPanel status={RESEARCH_STATUS} />);
    const table = screen.getByRole("table", { name: /Minimum evidence requirements/ });
    const period = within(table).getByTestId("requirement-forward_period");
    expect(period).toHaveAttribute("data-met", "false");
    expect(within(period).getByText("Forward observation period")).toBeInTheDocument();
    expect(within(period).getByText("90 days")).toBeInTheDocument();
    expect(within(period).getByText("9.5 days")).toBeInTheDocument();
    expect(within(period).getByText(/✗/)).toBeInTheDocument();
    expect(within(period).getByText("forward span shorter than horizon")).toBeInTheDocument();

    // observed null -> the word "unavailable", not 0 and not blank
    const arms = within(table).getByTestId("requirement-control_arms");
    expect(within(arms).getByText("unavailable")).toBeInTheDocument();
    expect(within(arms).getByText("no experiment runs")).toBeInTheDocument();

    const met = within(table).getByTestId("requirement-min_memes");
    expect(met).toHaveAttribute("data-met", "true");
    expect(within(met).getByText(/✓/)).toBeInTheDocument();
    expect(screen.getByText("1 of 4")).toBeInTheDocument();
  });

  it("shows the explanation and forward days; null forward days is unavailable", () => {
    const { rerender } = render(<ResearchStatusPanel status={RESEARCH_STATUS} />);
    expect(screen.getByText(RESEARCH_STATUS.explanation)).toBeInTheDocument();
    expect(screen.getByTestId("research-forward-days")).toHaveTextContent("9.5");
    rerender(<ResearchStatusPanel status={withState("NOT_STARTED", { forward_days: null })} />);
    expect(screen.getByTestId("research-forward-days")).toHaveTextContent("unavailable");
  });

  it("sits at the top of the Lab page from overview.research_status", async () => {
    routeApi();
    render(<LifecycleLabPage />, { wrapper });
    const panel = await screen.findByTestId("research-status");
    expect(panel).toHaveTextContent("VERDICT: UNCERTAIN");
    expect(screen.getByRole("link", { name: /Data quality/ })).toHaveAttribute(
      "href",
      "/lifecycle-lab/quality",
    );
    // research panel precedes the overview panel in document order
    const overview = screen.getByText(/Lab overview/);
    expect(panel.compareDocumentPosition(overview) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("data boundary banner", () => {
  it("carries the exact copy from the doc", () => {
    const { container, unmount } = render(<DataBoundaryBanner kind="exploratory" />);
    expect(container.textContent).toBe(
      "EXPLORATORY DATA — Historical data may contain survivorship or look-ahead limitations. Not used for the authoritative strategy verdict.",
    );
    unmount();
    const fwd = render(<DataBoundaryBanner kind="forward" />);
    expect(fwd.container.textContent).toBe(
      "FORWARD DATA — Collected prospectively by MEMESCOPE. Eligible for the authoritative research dataset.",
    );
    expect(`${EXPLORATORY_HEADLINE} — ${EXPLORATORY_BODY}`).toContain("survivorship or look-ahead");
    expect(`${FORWARD_HEADLINE} — ${FORWARD_BODY}`).toContain("Collected prospectively");
  });

  it("picks the kind from data_label / contains_backfill", () => {
    expect(boundaryKinds("exploratory", true)).toEqual(["exploratory"]);
    expect(boundaryKinds("authoritative", false)).toEqual(["forward"]);
    expect(boundaryKinds("authoritative", true)).toEqual(["exploratory", "forward"]);
  });

  it("appears on the meme detail page for backfilled data", async () => {
    routeApi();
    render(<LifecycleMemeDetailPage slug="frogceo" />, { wrapper });
    const banner = await screen.findByTestId("data-label-banner");
    expect(within(banner).getByTestId("data-boundary-exploratory")).toBeInTheDocument();
    expect(within(banner).queryByTestId("data-boundary-forward")).not.toBeInTheDocument();
  });

  it("appears as FORWARD on the meme detail page for forward-only data", async () => {
    vi.mocked(api.get).mockImplementation(async (path: string) => {
      if (path === "/lifecycle-lab/memes/frogceo")
        return { ...DETAIL, data_label: "authoritative", contains_backfill: false };
      if (path === "/lifecycle-lab/memes/frogceo/quality") return MEME_QUALITY;
      throw new Error(`unexpected ${path}`);
    });
    render(<LifecycleMemeDetailPage slug="frogceo" />, { wrapper });
    const banner = await screen.findByTestId("data-label-banner");
    expect(within(banner).getByTestId("data-boundary-forward")).toBeInTheDocument();
    expect(within(banner).queryByTestId("data-boundary-exploratory")).not.toBeInTheDocument();
  });
});

describe("quality page", () => {
  it("renders a null success rate as unavailable, never 0%", () => {
    const report = {
      ...QUALITY,
      collection: { ...QUALITY.collection, success_rate_24h: null },
    };
    render(<QualityReportView report={report} />);
    const cell = screen.getByTestId("collection-success-rate");
    expect(cell).toHaveTextContent("unavailable");
    expect(cell.textContent).not.toMatch(/0(\.0)?%/);
    // the per-source row with a null rate says so too
    const reddit = screen.getByTestId("quality-source-reddit");
    expect(within(reddit).getByText("unavailable")).toBeInTheDocument();
    // a present rate is formatted
    expect(within(screen.getByTestId("quality-source-gdelt")).getByText("95.8%")).toBeInTheDocument();
  });

  it("shows the overall rate when present", () => {
    render(<QualityReportView report={QUALITY} />);
    expect(screen.getByTestId("collection-success-rate")).toHaveTextContent("97.7%");
  });

  it("splits forward and backfill observations under both boundary banners", () => {
    render(<QualityReportView report={QUALITY} />);
    const boundary = screen.getByTestId("quality-boundary");
    expect(boundary.textContent).toContain(
      "FORWARD DATA — Collected prospectively by MEMESCOPE. Eligible for the authoritative research dataset.",
    );
    expect(boundary.textContent).toContain(
      "EXPLORATORY DATA — Historical data may contain survivorship or look-ahead limitations. Not used for the authoritative strategy verdict.",
    );
    expect(screen.getByText("2,100")).toBeInTheDocument();
    expect(screen.getByText("5,600")).toBeInTheDocument();
    expect(screen.getByText("340")).toBeInTheDocument();
  });

  it("lists sources, gaps and missing fields", () => {
    render(<QualityReportView report={QUALITY} />);
    expect(screen.getByText("Unavailable sources")).toBeInTheDocument();
    expect(within(screen.getByTestId("gap-memes")).getByRole("link", { name: "NEWMEME" })).toHaveAttribute(
      "href",
      "/lifecycle-lab/newmeme",
    );
    expect(within(screen.getByTestId("gap-tokens")).getByRole("link", { name: "frogceo" })).toBeInTheDocument();
    expect(within(screen.getByTestId("gap-incomplete")).getByText("liquidity usd")).toBeInTheDocument();
    expect(screen.getByTestId("oldest-forward")).toHaveTextContent("2026-10-01 00:05Z");
    const reddit = screen.getByTestId("quality-source-reddit");
    expect(within(reddit).getByText("disabled")).toBeInTheDocument();
    expect(within(reddit).getByText("disabled by config")).toBeInTheDocument();
  });

  it("says forward observations are unavailable when there are none", () => {
    render(
      <QualityReportView
        report={{
          ...QUALITY,
          oldest_forward_observation_at: null,
          newest_forward_observation_at: null,
          memes_without_observations: [],
        }}
      />,
    );
    expect(screen.getByTestId("oldest-forward")).toHaveTextContent("unavailable");
    expect(screen.getByTestId("newest-forward")).toHaveTextContent("unavailable");
    expect(screen.getByTestId("gap-memes")).toHaveTextContent(/every tracked meme/i);
  });

  it("loads from GET /quality", async () => {
    routeApi();
    render(<LifecycleQualityPage />, { wrapper });
    expect(await screen.findByRole("heading", { name: "Data quality" })).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/lifecycle-lab/quality");
  });
});

describe("source status pills", () => {
  const ALL: SourceStatus[] = [
    "available",
    "disabled",
    "unavailable",
    "error",
    "stale",
    "partial",
    "never_collected",
  ];

  it("renders seven distinct labels, none of them a number", () => {
    const texts = ALL.map((status) => {
      const { container, unmount } = render(<StatusPill status={status} />);
      const text = container.textContent ?? "";
      expect(container.querySelector(`[data-status="${status}"]`)).not.toBeNull();
      expect(text).not.toMatch(/\d/);
      expect(text.length).toBeGreaterThan(0);
      unmount();
      return text;
    });
    expect(new Set(texts).size).toBe(7);
    expect(texts).toContain("never collected");
  });

  it("gives each status a distinct style signature", () => {
    const sigs = ALL.map((status) => {
      const { container, unmount } = render(<StatusPill status={status} />);
      const cls = container.querySelector("span span")!.className;
      unmount();
      return cls;
    });
    expect(new Set(sigs).size).toBe(7);
  });

  it("does not crash on a status the client has not heard of", () => {
    const { container } = render(<StatusPill status="rate_limited" />);
    expect(container.textContent).toBe("rate limited");
  });
});

describe("audit trail", () => {
  it("shows linked_at, method, confidence, linked_by and evidence for each link", () => {
    render(<AuditTrailView audit={MEME_QUALITY} />);
    const trail = screen.getByTestId("audit-trail");
    const links = within(trail).getByRole("table", { name: /Token links/ });
    expect(within(links).getByText("2026-10-02 06:00Z")).toBeInTheDocument();
    expect(within(links).getByText("manual")).toBeInTheDocument();
    expect(within(links).getByText("80%")).toBeInTheDocument();
    expect(within(links).getByText("operator")).toBeInTheDocument();
    expect(within(links).getByText("ticker matches meme name")).toBeInTheDocument();
    expect(within(links).getByText("still linked")).toBeInTheDocument();
  });

  it("shows aliases with added_at, per-source counts, market gaps and the state block", () => {
    render(<AuditTrailView audit={MEME_QUALITY} />);
    expect(screen.getByTestId("audit-aliases")).toHaveTextContent("added 2026-10-01 00:00Z");

    const gdelt = screen.getByTestId("audit-source-gdelt");
    for (const v of ["120", "100", "20"]) expect(within(gdelt).getByText(v)).toBeInTheDocument();
    expect(within(gdelt).getByText("collecting")).toBeInTheDocument();
    // never-observed source: dates are unavailable, counts are real zeros
    const reddit = screen.getByTestId("audit-source-reddit");
    expect(within(reddit).getAllByText("unavailable")).toHaveLength(2);
    expect(within(reddit).getByText("disabled")).toBeInTheDocument();

    expect(screen.getByText("liquidity usd")).toBeInTheDocument();
    expect(screen.getByText("dormant")).toBeInTheDocument();
    expect(screen.getByText("4.70×")).toBeInTheDocument();
    // velocity and acceleration are unavailable, not 0
    const trail = screen.getByTestId("audit-trail");
    expect(within(trail).getAllByText("unavailable").length).toBeGreaterThanOrEqual(2);
  });

  it("labels collection priority as frequency only", () => {
    render(<AuditTrailView audit={MEME_QUALITY} />);
    const p = screen.getByTestId("collection-priority");
    expect(p).toHaveTextContent("low");
    expect(p).toHaveTextContent("every 6h");
    expect(p).toHaveTextContent("dormant no recent change");
    expect(p).toHaveTextContent("Collection frequency only; not used in trading decisions.");
  });

  it("shows both boundary banners only when a source holds backfill", () => {
    const { rerender } = render(<AuditTrailView audit={MEME_QUALITY} />);
    expect(screen.getByTestId("data-boundary-exploratory")).toBeInTheDocument();
    rerender(
      <AuditTrailView
        audit={{
          ...MEME_QUALITY,
          sources: MEME_QUALITY.sources.map((s) => ({ ...s, backfill_count: 0 })),
        }}
      />,
    );
    expect(screen.queryByTestId("data-boundary-exploratory")).not.toBeInTheDocument();
  });

  it("is part of the meme detail page", async () => {
    routeApi();
    render(<LifecycleMemeDetailPage slug="frogceo" />, { wrapper });
    expect(await screen.findByTestId("audit-trail")).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/lifecycle-lab/memes/frogceo/quality");
  });

  it("renders a degraded evidence shape without crashing", () => {
    render(
      <AuditTrailView
        audit={{
          ...MEME_QUALITY,
          links: [
            { ...MEME_QUALITY.links[0]!, evidence: null, linked_by: null },
          ],
        }}
      />,
    );
    expect(screen.getByText("none recorded")).toBeInTheDocument();
    expect(screen.getByText("not recorded")).toBeInTheDocument();
  });
});

describe("wording", () => {
  it("never uses buy / sell / hold / consider on the new surfaces", async () => {
    routeApi();
    const quality = render(<LifecycleQualityPage />, { wrapper });
    await screen.findByRole("heading", { name: "Data quality" });
    expect(quality.container.textContent).not.toMatch(FORBIDDEN);
    quality.unmount();

    const detail = render(<LifecycleMemeDetailPage slug="frogceo" />, { wrapper });
    await screen.findByTestId("audit-trail");
    expect(detail.container.textContent).not.toMatch(FORBIDDEN);
    detail.unmount();

    for (const state of [
      "NOT_STARTED", "COLLECTING", "INSUFFICIENT_DATA", "READY_FOR_ANALYSIS",
      "ANALYZING", "AUTHORITATIVE_RESULT",
    ] as ResearchState[]) {
      const r = render(<ResearchStatusPanel status={withState(state)} />);
      expect(r.container.textContent).not.toMatch(FORBIDDEN);
      r.unmount();
    }
  });
});

describe("contract fixtures", () => {
  it("carry every field the validation-phase contract names", () => {
    expect(Object.keys(QUALITY).sort()).toEqual(
      [
        "collection", "generated_at", "memes_without_observations",
        "newest_forward_observation_at", "observations_today", "observations_week",
        "oldest_forward_observation_at", "stale_sources", "tokens_with_incomplete_market_data",
        "tokens_without_market_history", "tracked_memes", "tracked_tokens", "unavailable_sources",
      ].sort(),
    );
    expect(Object.keys(QUALITY.collection.by_source[0]!).sort()).toEqual(
      [
        "available", "disabled", "error", "label", "last_reason", "last_status",
        "last_success_at", "partial", "runs_24h", "source", "stale", "success_rate_24h",
        "unavailable",
      ].sort(),
    );
    expect(Object.keys(MEME_QUALITY).sort()).toEqual(
      [
        "aliases", "attention", "collection_priority", "divergence_case", "lifecycle_state",
        "links", "market", "meme", "sources",
      ].sort(),
    );
    expect(Object.keys(MEME_QUALITY.links[0]!)).toEqual(
      expect.arrayContaining(["mint", "method", "confidence", "linked_at", "unlinked_at", "linked_by", "evidence"]),
    );
    expect(Object.keys(RESEARCH_STATUS).sort()).toEqual(
      [
        "experiment_key", "explanation", "forward_days", "forward_start", "requirements",
        "state", "verdict", "verdict_engine_available",
      ].sort(),
    );
    expect(Object.keys(RESEARCH_STATUS.requirements[0]!).sort()).toEqual(
      ["key", "label", "threshold", "observed", "met", "reason"].sort(),
    );
    expect(OVERVIEW.research_status).toBe(RESEARCH_STATUS);
  });
});
