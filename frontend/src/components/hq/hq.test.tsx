import fs from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HqCards } from "@/components/hq/hq-cards";
import { HqStage } from "@/components/hq/hq-stage";
import { FURNITURE } from "@/lib/hq/furniture";
import { SUPPORT_STAFF } from "@/lib/hq/support";
import { CATS } from "@/lib/hq/cats";
import { AMBIENT_ROUTINES, DAY_PHASES, isInBreakRoom } from "@/lib/hq/ambient";
import { deriveHqState, type HqState } from "@/lib/hq/adapter";
import type { PipelineHealth } from "@/lib/hq/pipeline";
import { EMPLOYEES, NON_HEALTHY_STATES, STATE_LABEL } from "@/lib/hq/employees";
import { FOCUSABLE_ZONES } from "@/lib/hq/zones";
import { CHARACTERS } from "@/lib/hq/characters";
import { Portrait } from "@/components/hq/portrait";
import { Character } from "@/components/hq/character-rig";
import { NAV_GROUPS } from "@/lib/design/nav";

/**
 * HQ-1 acceptance.
 *
 * The tests that matter here are not "does it render" — they are the two
 * promises the plan makes that are easy to break by accident: that HQ never
 * presents unmeasured state as healthy, and that HQ's code cannot reach the
 * bundles of the screens people actually trade from.
 */

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

beforeEach(() => {
  window.matchMedia = matchMedia(false);
});

const noop = () => {};

describe("navigation", () => {
  it("publishes an HQ entry that points at the route", () => {
    const items = NAV_GROUPS.flatMap((group) => group.items);
    const hq = items.find((item) => item.href === "/hq");
    expect(hq).toBeDefined();
    expect(hq?.label).toBe("HQ");
    expect(hq?.status).toBe("ready");
  });

  it("does not disturb the existing destinations", () => {
    const hrefs = NAV_GROUPS.flatMap((group) => group.items).map((item) => item.href);
    for (const existing of ["/command", "/trending", "/launches", "/record", "/watchlist", "/wallet"]) {
      expect(hrefs).toContain(existing);
    }
  });
});

describe("the stage", () => {
  it("renders every department and every member of staff", () => {
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );

    for (const zone of FOCUSABLE_ZONES) {
      expect(container.querySelector(`[data-zone="${zone.id}"]`)).not.toBeNull();
    }
    for (const employee of EMPLOYEES) {
      expect(container.querySelector(`[data-employee="${employee.id}"]`)).not.toBeNull();
    }
    expect(EMPLOYEES.length).toBeGreaterThanOrEqual(10);
  });

  it("shows no data rather than idle for every employee", () => {
    // The single most important assertion in this phase. Nothing is measured
    // yet, and `Idle` would be a claim about a system nobody has asked.
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );

    for (const employee of EMPLOYEES) {
      const node = container.querySelector(`[data-employee="${employee.id}"]`)!;
      expect(node.getAttribute("data-state")).toBe("unknown");
      expect(node.getAttribute("aria-label")).toContain(STATE_LABEL.unknown);
    }
    expect(container.textContent).not.toContain(STATE_LABEL.idle);
    expect(container.textContent).not.toContain(STATE_LABEL.working);
  });

  it("marks unmeasured staff as unmeasured, not as a healthy state", () => {
    expect(NON_HEALTHY_STATES).toContain("unknown");
    expect(NON_HEALTHY_STATES).toContain("offline");
    expect(NON_HEALTHY_STATES).not.toContain("working");
  });

  it("claims no system status on the mission board", () => {
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    // With no sources the roll-up is UNKNOWN, and the board says so. The one
    // thing it may never do is imply health on the most authoritative surface
    // in the product.
    expect(container.textContent).toContain("Office activity UNKNOWN");
    for (const forbidden of ["ONLINE", "HEALTHY", "ACTIVE"]) {
      expect(container.textContent).not.toContain(forbidden);
    }
  });

  it("gives every employee an accessible name carrying their state", () => {
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    for (const employee of EMPLOYEES) {
      // Name, role, state, then the sentence explaining the state. The pose is
      // deliberately absent: ambient motion is decoration and must never reach
      // a screen reader as though it were status.
      const node = container.querySelector(`[data-employee="${employee.id}"]`)!;
      const label = node.getAttribute("aria-label")!;
      expect(label.startsWith(`${employee.name}, ${employee.role}. ${STATE_LABEL.unknown}.`)).toBe(
        true,
      );
      expect(label.length).toBeGreaterThan(
        `${employee.name}, ${employee.role}. ${STATE_LABEL.unknown}.`.length,
      );
    }
  });

  it("describes the room for a reader who cannot see it", () => {
    render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    const image = screen.getByRole("img");
    const label = image.getAttribute("aria-label")!;
    expect(label).toContain("Mission Control");
    // The roll-up and every individual reading, as text. A reader who cannot
    // see the room gets strictly more than a reader who can.
    expect(label).toContain("Office activity UNKNOWN");
    for (const employee of EMPLOYEES) {
      expect(label).toContain(`${employee.name}: ${STATE_LABEL.unknown}`);
    }
  });

  it("drops ambient detail at reduced density", () => {
    const full = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    const fullNodes = full.container.querySelectorAll("*").length;
    full.unmount();

    const reduced = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="reduced" />,
    );
    expect(reduced.container.querySelectorAll("*").length).toBeLessThan(fullNodes);
  });

  it("dims the departments that are not focused", () => {
    const { container } = render(
      <HqStage focusedZone="risk" onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    const risk = container.querySelector('[data-zone="risk"]')!;
    const floor = container.querySelector('[data-zone="floor"]')!;
    expect(risk.getAttribute("opacity")).toBe("1");
    expect(Number(floor.getAttribute("opacity"))).toBeLessThan(1);
  });
});

