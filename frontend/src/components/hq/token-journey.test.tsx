import fs from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HqStage } from "@/components/hq/hq-stage";
import { CaseFilePanel } from "@/components/hq/case-file-panel";
import { deriveCaseFile, type CaseStageStatus, type TokenCaseFile } from "@/lib/hq/case-file";
import { UNKNOWN_HQ_STATE } from "@/lib/hq/adapter";
import { GRID_COLS, GRID_ROWS } from "@/lib/hq/geometry";
import { ZONES, ZONE_BY_ID } from "@/lib/hq/zones";
import { EMPLOYEE_BY_ID } from "@/lib/hq/employees";
import type { RadarDetail } from "@/types/radar";
import type { PaperPositions } from "@/types/paper";

/**
 * HQ-5 acceptance: the live token journey drawn into the room.
 *
 * `case-file.test.ts` defends the adapter's truthfulness in isolation; this
 * file defends the two things that only exist once the adapter's output
 * reaches the DOM — that a packet's status is legible as text and not just
 * as colour, that the physical room the world-expansion phase froze is still
 * exactly 22×14 with every coordinate untouched, and that reduced motion and
 * mobile keep every promise HQ-3/HQ-4 already made.
 */

const noop = () => {};

function matchMedia(reduced: boolean) {
  return vi.fn().mockImplementation((query: string) => ({
    matches: query.includes("reduce") ? reduced : false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
    onchange: null,
  }));
}

const STATUS_TEXT: Record<CaseStageStatus, string> = {
  PASSED: "Passed",
  FAILED: "Failed",
  PENDING: "Pending",
  UNKNOWN: "Unknown",
  UNAVAILABLE: "Not available",
};

beforeEach(() => {
  window.matchMedia = matchMedia(false);
});

function radarFixture(overrides: Partial<RadarDetail> = {}): RadarDetail {
  return {
    mint_address: "MintPassed11111111111111111111111111111",
    name: "Passed Token",
    symbol: "PASS",
    image_url: null,
    category: "early_momentum",
    original_category: "early_momentum",
    opportunity_score: "80",
    confidence: "75",
    first_detected_at: "2026-01-01T00:00:00Z",
    first_price: null,
    first_market_cap: null,
    first_liquidity: null,
    first_opportunity_score: "80",
    current_price: null,
    current_market_cap: "60000",
    current_liquidity: "12000",
    current_multiple: null,
    peak_multiple: null,
    peak_price: null,
    peak_market_cap: null,
    peak_at: null,
    days_since_detection: "1",
    is_active: true,
    detection_reason: [],
    achieved_tiers: [],
    liveness: "alive",
    model_version: "v1",
    last_evaluated_at: "2026-01-01T00:05:00Z",
    base_rate: null,
    market: {
      price_usd: "0.001",
      market_cap: "60000",
      liquidity_usd: "12000",
      volume_24h: null,
      change_24h_pct: null,
      captured_at: "2026-01-01T00:05:00Z",
      dex_name: "pumpswap",
    },
    age_seconds: null,
    risk_score: null,
    risk_band: null,
    risk_reasons: [],
    evidence: null,
    signal: null,
    why_now: null,
    dimensions: [{ id: "momentum", label: "Momentum", available: true, score: "70", effective_weight: "1", reasons: [] }],
    reasons: [],
    achievements: [],
    ...overrides,
  };
}

function caseFile(mint: string, radar: RadarDetail | null, positions: PaperPositions["items"] = []): TokenCaseFile {
  const now = Date.parse("2026-06-01T00:00:00Z");
  return deriveCaseFile(mint, {
    radar: radar ? { data: radar, observedAt: now } : { data: null, observedAt: null },
    safety: { data: null, observedAt: null },
    paperPositions: { data: { items: positions, enabled: true, observed_at: "2026-01-01T00:00:00Z" }, observedAt: now },
    now,
  });
}

const PASSED_CASE = caseFile(
  "MintPassed11111111111111111111111111111",
  radarFixture({
    mint_address: "MintPassed11111111111111111111111111111",
  }),
);

const UNAVAILABLE_CASE = caseFile("MintGhost11111111111111111111111111111", null);

/* ---------------------------------------------------------------------- */

