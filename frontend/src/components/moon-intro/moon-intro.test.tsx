import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MoonIntro, { SEEN_KEY, SOUND_KEY } from "./moon-intro";
import { MOMENTS, REDUCED_TIMELINE, SHORT_TIMELINE, TIMELINE, phaseStart, totalSeconds, type Frame } from "./timeline";

const scene = vi.hoisted(() => ({ frames: [] as Frame[], destroyed: 0 }));
const board = vi.hoisted(() => ({ played: [] as string[], muted: [] as boolean[], unlocks: 0, throttle: [] as number[] }));

vi.mock("./space-scene", () => ({
  createSpaceScene: () => ({
    update: (f: Frame) => scene.frames.push({ ...f }),
    resize() {},
    destroy: () => void scene.destroyed++,
    quality: () => "high",
  }),
}));
vi.mock("./soundboard", () => ({
  createSoundboard: () => ({
    play: (n: string) => board.played.push(n),
    setThrottle: (l: number) => board.throttle.push(l),
    setMuted: (m: boolean) => board.muted.push(m),
    unlock: () => void board.unlocks++,
    destroy() {},
  }),
}));

let now = 0;
let queue: FrameRequestCallback[] = [];
let reduced = false;

/** Advance simulated time by `seconds`, one 50ms frame at a time. */
function step(seconds: number) {
  for (let i = 0; i < Math.round(seconds / 0.05); i++) {
    now += 50;
    const run = queue;
    queue = [];
    act(() => run.forEach((cb) => cb(now)));
  }
}
const t = () => scene.frames.at(-1)?.t ?? 0;

beforeEach(() => {
  now = 0;
  queue = [];
  reduced = false;
  scene.frames = [];
  scene.destroyed = 0;
  Object.assign(board, { played: [], muted: [], unlocks: 0, throttle: [] });
  sessionStorage.clear();
  localStorage.clear();
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => queue.push(cb));
  vi.stubGlobal("cancelAnimationFrame", () => (queue = []));
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: reduced && q.includes("reduce"),
    addEventListener() {},
    removeEventListener() {},
  }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const mount = (onComplete = vi.fn()) => {
  const view = render(<MoonIntro onComplete={onComplete} />);
  const root = view.container.querySelector<HTMLElement>(".mi-root")!;
  return { ...view, root, onComplete };
};

describe("MoonIntro", () => {
  it("plays the full cut on a first visit and marks the session", () => {
    const { root, onComplete } = mount();
    expect(root).toHaveAttribute("data-mode", "full");
    expect(root).toHaveAttribute("aria-label", "Landing sequence");
    expect(sessionStorage.getItem(SEEN_KEY)).toBe("1");
    step(totalSeconds(TIMELINE) + 0.2);
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(new Set(scene.frames.map((f) => f.phase))).toEqual(
      new Set(["seatbelt", "cockpit", "ignition", "warp", "approach", "landing", "reveal", "done"]),
    );
  });

  it("plays the short cut once the session has seen it", () => {
    sessionStorage.setItem(SEEN_KEY, "1");
    const { root, onComplete } = mount();
    expect(root).toHaveAttribute("data-mode", "short");
    step(totalSeconds(SHORT_TIMELINE) + 0.1);
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(scene.frames.some((f) => f.phase === "warp")).toBe(false);
  });

  it("plays the reduced cut, still and silent, under reduced motion", () => {
    reduced = true;
    const { root, onComplete, container } = mount();
    expect(root).toHaveAttribute("data-mode", "reduced");
    step(0.5);
    expect(container.querySelector<HTMLElement>(".mi-shake")!.style.transform).toBe("");
    step(totalSeconds(REDUCED_TIMELINE));
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(board.played).toEqual([]);
    expect(board.throttle).toEqual([]);
  });

  it("advances phases and passes moments in order", () => {
    const { root, container } = mount();
    step(0.5);
    expect(root.dataset.phase).toBe("seatbelt");
    expect(screen.queryByText("SECURED ✓")).toBeNull();
    step(0.6); // past seatbelt.secured at 0.96s
    expect(screen.getByText("SECURED ✓")).toBeInTheDocument();
    step(1.5); // into cockpit's switches
    expect(root.dataset.phase).toBe("cockpit");
    expect(container.querySelectorAll(".mi-switch[data-on]").length).toBeGreaterThan(0);
    expect(board.played.slice(0, 2)).toEqual(["click", "switch"]);
    step(4); // through ignition + warp
    expect(board.played).toEqual(expect.arrayContaining(["beep", "whoosh", "static"]));
    expect(board.played.indexOf("beep")).toBeLessThan(board.played.indexOf("whoosh"));
    expect(Math.max(...board.throttle)).toBeGreaterThan(0.9);
  });

  it("skips to the reveal on Escape and completes within 0.7s", () => {
    const { onComplete, root } = mount();
    step(3);
    const before = board.played.length;
    fireEvent.keyDown(window, { key: "Escape" });
    step(0.05);
    expect(root.dataset.phase).toBe("reveal");
    const jumped = t();
    const revealStart = phaseStart(TIMELINE, "reveal")!;
    expect(jumped).toBeGreaterThanOrEqual(revealStart + MOMENTS.reveal.dolly * 0.8);
    step(0.7);
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(scene.frames.find((f) => f.phase === "done")!.t - jumped).toBeLessThanOrEqual(0.7);
    // Nothing jumped over made a sound: no alarm, no thud, no warp.
    expect(board.played.slice(before)).toEqual([]);
    step(1);
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("skips on a click anywhere and on the skip button, and ignores skips in the reveal", () => {
    const { root, onComplete } = mount();
    step(0.3);
    fireEvent.click(screen.getByRole("button", { name: /skip to moon/i }));
    step(0.05);
    expect(root.dataset.phase).toBe("reveal");
    const at = t();
    fireEvent.click(root);
    step(0.05);
    expect(t()).toBeCloseTo(at + 0.05, 5);
    step(0.7);
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("is muted by default and persists the sound toggle", () => {
    mount();
    expect(board.muted.at(-1)).toBe(true);
    const toggle = screen.getByRole("button", { name: "Sound off" });
    fireEvent.click(toggle);
    expect(localStorage.getItem(SOUND_KEY)).toBe("on");
    expect(board.unlocks).toBe(1);
    expect(board.muted.at(-1)).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Sound on" }));
    expect(localStorage.getItem(SOUND_KEY)).toBe("off");
    expect(board.muted.at(-1)).toBe(true);
  });

  it("waits for a gesture before unlocking a stored 'on'", () => {
    localStorage.setItem(SOUND_KEY, "on");
    mount();
    expect(board.unlocks).toBe(0);
    fireEvent.pointerDown(window);
    expect(board.unlocks).toBe(1);
  });

  it("focuses the skip button and cleans up on unmount", () => {
    const { unmount } = mount();
    expect(document.activeElement).toHaveTextContent(/skip to moon/i);
    unmount();
    expect(scene.destroyed).toBe(1);
  });
});