describe("the cast", () => {
  it("draws a real character for every employee, not a placeholder", () => {
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    // Twelve people on the shared rig: the ten employees plus Maya and Sam.
    expect(container.querySelectorAll(".hq-character")).toHaveLength(
      EMPLOYEES.length + SUPPORT_STAFF.length,
    );
    expect(container.querySelectorAll("[data-employee]")).toHaveLength(EMPLOYEES.length);
    // The HQ-1 capsule is gone.
    expect(container.querySelector(".hq-anchor-body")).toBeNull();
  });

  it("gives each character their own build and pose in the DOM", () => {
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    for (const employee of EMPLOYEES) {
      const node = container.querySelector(`[data-employee="${employee.id}"] .hq-character`)!;
      const character = CHARACTERS[employee.id];
      expect(node.getAttribute("data-body")).toBe(character.bodyType);
      expect(node.getAttribute("data-pose")).toBe(character.defaultPose);
    }
  });

  it("gives each desk its own instrument cluster", () => {
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    const themes = [...container.querySelectorAll("[data-instruments]")].map((node) =>
      node.getAttribute("data-instruments"),
    );
    expect(new Set(themes).size).toBe(EMPLOYEES.length);
  });

  it("renders the shared rig once rather than per character", () => {
    // Ten copies of the chair geometry would be the tell that the rig is not
    // actually shared.
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    expect(container.querySelectorAll("#hq-chair")).toHaveLength(1);
    expect(container.querySelectorAll("#hq-seated-legs")).toHaveLength(1);
  });

  it("marks Rex's terminal as the paper one", () => {
    // The simulation/real-money distinction is the one thing in this room that
    // must never be ambiguous, and it is present from the first drawn frame.
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    expect(container.textContent).toContain("PAPER");
  });

  it("renders no numeric value anywhere in the room", () => {
    // Desk screens are abstract shapes. A digit drawn as decoration would be
    // indistinguishable from a measured one once the adapter lands.
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    const text = [...container.querySelectorAll("text")]
      .map((node) => node.textContent ?? "")
      .join(" ");
    expect(text).not.toMatch(/\d/);
    expect(text).not.toMatch(/[%$]/);
  });
});

describe("portraits", () => {
  it("renders a portrait for every employee with an accessible name", () => {
    for (const employee of EMPLOYEES) {
      const { getByRole, unmount } = render(<Portrait id={employee.id} />);
      expect(getByRole("img").getAttribute("aria-label")).toBe(
        `${employee.name}, ${employee.role}`,
      );
      unmount();
    }
  });

  it("reuses the rig rather than drawing a second illustration", () => {
    const { container } = render(<Portrait id="atlas" />);
    expect(container.querySelector(".hq-character")).not.toBeNull();
    expect(container.querySelector(".hq-character")!.getAttribute("data-body")).toBe(
      CHARACTERS.atlas.bodyType,
    );
  });
});

describe("reduced motion", () => {
  it("keeps motion off until the preference has been read", () => {
    // Rendering with the query reporting `reduce` must never produce a frame
    // with motion enabled — hence the attribute starts off and is raised, not
    // the reverse.
    window.matchMedia = matchMedia(true);
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    expect(container.querySelector(".hq")!.getAttribute("data-hq-motion")).toBe("off");
  });

  it("still carries every operational fact with motion disabled", () => {
    window.matchMedia = matchMedia(true);
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    // The state is in the DOM as text, not conveyed by an animation or a
    // colour. It moved from a visible plate to the accessible name when the
    // composition pass replaced ten floating status boxes with a name and a
    // dot; the requirement — reachable without motion and without hue — is
    // unchanged, and `unknown` in particular must never be able to read as a
    // healthy state.
    for (const employee of EMPLOYEES) {
      const node = container.querySelector(`[data-employee="${employee.id}"]`)!;
      expect(node.getAttribute("data-state"), employee.id).toBe("unknown");
      expect(node.getAttribute("aria-label"), employee.id).toContain(STATE_LABEL.unknown);
    }
  });

  it("exposes a pause switch for a hidden tab", () => {
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    expect(container.querySelector(".hq")!.hasAttribute("data-hq-paused")).toBe(true);
  });
});

describe("small screens", () => {
  it("renders every staffed department as a card, and the rest compactly", () => {
    render(<HqCards onSelectEmployee={noop} />);
    // Departments with operational staff get full cards; the world-expansion
    // spaces compress into one line each in the around-the-office card, so a
    // phone is not scrolled through seven near-empty panels.
    const around = screen.getByTestId("hq-around").textContent!;
    for (const zone of FOCUSABLE_ZONES) {
      const staffed = EMPLOYEES.some((employee) => employee.zone === zone.id);
      if (staffed) expect(screen.getByText(zone.label)).toBeInTheDocument();
      else expect(around).toContain(zone.label);
    }
    for (const employee of EMPLOYEES) {
      expect(screen.getByText(employee.name)).toBeInTheDocument();
    }
    // The household, as text with no state chips: nothing about them is
    // measured, and the card does not pretend otherwise.
    const life = screen.getByTestId("hq-office-life").textContent!;
    for (const npc of SUPPORT_STAFF) expect(life).toContain(npc.name);
    for (const cat of CATS) expect(life).toContain(cat.name);
  });

  it("states no data as text rather than as a colour", () => {
    render(<HqCards onSelectEmployee={noop} />);
    expect(screen.getAllByText(STATE_LABEL.unknown)).toHaveLength(EMPLOYEES.length);
  });

  it("shows a portrait and a personality line per employee", () => {
    const { container } = render(<HqCards onSelectEmployee={noop} />);
    expect(container.querySelectorAll(".hq-portrait")).toHaveLength(EMPLOYEES.length);
    for (const employee of EMPLOYEES) {
      expect(screen.getByText(CHARACTERS[employee.id].personalityLine)).toBeInTheDocument();
    }
  });

  it("claims no operational state on any card", () => {
    const { container } = render(<HqCards onSelectEmployee={noop} />);
    for (const forbidden of ["ONLINE", "HEALTHY", "ACTIVE", "APPROVED", "PROFIT"]) {
      expect(container.textContent).not.toContain(forbidden);
    }
  });
});