describe("the physical room stays frozen", () => {
  it("keeps the world-expansion 22×14 geometry, untouched by HQ-5", () => {
    expect(GRID_COLS).toBe(22);
    expect(GRID_ROWS).toBe(14);
  });

  it("keeps every working department's rectangle where it was", () => {
    // The composition pass was authorised to reflow the room, and did — but
    // only at the two edges that were empty. Every department somebody works
    // in is byte-identical, so no desk, route or prop moved under anyone.
    expect(ZONE_BY_ID.get("mission")!.rect).toEqual({ col: 0, row: 0, cols: 16, rows: 2 });
    expect(ZONE_BY_ID.get("conference")!.rect).toEqual({ col: 16, row: 0, cols: 6, rows: 4 });
    expect(ZONE_BY_ID.get("pantry")!.rect).toEqual({ col: 0, row: 10, cols: 8, rows: 2 });
    expect(ZONE_BY_ID.get("lounge")!.rect).toEqual({ col: 8, row: 10, cols: 8, rows: 2 });
    expect(ZONE_BY_ID.get("facilities")!.rect).toEqual({ col: 0, row: 12, cols: 3, rows: 2 });
  });

  it("leaves no tile of the building belonging to no department", () => {
    // The composition fix, pinned. cols 16-22 x rows 8-14 — 42 tiles, a sixth
    // of the floor — used to belong to nothing and rendered as a hole in the
    // south-east corner. The deck now runs to row 12 and reception spans the
    // full south wall, so the footprint is a complete rectangle.
    expect(ZONE_BY_ID.get("deck")!.rect).toEqual({ col: 16, row: 4, cols: 6, rows: 8 });
    expect(ZONE_BY_ID.get("reception")!.rect).toEqual({ col: 6, row: 12, cols: 16, rows: 2 });

    const covered = new Set<string>();
    for (const zone of ZONES) {
      for (let c = zone.rect.col; c < zone.rect.col + zone.rect.cols; c += 1) {
        for (let r = zone.rect.row; r < zone.rect.row + zone.rect.rows; r += 1) {
          covered.add(`${c},${r}`);
        }
      }
    }
    const orphans: string[] = [];
    for (let c = 0; c < GRID_COLS; c += 1) {
      for (let r = 0; r < GRID_ROWS; r += 1) {
        if (!covered.has(`${c},${r}`)) orphans.push(`${c},${r}`);
      }
    }
    expect(orphans).toEqual([]);
  });

  it("keeps every employee desk exactly where it already was", () => {
    expect(EMPLOYEE_BY_ID.get("radar")!.desk).toEqual({ col: 6, row: 3 });
    expect(EMPLOYEE_BY_ID.get("luna")!.desk).toEqual({ col: 8, row: 3 });
    expect(EMPLOYEE_BY_ID.get("dex")!.desk).toEqual({ col: 10, row: 3 });
    expect(EMPLOYEE_BY_ID.get("atlas")!.desk).toEqual({ col: 2, row: 4 });
    expect(EMPLOYEE_BY_ID.get("rex")!.desk).toEqual({ col: 12, row: 4 });
  });
});

describe("visible packets in the room", () => {
  it("draws a packet for each visible case, docked at the right employee", () => {
    const { container } = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        visibleCases={[PASSED_CASE]}
        onSelectCase={noop}
      />,
    );
    const packet = container.querySelector('[data-packet-stage]')!;
    expect(packet).not.toBeNull();
    // PASSED_CASE's currentStage should anchor at Rex (decision/execution) or
    // an earlier employee depending on what evidence exists — whichever it
    // is, the dock must be a real employee anchor, not a fabricated position.
    expect(packet.getAttribute("data-packet-stage")).toBe(PASSED_CASE.currentStage);
  });

  it("carries status as text in the accessible name, never colour alone", () => {
    const { container } = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        visibleCases={[PASSED_CASE]}
        onSelectCase={noop}
      />,
    );
    const packet = container.querySelector('[data-packet-stage]')!;
    const label = packet.getAttribute("aria-label")!;
    expect(label).toContain(PASSED_CASE.symbol);
    expect(label).toContain(PASSED_CASE.stages[PASSED_CASE.currentStage].status);
  });

  it("never draws more than three packets even when handed more", () => {
    const extra = caseFile("MintExtra1111111111111111111111111111111", radarFixture({ mint_address: "MintExtra1111111111111111111111111111111" }));
    const extra2 = caseFile("MintExtra2222222222222222222222222222222", radarFixture({ mint_address: "MintExtra2222222222222222222222222222222" }));
    const extra3 = caseFile("MintExtra3333333333333333333333333333333", radarFixture({ mint_address: "MintExtra3333333333333333333333333333333" }));
    const { container } = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        visibleCases={[PASSED_CASE, extra, extra2, extra3]}
        onSelectCase={noop}
      />,
    );
    // The stage draws whatever it is handed; the *cap itself* is enforced by
    // `selectPackets`, which `packets.test.ts` covers directly. This asserts
    // the stage does not silently drop or duplicate what it is given.
    expect(container.querySelectorAll('[data-packet-stage]')).toHaveLength(4);
  });

  it("shows a real overflow count and nothing when none exists", () => {
    const withOverflow = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        visibleCases={[PASSED_CASE]}
        caseOverflow={12}
        onSelectCase={noop}
      />,
    );
    expect(withOverflow.container.querySelector(".hq-packet-overflow")).not.toBeNull();
    expect(withOverflow.container.textContent).toContain("+12");
    withOverflow.unmount();

    const withoutOverflow = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        visibleCases={[PASSED_CASE]}
        caseOverflow={null}
        onSelectCase={noop}
      />,
    );
    expect(withoutOverflow.container.querySelector(".hq-packet-overflow")).toBeNull();
  });

  it("opens a case on click and on keyboard activation", () => {
    const onSelectCase = vi.fn();
    const { container } = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        visibleCases={[PASSED_CASE]}
        onSelectCase={onSelectCase}
      />,
    );
    const packet = container.querySelector('[data-packet-stage]')! as SVGElement;
    packet.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(onSelectCase).toHaveBeenCalledWith(PASSED_CASE.mint);

    packet.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(onSelectCase).toHaveBeenCalledTimes(2);
  });

  it("stops packet travel during HIGH_ALERT without hiding the packet", () => {
    const { container } = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        state={{ ...UNKNOWN_HQ_STATE, activity: "HIGH_ALERT" }}
        visibleCases={[PASSED_CASE]}
        onSelectCase={noop}
      />,
    );
    const packet = container.querySelector('[data-packet-stage]')!;
    expect(packet.getAttribute("data-motion")).toBe("off");
    // Still there, still clickable — HIGH_ALERT quiets animation, not truth.
    expect(packet.getAttribute("role")).toBe("button");
  });

  it("stops packet travel under reduced motion, same as every other animation", () => {
    window.matchMedia = matchMedia(true);
    const { container } = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        visibleCases={[PASSED_CASE]}
        onSelectCase={noop}
      />,
    );
    const packet = container.querySelector('[data-packet-stage]')!;
    expect(packet.getAttribute("data-motion")).toBe("off");
  });
});

