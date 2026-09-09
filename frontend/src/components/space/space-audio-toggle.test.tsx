import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The control appears twice — launch screen and dashboard topbar — and the
 * reason `use-space-audio` holds the instance at module scope is that those
 * two must agree and must not each build their own AudioContext. That is what
 * is tested here; the sound itself is measured in the browser, not in jsdom,
 * which has no Web Audio at all.
 */

const started = vi.fn();
const stopped = vi.fn();
const created = vi.fn();

vi.mock("@/lib/space-audio", () => ({
  audioContextCtor: () => class {},
  createSpaceAudio: () => {
    created();
    return {
      start: async () => void started(),
      stop: () => void stopped(),
      dispose: () => {},
    };
  },
}));

const { SpaceAudioToggle } = await import("./space-audio-toggle");

function buttons() {
  return screen.getAllByRole("button", { name: /ambient soundtrack/i });
}

describe("SpaceAudioToggle", () => {
  beforeEach(() => {
    started.mockClear();
    stopped.mockClear();
    created.mockClear();
  });

  it("starts off, because a browser will not play before a gesture", () => {
    render(<SpaceAudioToggle />);
    expect(buttons()[0]).toHaveAttribute("aria-pressed", "false");
    expect(created).not.toHaveBeenCalled();
    expect(started).not.toHaveBeenCalled();
  });

  it("two copies share one instance and agree with each other", async () => {
    render(
      <>
        <SpaceAudioToggle />
        <SpaceAudioToggle label={false} />
      </>,
    );

    // `toggle` awaits `start()`, so the state settles a microtask after the
    // click — the act() wrapper is what flushes it.
    const click = async (el: HTMLElement) => {
      await act(async () => {
        fireEvent.click(el);
      });
    };

    const [launch, topbar] = buttons();
    await click(launch);

    // Both report on, and only ONE audio graph was ever built.
    expect(launch).toHaveAttribute("aria-pressed", "true");
    expect(topbar).toHaveAttribute("aria-pressed", "true");
    expect(created).toHaveBeenCalledTimes(1);
    expect(started).toHaveBeenCalledTimes(1);

    // Turning it off from the OTHER copy turns off the same sound.
    await click(topbar);
    expect(stopped).toHaveBeenCalledTimes(1);
    expect(launch).toHaveAttribute("aria-pressed", "false");
    expect(topbar).toHaveAttribute("aria-pressed", "false");

    // Re-starting reuses the graph rather than building a second one.
    await click(topbar);
    expect(created).toHaveBeenCalledTimes(1);
  });
});