describe("bundle isolation", () => {
  const root = path.resolve(__dirname, "../..");

  function sourcesUnder(dir: string): string[] {
    const full = path.join(root, dir);
    if (!fs.existsSync(full)) return [];
    const out: string[] = [];
    for (const entry of fs.readdirSync(full, { withFileTypes: true })) {
      const next = path.join(dir, entry.name);
      if (entry.isDirectory()) out.push(...sourcesUnder(next));
      else if (/\.tsx?$/.test(entry.name) && !entry.name.includes(".test."))
        out.push(next);
    }
    return out;
  }

  /** Resolve an `@/…` specifier to a file on disk, trying the usual endings. */
  function resolve(specifier: string): string | null {
    if (!specifier.startsWith("@/")) return null;
    const base = path.join(root, specifier.slice(2));
    for (const candidate of [
      base,
      `${base}.ts`,
      `${base}.tsx`,
      path.join(base, "index.ts"),
      path.join(base, "index.tsx"),
    ]) {
      if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
    }
    return null;
  }

  /**
   * Every module reachable from an entry point by a **static** import.
   *
   * Static is the whole point: `dynamic(() => import(...))` is what puts HQ in
   * its own chunk, so a dynamic import is explicitly not a reachability edge
   * here. Walking the graph rather than grepping one file catches the realistic
   * regression — nobody imports HQ into `/wallet` directly, they import a shared
   * helper that happens to pull it in three hops away.
   */
  function staticallyReachable(entry: string): Set<string> {
    const seen = new Set<string>();
    const queue = [path.join(root, entry)];
    while (queue.length > 0) {
      const file = queue.pop()!;
      if (seen.has(file) || !fs.existsSync(file)) continue;
      seen.add(file);
      const source = fs.readFileSync(file, "utf8");
      // Strip dynamic imports before scanning, so a lazily loaded module does
      // not count as reachable.
      const stripped = source.replace(/import\s*\(/g, "DYNAMIC_IMPORT(");
      for (const match of stripped.matchAll(/from\s+["'](@\/[^"']+)["']/g)) {
        const next = resolve(match[1]!);
        if (next) queue.push(next);
      }
      for (const match of stripped.matchAll(/^\s*import\s+["'](@\/[^"']+)["']/gm)) {
        const next = resolve(match[1]!);
        if (next) queue.push(next);
      }
    }
    return seen;
  }

  /**
   * HQ must not ship with the screens people trade from. The plan's hardest
   * performance requirement, and the easiest to undo with one convenient
   * import, so it is asserted transitively rather than trusted.
   */
  it.each([
    "app/(dashboard)/wallet/page.tsx",
    "app/(dashboard)/command/page.tsx",
    "app/(dashboard)/real-wallet/page.tsx",
    "app/(dashboard)/layout.tsx",
    "app/layout.tsx",
  ])("keeps HQ out of the module graph of %s", (entry) => {
    const reachable = staticallyReachable(entry);
    const leaked = [...reachable].filter(
      (file) => file.includes("/components/hq/") || file.includes("/lib/hq/"),
    );
    expect(leaked, `${entry} statically reaches HQ`).toEqual([]);
  });

  it("keeps the HQ stylesheet out of every non-HQ module", () => {
    const watched = [
      ...sourcesUnder("app/(dashboard)/wallet"),
      ...sourcesUnder("app/(dashboard)/command"),
      ...sourcesUnder("components/paper"),
      ...sourcesUnder("components/layout"),
    ];
    for (const file of watched) {
      const source = fs.readFileSync(path.join(root, file), "utf8");
      expect(source, `${file} imports HQ styles`).not.toContain("hq.css");
    }
  });

  it("reaches HQ from the HQ route only through a dynamic import", () => {
    // Proves the graph walk above is meaningful rather than vacuously true:
    // the stage must be unreachable statically even from its own page.
    const reachable = staticallyReachable("app/(dashboard)/hq/page.tsx");
    expect([...reachable].some((file) => file.includes("hq-stage"))).toBe(false);
    expect([...reachable].some((file) => file.includes("hq-cards"))).toBe(true);
  });

  it("keeps the HQ stylesheet out of the global layout", () => {
    // `hq.css` in `app/layout.tsx` would ship it to every route and silently
    // undo the isolation the dynamic import buys.
    const layout = fs.readFileSync(path.join(root, "app/layout.tsx"), "utf8");
    expect(layout).not.toContain("hq.css");
  });

  it("keeps the ambient scheduler out of the mobile card path", () => {
    // The card stack is what a phone renders. It may know the household's
    // names — that is data — but it must never pull in the scheduler that
    // animates fourteen residents around a room it is not drawing.
    const reachable = staticallyReachable("components/hq/hq-cards.tsx");
    expect([...reachable].some((file) => file.includes("ambient-scheduler"))).toBe(false);
    expect([...reachable].some((file) => file.includes("use-ambient"))).toBe(false);
    expect([...reachable].some((file) => file.includes("hq-stage"))).toBe(false);
  });

  it("loads the stage through a dynamic import", () => {
    const page = fs.readFileSync(
      path.join(root, "app/(dashboard)/hq/page.tsx"),
      "utf8",
    );
    expect(page).toMatch(/dynamic\(/);
    expect(page).toMatch(/ssr:\s*false/);
  });
});

describe("isolation from trading logic", () => {
  const root = path.resolve(__dirname, "../..");

  it("issues no mutating request and reaches no trading module", () => {
    const files = [
      "components/hq/hq-stage.tsx",
      "components/hq/hq-cards.tsx",
      "app/(dashboard)/hq/page.tsx",
      "lib/hq/employees.ts",
      "lib/hq/zones.ts",
      "lib/hq/geometry.ts",
      "lib/hq/ambient.ts",
      "lib/hq/ambient-scheduler.ts",
      "lib/hq/adapter.ts",
      "lib/hq/events.ts",
      "lib/hq/pipeline.ts",
      "components/hq/use-hq-env.ts",
    ];
    for (const file of files) {
      const source = fs.readFileSync(path.join(root, file), "utf8");
      expect(source, `${file} mutates`).not.toMatch(/method:\s*["'](POST|PUT|PATCH|DELETE)/i);
      // Paper *data* is HQ-4's business — reading the wallet is the whole
      // point. Paper *logic* is not: nothing in HQ may reach the strategy, the
      // eligibility rules, or a mutation. `use-hq-state` is the one module
      // allowed to hold a query at all, and it is checked separately below.
      expect(source, `${file} queries directly`).not.toMatch(/use-paper|usePaper|useQuery/);
    }
  });
});

/* ---------------------------------------------------------------------- */

describe("ambient life", () => {
  it("draws every figure at a pose the rig knows", () => {
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    for (const employee of EMPLOYEES) {
      const anchor = container.querySelector(`[data-employee="${employee.id}"]`)!;
      // At rest everybody is at their own desk in their own default pose. The
      // scheduler is what moves them, and it has not run.
      expect(anchor.getAttribute("data-away")).toBe("false");
      expect(anchor.getAttribute("data-pose")).toBe(CHARACTERS[employee.id].defaultPose);
    }
  });

  it("gives every figure a movable group that starts at their desk", () => {
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    const walkers = container.querySelectorAll("[data-employee] .hq-walker");
    expect(walkers).toHaveLength(EMPLOYEES.length);
    for (const walker of walkers) {
      // No offset until somebody actually walks: a resting room must not carry
      // ten inline transforms the browser has to composite.
      expect((walker as SVGElement).getAttribute("style")).toBeNull();
    }
  });

  it("puts a fixture near every pantry and lounge destination", () => {
    // Otherwise a walk is somebody crossing the room to stand on an empty
    // floor plate, which reads as a rendering bug rather than as a coffee run.
    const destinations = AMBIENT_ROUTINES.flatMap((routine) =>
      routine.frames
        .filter((frame) => frame.pose !== "walking_short" && frame.pose !== "returning_to_desk")
        .filter((frame) => frame.tile && isInBreakRoom(frame.tile))
        .map((f) => f.tile!),
    );
    expect(destinations.length).toBeGreaterThan(0);
    for (const tile of destinations) {
      const near = FURNITURE.some(
        (piece) =>
          Math.abs(piece.tile.col - tile.col) <= 1.3 && Math.abs(piece.tile.row - tile.row) <= 1.3,
      );
      expect(near, `nothing to do at ${tile.col},${tile.row}`).toBe(true);
    }
  });

  it("draws the pantry, the lounge and the space traffic", () => {
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    for (const kind of ["sofa", "fridge", "coffee-machine", "water-cooler", "viewport"]) {
      expect(container.querySelector(`[data-prop="${kind}"]`), kind).not.toBeNull();
    }
    expect(container.querySelector(".hq-traffic")).not.toBeNull();
  });

  it("still says No data while the room is alive", () => {
    // The load-bearing assertion of the whole phase. Motion is decoration; the
    // state chip is the fact, and ambient personality may never touch it.
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    for (const employee of EMPLOYEES) {
      const anchor = container.querySelector(`[data-employee="${employee.id}"]`)!;
      expect(anchor.getAttribute("data-state")).toBe("unknown");
      expect(anchor.getAttribute("aria-label")).toContain(STATE_LABEL.unknown);
    }
    expect(container.textContent).not.toContain(STATE_LABEL.working);
    expect(container.textContent).not.toContain(STATE_LABEL.busy);
  });

  it("puts no routine name or pose into anything a reader can read", () => {
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    const text = [...container.querySelectorAll("text")].map((n) => n.textContent).join(" ");
    for (const routine of AMBIENT_ROUTINES) {
      expect(text).not.toContain(routine.id);
    }
    expect(text).not.toContain("walking");
    expect(text).not.toContain("break");
  });

  it("mounts no ambient motion when the reader asked for reduced motion", () => {
    window.matchMedia = matchMedia(true);
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    const hq = container.querySelector(".hq")!;
    expect(hq.getAttribute("data-hq-motion")).toBe("off");
    // Nobody has been moved off their desk, and nothing has an offset to
    // animate. The scheduler refuses independently; this is the render-side
    // half of the same guarantee.
    for (const walker of container.querySelectorAll(".hq-walker")) {
      expect((walker as SVGElement).getAttribute("style")).toBeNull();
    }
    for (const employee of EMPLOYEES) {
      expect(
        container.querySelector(`[data-employee="${employee.id}"]`)!.getAttribute("data-away"),
      ).toBe("false");
    }
  });
});

describe("the rig's ambient poses", () => {
  const POSES = [
    "seated_working",
    "seated_reviewing",
    "standing",
    "holding_tablet",
    "coffee_idle",
    "walking_short",
    "stretching",
    "looking_at_screen",
    "talking_briefly",
    "returning_to_desk",
    "seated_lounge",
    "seated_talk",
    "tidying",
  ] as const;

  function draw(props: Parameters<typeof Character>[0]) {
    return render(
      <svg>
        <Character {...props} />
      </svg>,
    );
  }

  it.each(POSES)("draws %s", (pose) => {
    const { container } = draw({ character: CHARACTERS.radar, pose });
    const figure = container.querySelector(".hq-character")!;
    expect(figure.getAttribute("data-pose")).toBe(pose);
    // Every pose has arms. A pose that fell through the switch would render a
    // torso with nothing on it, which is subtle enough to ship.
    expect(figure.querySelector(".hq-arms")).not.toBeNull();
  });

  it("seats and stands the same person on request", () => {
    const seated = draw({ character: CHARACTERS.byte, pose: "coffee_idle" });
    expect(seated.container.querySelector('[href="#hq-chair"]')).not.toBeNull();
    seated.unmount();

    // The stage forces this for anyone off their own desk tile. A chair does
    // not follow you to the break room.
    const standing = draw({
      character: CHARACTERS.byte,
      pose: "coffee_idle",
      stance: "standing",
    });
    expect(standing.container.querySelector('[href="#hq-chair"]')).toBeNull();
    expect(standing.container.querySelector('[href="#hq-standing-legs"]')).not.toBeNull();
  });

  it("draws the telescope only for the easter egg", () => {
    const plain = draw({ character: CHARACTERS.radar, pose: "standing" });
    expect(plain.container.querySelector(".hq-telescope")).toBeNull();
    plain.unmount();

    const { container } = draw({
      character: CHARACTERS.radar,
      pose: "standing",
      egg: "telescope",
    });
    expect(container.querySelector(".hq-telescope")).not.toBeNull();
    expect(container.querySelector(".hq-character")!.getAttribute("data-egg")).toBe("telescope");
  });

  it("keeps the eggs out of the portraits", () => {
    // A portrait is an identity, and Byte is not permanently asleep.
    for (const employee of EMPLOYEES) {
      const { container, unmount } = render(<Portrait id={employee.id} />);
      expect(container.querySelector(".hq-character")!.hasAttribute("data-egg")).toBe(false);
      expect(container.querySelector(".hq-telescope")).toBeNull();
      unmount();
    }
  });
});

describe("day and night", () => {
  const cases: Array<[number, string]> = [
    [10, "day"],
    [19, "evening"],
    [2, "night"],
  ];

  afterEach(() => {
    vi.useRealTimers();
  });

  it.each(cases)("renders the room at %i:00 as %s", (hour, expected) => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 0, 15, hour, 30, 0));
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    expect(container.querySelector(".hq")!.getAttribute("data-hq-phase")).toBe(expected);
  });

  it.each(cases)("themes the card stack at %i:00 as %s", (hour, expected) => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 0, 15, hour, 30, 0));
    render(<HqCards onSelectEmployee={noop} />);
    expect(screen.getByTestId("hq-cards").getAttribute("data-hq-phase")).toBe(expected);
  });

  it("stays staffed at night", () => {
    // Crypto runs 24/7. Night is a lighting change and nothing else — the same
    // ten people at the same ten desks.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 0, 15, 3, 0, 0));
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    expect(container.querySelectorAll(".hq-character")).toHaveLength(
      EMPLOYEES.length + SUPPORT_STAFF.length,
    );
    for (const forbidden of ["CLOSED", "OFFLINE", "Closed"]) {
      expect(container.textContent).not.toContain(forbidden);
    }
  });

  it("names exactly three phases", () => {
    expect(DAY_PHASES).toHaveLength(3);
  });
});