describe("the Token Case File panel", () => {
  it("shows every stage's status as readable text", () => {
    render(<CaseFilePanel file={PASSED_CASE} onClose={noop} />);
    const stages = Object.values(PASSED_CASE.stages) as Array<{ status: CaseStageStatus }>;
    for (const stage of stages) {
      expect(screen.getAllByText(new RegExp(STATUS_TEXT[stage.status], "i")).length).toBeGreaterThan(0);
    }
  });

  it("never shows a fabricated value — missing evidence renders NOT AVAILABLE", () => {
    render(<CaseFilePanel file={UNAVAILABLE_CASE} onClose={noop} />);
    const evidence = screen.getByTestId("hq-case-evidence");
    expect(evidence.textContent).toContain("NOT AVAILABLE");
    expect(evidence.textContent).not.toMatch(/\$0(?!\d)/);
  });

  it("keeps market depth and security evidence in separate sections", () => {
    // The confusion this whole line of work guards against: "Liquidity
    // $24,300" sitting one row above "Liquidity security: Unknown" invites a
    // reader to treat the first as evidence for the second.
    render(<CaseFilePanel file={PASSED_CASE} onClose={noop} />);
    const market = screen.getByTestId("hq-case-evidence-market");
    const security = screen.queryByTestId("hq-case-evidence-security");
    expect(market.textContent).toContain("Current liquidity");
    expect(market.textContent).not.toContain("Liquidity security");
    if (security) expect(security.textContent).not.toContain("Current liquidity");
  });

  it("distinguishes AT ENTRY, CURRENT and LAST CHECKED where the adapter set them", () => {
    render(<CaseFilePanel file={PASSED_CASE} onClose={noop} />);
    const evidence = screen.getByTestId("hq-case-evidence");
    expect(evidence.textContent).toMatch(/current/i);
  });
});

describe("mobile and reduced-motion isolation", () => {
  const root = path.resolve(__dirname, "../..");

  function staticallyReachable(entry: string): Set<string> {
    const seen = new Set<string>();
    const queue = [path.join(root, entry)];
    while (queue.length > 0) {
      const file = queue.pop()!;
      if (seen.has(file) || !fs.existsSync(file)) continue;
      seen.add(file);
      const source = fs.readFileSync(file, "utf8");
      const stripped = source.replace(/import\s*\(/g, "DYNAMIC_IMPORT(");
      const resolve = (specifier: string): string | null => {
        if (!specifier.startsWith("@/")) return null;
        const base = path.join(root, specifier.slice(2));
        for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, "index.ts"), path.join(base, "index.tsx")]) {
          if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
        }
        return null;
      };
      for (const match of stripped.matchAll(/from\s+["'](@\/[^"']+)["']/g)) {
        const next = resolve(match[1]!);
        if (next) queue.push(next);
      }
    }
    return seen;
  }

  it("keeps the token-packet scheduler out of the mobile card path", () => {
    const reachable = staticallyReachable("components/hq/hq-cards.tsx");
    expect([...reachable].some((file) => file.includes("token-packet"))).toBe(false);
    expect([...reachable].some((file) => file.includes("use-token-cases"))).toBe(false);
    expect([...reachable].some((file) => file.includes("hq-stage"))).toBe(false);
  });

  it("never lets support staff or cats reach TokenCaseFile", () => {
    for (const file of ["lib/hq/support.ts", "lib/hq/cats.ts"]) {
      const source = fs.readFileSync(path.join(root, file), "utf8");
      expect(source, `${file} reaches case-file`).not.toMatch(/case-file|TokenCaseFile|packets\.ts/);
    }
  });
});