describe("mobile", () => {
  it("mounts none of the desktop motion system", () => {
    const { container } = render(<HqCards onSelectEmployee={noop} />);
    // No room, no walkers, no space traffic, no break room — the card stack is
    // a list, and HQ-3 did not quietly turn it into a scene.
    expect(container.querySelector(".hq-room")).toBeNull();
    expect(container.querySelector(".hq-walker")).toBeNull();
    expect(container.querySelector(".hq-traffic")).toBeNull();
    expect(container.querySelector(".hq-break")).toBeNull();
  });

  it("carries the motion and pause switches so the portraits can rest", () => {
    const cards = render(<HqCards onSelectEmployee={noop} />).getByTestId("hq-cards");
    // The same two switches the room uses, so the one stylesheet governs both
    // surfaces and a hidden tab stills the phone as well as the desktop.
    expect(cards.getAttribute("data-hq-motion")).toBe("on");
    expect(cards.hasAttribute("data-hq-paused")).toBe(true);
  });

  it("keeps the portraits still for a reader who asked for reduced motion", () => {
    window.matchMedia = matchMedia(true);
    const cards = render(<HqCards onSelectEmployee={noop} />).getByTestId("hq-cards");
    expect(cards.getAttribute("data-hq-motion")).toBe("off");
  });

  it("keeps every operational fact as text with motion off", () => {
    window.matchMedia = matchMedia(true);
    render(<HqCards onSelectEmployee={noop} />);
    expect(screen.getAllByText(STATE_LABEL.unknown)).toHaveLength(EMPLOYEES.length);
    for (const employee of EMPLOYEES) {
      expect(screen.getByText(employee.name)).toBeInTheDocument();
    }
  });
});

/* ---------------------------------------------------------------------- */

/** A pipeline reading, shaped like the endpoint, for the render tests. */
function pipelineFixture(over: Partial<PipelineHealth["market_enrichment"]> = {}): PipelineHealth {
  return {
    scanner: {
      status: "healthy",
      last_discovery: null,
      minutes_since_last_token: 0.2,
      reconnect_attempts: 0,
      failure_reason: null,
    },
    market_enrichment: {
      status: "healthy",
      last_snapshot: null,
      minutes_since_last_snapshot: 0.2,
      queue_depth: 0,
      dead_lettered: 0,
      priority_queue_depth: 0,
      priority_tokens: 4,
      oldest_priority_wait_seconds: null,
      oldest_normal_wait_seconds: null,
      tracked_freshness_p50_seconds: null,
      tracked_freshness_p95_seconds: null,
      tracked_freshness_worst_seconds: null,
      tracked_stale_count: 0,
      ...over,
    },
    scoring: { status: "healthy", last_score: null, minutes_since_last_score: 1, pending: 0 },
    radar: { status: "healthy", last_cycle: null, minutes_since_last_cycle: 1, tracked_tokens: 4 },
    overall: "healthy",
    environment: "test",
    version: "0.0.0",
    observed_at: new Date().toISOString(),
  };
}

function liveState(over: Partial<PipelineHealth["market_enrichment"]> = {}): HqState {
  const now = Date.now();
  return deriveHqState({
    pipeline: { data: pipelineFixture(over), observedAt: now },
    now,
    stream: "live",
  });
}

describe("real state on the stage", () => {
  it("draws the state the adapter derived, not a hardcoded one", () => {
    const state = liveState();
    const { container } = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        state={state}
      />,
    );
    for (const employee of EMPLOYEES) {
      const node = container.querySelector(`[data-employee="${employee.id}"]`)!;
      expect(node.getAttribute("data-state"), employee.id).toBe(
        state.employees[employee.id].state,
      );
    }
    // Radar's scanner found something a moment ago, so he is working — and
    // the room says so in a channel that is not colour.
    //
    // The stage carries the state as a dot now rather than as a word: ten
    // two-line status plates floating over the cast was the loudest reason
    // the office read as objects on a plan. The rule they protected is
    // intact — `data-state` above, the state word in `aria-label` below, a
    // shape difference per class in CSS, and the full sentence in the
    // employee panel one click away.
    expect(state.employees.radar.state).toBe("working");
    const radar = container.querySelector('[data-employee="radar"]')!;
    expect(radar.getAttribute("aria-label")).toContain(STATE_LABEL.working);
    expect(radar.querySelector(".hq-anchor-dot")).toBeTruthy();
  });

  it("shows the office roll-up on the mission board", () => {
    const { container } = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        state={liveState()}
      />,
    );
    expect(container.textContent).toContain("Office activity");
    expect(container.querySelector(".hq")!.getAttribute("data-hq-activity")).toBe("NORMAL");
  });

  it("carries an alert as text and as an attribute, never as colour alone", () => {
    const state = liveState({ tracked_stale_count: 9, tracked_freshness_worst_seconds: 4000 });
    expect(state.employees.dex.state).toBe("alert");

    const { container } = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        state={state}
      />,
    );
    const dex = container.querySelector('[data-employee="dex"]')!;
    expect(dex.getAttribute("data-state")).toBe("alert");
    // Three non-colour channels, any one of which carries the alert:
    // the attribute, the accessible name, and the state word inside it.
    expect(dex.getAttribute("aria-label")).toContain(STATE_LABEL.alert);
    expect(dex.getAttribute("aria-label")).toContain("stale market data");
    expect(dex.querySelector(".hq-anchor-dot")).toBeTruthy();
  });

  it("still renders no numeric value in the room once state is live", () => {
    // A digit drawn in the scene would be indistinguishable from a measured
    // one. Numbers belong on panels, where they carry a source.
    const { container } = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        state={liveState({ queue_depth: 42, dead_lettered: 7 })}
      />,
    );
    const text = [...container.querySelectorAll("text")].map((n) => n.textContent ?? "").join(" ");
    expect(text).not.toMatch(/\d/);
  });

  it("keeps every operational fact as text with motion disabled", () => {
    // Reduced motion removes the room's movement and none of its meaning.
    window.matchMedia = matchMedia(true);
    const state = liveState({ dead_lettered: 4 });
    const { container } = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        state={state}
      />,
    );
    expect(container.querySelector(".hq")!.getAttribute("data-hq-motion")).toBe("off");
    for (const employee of EMPLOYEES) {
      const node = container.querySelector(`[data-employee="${employee.id}"]`)!;
      // Reachable as text without motion and without hue. The stage shows a
      // dot; the word lives in the accessible name and in the panel.
      expect(node.getAttribute("aria-label"), employee.id).toContain(
        STATE_LABEL[state.employees[employee.id].state],
      );
    }
  });
});

describe("real state on mobile", () => {
  it("prints the normalized state as text on every card", () => {
    const state = liveState({ dead_lettered: 3 });
    const { container } = render(<HqCards onSelectEmployee={noop} state={state} />);
    for (const employee of EMPLOYEES) {
      const card = container.querySelector(`[data-state][aria-label^="${employee.name},"]`)!;
      expect(card.getAttribute("data-state"), employee.id).toBe(
        state.employees[employee.id].state,
      );
      expect(card.getAttribute("aria-label")).toContain(
        STATE_LABEL[state.employees[employee.id].state],
      );
    }
    // Echo's dead-letter alert reaches the phone as words.
    expect(screen.getByText(state.employees.echo.detail)).toBeInTheDocument();
  });

  it("shows the office roll-up without mounting any of the desktop motion system", () => {
    const { container } = render(<HqCards onSelectEmployee={noop} state={liveState()} />);
    expect(screen.getByTestId("hq-activity").textContent).toBe("NORMAL");
    expect(container.querySelector(".hq-walker")).toBeNull();
    expect(container.querySelector(".hq-room")).toBeNull();
  });

  it("says NOT AVAILABLE rather than inventing a state for Atlas", () => {
    const state = liveState();
    render(<HqCards onSelectEmployee={noop} state={state} />);
    expect(state.employees.atlas.state).toBe("unknown");
    expect(screen.getAllByText(STATE_LABEL.unknown).length).toBeGreaterThan(0);
  });
});

describe("adapter isolation", () => {
  const root = path.resolve(__dirname, "../..");

  /**
   * Strip comments before scanning for forbidden code.
   *
   * These modules discuss Real Wallet at length — explaining why HQ does not
   * read it is most of what the comments are for, and several quote the
   * endpoint path. Scanning the prose for the thing the prose is about would
   * make the honest documentation the failure.
   */
  function withoutComments(source: string): string {
    return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  }

  it("is the only module that reads a backend health field", () => {
    // The architecture in one assertion. If a component starts reading
    // `tracked_stale_count` itself, the office gains a second opinion about
    // what stale means and the two will drift.
    const fields = [
      "tracked_stale_count",
      "queue_depth",
      "dead_lettered",
      "minutes_since_last_token",
      "oldest_priority_wait_seconds",
      "market_enrichment",
    ];
    const components = fs
      .readdirSync(path.join(root, "components/hq"))
      .filter((name) => /\.tsx?$/.test(name) && !name.includes(".test."));

    for (const file of components) {
      const source = fs.readFileSync(path.join(root, "components/hq", file), "utf8");
      for (const field of fields) {
        expect(source, `${file} reads ${field} directly`).not.toContain(field);
      }
    }
  });

  it("never lets HQ fetch Real Wallet execution, kill-switch or strategy endpoints", () => {
    // Matched inside string literals rather than anywhere in the file: these
    // modules *discuss* Real Wallet at length, because explaining why HQ does
    // not read most of it is most of the reason the comments exist. What must
    // not appear is a request path.
    //
    // `real-wallet-safety` is deliberately absent from this list as of HQ-5:
    // it is the one read-only audit endpoint the brief explicitly sanctions
    // for Atlas's per-token stage (§7), and it cannot trigger a quote, an
    // order, or a wallet action — its own backend docstring says so. The next
    // test asserts that exception stays exactly that narrow.
    const files = [
      "lib/hq/adapter.ts",
      "lib/hq/events.ts",
      "components/hq/use-hq-state.ts",
      "components/hq/hq-stage.tsx",
      "components/hq/hq-cards.tsx",
    ];
    const forbiddenPath = /["'`][^"'`]*\/(real-wallet\/|kill-switch)/;
    for (const file of files) {
      const source = withoutComments(fs.readFileSync(path.join(root, file), "utf8"));
      expect(source, `${file} mutates`).not.toMatch(/method:\s*["'](POST|PUT|PATCH|DELETE)/i);
      expect(source, `${file} fetches a real-wallet execution path`).not.toMatch(forbiddenPath);
      expect(source, `${file} imports paper strategy code`).not.toMatch(
        /from\s+["'][^"']*(strategy|eligibility)/,
      );
    }
  });

  it("scopes the one Real Wallet read to the audit-only safety evaluations path", () => {
    const source = withoutComments(
      fs.readFileSync(path.join(root, "lib/hq/pipeline.ts"), "utf8"),
    );
    // Every real-wallet-flavoured string in this file must be one of two
    // read-only audit paths. A third — anything under /real-wallet/ itself,
    // a kill-switch control, a dry-run trigger — would be the exception
    // quietly growing into something the brief did not authorise.
    //
    // `execution-posture` was added for the Execution Vault. It is a GET that
    // reports whether execution is possible and returns nothing that would
    // help anyone make it happen: no balance, no key, no signer or transport
    // detail. The admin-only `/real-wallet/status` read stays out of HQ.
    const realWalletStrings = [...source.matchAll(/["'`]([^"'`]*real-wallet[^"'`]*)["'`]/g)].map(
      (match) => match[1],
    );
    expect(realWalletStrings.length).toBeGreaterThan(0);
    for (const value of realWalletStrings) {
      expect(value, `unexpected real-wallet path: ${value}`).toMatch(
        /^\/real-wallet-safety\/(evaluations\/|execution-posture$)/,
      );
    }
    expect(source).not.toMatch(/method:\s*["'](POST|PUT|PATCH|DELETE)/i);
  });

  it("mounts exactly the sources it needs and no more", () => {
    // A small number of shared queries feeding one adapter, rather than
    // thirteen employees each polling for themselves. Four are the app's
    // existing hooks, so HQ shares their cache entries instead of doubling the
    // request rate on the slowest endpoints in the API. The four HQ-owned ones
    // — pipeline health, the token-security summary, the execution posture and
    // the operations surface — exist because nothing else in the app asks for
    // them.
    //
    // Raised from seven to eight when the operations surface shipped. That one
    // request feeds three employees, the Mission Board's infrastructure rows,
    // the incident panel and the autonomous activity trail, because the
    // endpoint aggregates all of it server-side — which is the shape this cap
    // exists to encourage. The next addition should have to argue as well.
    //
    // The cap is the point: it is what stops a future panel from quietly
    // adding a fetch per employee. Raising it should require reading this.
    const source = fs.readFileSync(path.join(root, "components/hq/use-hq-state.ts"), "utf8");
    const queries = source.match(/useQuery\(|usePaper\w+\(|useRadar\w+\(/g) ?? [];
    expect(queries.length).toBeLessThanOrEqual(8);
    expect(source).toContain("usePaperWallet");
    expect(source).toContain("useRadarPerformance");
  });
});

/* ---------------------------------------------------------------------- */

describe("the furnished office", () => {
  it("never puts furniture where somebody works or walks", () => {
    // Twenty-five props against ten desks and twelve authored routes. Checking
    // this by eye survives exactly one floor-plan change; the failure mode is
    // a plant standing in the middle of Byte's route to the coffee machine and
    // a character walking straight through it.
    const waypoints = new Set(
      AMBIENT_ROUTINES.flatMap((routine) => [
        ...routine.frames,
        ...(routine.cast ?? []).flatMap((member) => member.frames),
      ])
        .map((frame) => frame.tile)
        .filter(Boolean)
        .map((tile) => `${tile!.col},${tile!.row}`),
    );

    for (const prop of FURNITURE.filter((piece) => !piece.sittable)) {
      const key = `${prop.tile.col},${prop.tile.row}`;
      expect(waypoints.has(key), `${prop.kind} blocks a walk route at ${key}`).toBe(false);
      for (const employee of EMPLOYEES) {
        expect(
          employee.desk.col === prop.tile.col && employee.desk.row === prop.tile.row,
          `${prop.kind} stands on ${employee.id}'s desk`,
        ).toBe(false);
      }
    }
  });

  it("gives every department its own furniture, not one shared set", () => {
    // Hide the labels and the rooms still have to say what they are. A library
    // in the Performance Lab, a server rack in Ops, case files in Risk.
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    const kinds = [...container.querySelectorAll("[data-prop]")].map((n) =>
      n.getAttribute("data-prop"),
    );
    expect(new Set(kinds).size).toBeGreaterThanOrEqual(8);
    for (const required of ["bookshelf", "server-rack", "printer", "cabinet", "whiteboard"]) {
      expect(kinds, `no ${required} in the office`).toContain(required);
    }
  });

  it("draws a face on every member of staff, support included", () => {
    // The change that turned the cast from figures into people — and the
    // support staff get the same care as the core ten, which was the brief's
    // own rule about them.
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    const people = EMPLOYEES.length + SUPPORT_STAFF.length;
    expect(container.querySelectorAll(".hq-room .hq-face")).toHaveLength(people);
    expect(container.querySelectorAll(".hq-room .hq-hand").length).toBeGreaterThanOrEqual(
      people * 2,
    );
  });

  it("keeps the room free of status colour used as decoration", () => {
    // Green and amber mean something in this product. The reference's office
    // is full of bright green bins and plants; only one of those survived the
    // port, and it is the plants.
    const css = fs.readFileSync(path.resolve(__dirname, "../../styles/hq.css"), "utf8");
    const propBlock = css.slice(css.indexOf("/* ---------- office props"), css.indexOf("/* ---------- wall decoration"));
    for (const forbidden of ["--color-up", "--color-warn", "--color-down", "--hq-status"]) {
      expect(propBlock, `office props reference ${forbidden}`).not.toContain(forbidden);
    }
  });

  it("mounts the mission board and seals the vault", () => {
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    expect(container.querySelector(".hq-mission-board")).not.toBeNull();
    expect(container.textContent).toContain("MEMESCOPE MISSION BOARD");

    const vault = container.querySelector(".hq-vault-door")!;
    expect(vault).not.toBeNull();
    expect(vault.textContent).toContain("SEALED");
    // The vault is a drawing. Nothing in it is interactive, and nothing in it
    // can start a transfer.
    expect(vault.querySelector("button")).toBeNull();
    expect(vault.getAttribute("aria-hidden")).toBe("true");
  });
});

/* ---------------------------------------------------------------------- */

describe("the expanded world on the stage", () => {
  function renderStage(frames?: React.ComponentProps<typeof HqStage>["frames"]) {
    return render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        frames={frames}
      />,
    );
  }

  it("renders the support staff and both cats as focusable residents", () => {
    const { container } = renderStage();
    for (const npc of SUPPORT_STAFF) {
      const node = container.querySelector(`[data-support="${npc.id}"]`)!;
      expect(node, npc.id).not.toBeNull();
      expect(node.getAttribute("tabindex")).toBe("0");
      const label = node.getAttribute("aria-label")!;
      expect(label).toContain(npc.name);
      expect(label).toContain(npc.role);
      // No operational state word: support staff are not measured, and their
      // label must not pretend somebody tried.
      expect(label).not.toContain("No data");
    }
    for (const cat of CATS) {
      const node = container.querySelector(`[data-cat="${cat.id}"][role="button"]`)!;
      expect(node, cat.id).not.toBeNull();
      expect(node.getAttribute("aria-label")).toContain("office cat");
    }
  });

  it("sits a lounging employee on real furniture with no conjured chair", () => {
    const { container } = renderStage({
      sage: { pose: "seated_lounge", tile: { col: 9.25, row: 11.05 }, hold: 1000 },
    });
    const sage = container.querySelector('[data-employee="sage"] .hq-character')!;
    expect(sage.getAttribute("data-stance")).toBe("lounge");
    // Lounge legs, and no office chair drawn under them — the sofa at the
    // destination is the seat.
    expect(sage.querySelector('[href="#hq-lounge-legs"]')).not.toBeNull();
    expect(sage.querySelector('[href="#hq-chair"]')).toBeNull();
  });

  it("orders walkers against furniture by position, both ways", () => {
    // The deferred depth-sorting issue, now load-bearing: byte standing north
    // of the server rack paints behind it; byte standing south paints in
    // front. DOM order inside one SVG is paint order, so the assertion is
    // exactly the pixels' behaviour.
    const rack = { col: 10, row: 8 };
    const behind = renderStage({
      byte: { pose: "standing", tile: { col: rack.col, row: rack.row - 1 }, hold: 1000 },
    });
    const orderOf = (container: HTMLElement) => {
      const nodes = [...container.querySelectorAll("[data-prop='server-rack'], [data-employee='byte']")];
      return nodes.map((node) =>
        node.hasAttribute("data-prop") ? "rack" : "byte",
      );
    };
    expect(orderOf(behind.container)).toEqual(["byte", "rack"]);
    behind.unmount();

    const inFront = renderStage({
      byte: { pose: "standing", tile: { col: rack.col, row: rack.row + 1 }, hold: 1000 },
    });
    expect(orderOf(inFront.container)).toEqual(["rack", "byte"]);
  });

  it("draws the conference room, the deck and the planet", () => {
    const { container } = renderStage();
    expect(container.querySelector(".hq-conference-glass")).not.toBeNull();
    expect(container.querySelector(".hq-deck-edge")).not.toBeNull();
    expect(container.querySelector(".hq-void-planet")).not.toBeNull();
    expect(container.querySelector('[data-prop="conference-table"]')).not.toBeNull();
    expect(container.querySelectorAll('[data-prop="conf-chair"]')).toHaveLength(6);
    expect(container.querySelector('[data-prop="restroom-doors"]')).not.toBeNull();
    expect(container.querySelector('[data-prop="reception-counter"]')).not.toBeNull();
  });

  it("carries Maya's trolley only while a frame says so", () => {
    const still = renderStage();
    expect(still.container.querySelector(".hq-trolley")).toBeNull();
    still.unmount();

    const cleaning = renderStage({
      maya: { pose: "walking_short", tile: { col: 5, row: 6 }, hold: 1000, carry: "trolley" },
    });
    expect(cleaning.container.querySelector(".hq-trolley")).not.toBeNull();
  });

});
