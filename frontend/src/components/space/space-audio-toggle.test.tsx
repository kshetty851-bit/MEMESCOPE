import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The control appears twice — launch screen and dashboard topbar — and the
 * reason `use-space-audio` holds the instance at module scope is that those
 * two must agree and must not each build their own player. That is what is
 * tested here; the player itself is covered in `lib/space-audio.test.ts`.
 */

const started = vi.fn();
const stopped = vi.fn();
const created = vi.fn();
let events: { onPlay?: () => void; onPause?: () => void } = {};

vi.mock("@/lib/space-audio", () => ({
  audioSupported: () => true,
  createSpaceAudio: (_src?: string, e: typeof events = {}) => {
    events = e;
    created();
    return {
      start: async () => void started(),
      stop: () => void stopped(),
      dispose: () => {},
      position: () => null,
    };
  },
}));

const { SpaceAudioToggle } = await import("./space-audio-toggle");

function buttons() {
  return screen.getAllByRole("button", { name: /soundtrack/i });
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

    // Both report on, and only ONE player was ever built.
    expect(launch).toHaveAttribute("aria-pressed", "true");
    expect(topbar).toHaveAttribute("aria-pressed", "true");
    expect(created).toHaveBeenCalledTimes(1);
    expect(started).toHaveBeenCalledTimes(1);

    // Turning it off from the OTHER copy turns off the same sound.
    await click(topbar);
    expect(stopped).toHaveBeenCalledTimes(1);
    expect(launch).toHaveAttribute("aria-pressed", "false");
    expect(topbar).toHaveAttribute("aria-pressed", "false");

    // Re-starting reuses the player rather than building a second one.
    await click(topbar);
    expect(created).toHaveBeenCalledTimes(1);
  });

  it("follows the track when something else pauses or resumes it", async () => {
    // A phone call, unplugged headphones, the keyboard's media key. The button
    // must say what can actually be heard, or the HQ dance floor dances on to
    // silence — which is how this was found.
    render(<SpaceAudioToggle />);
    const [button] = buttons();
    // Leave it on from wherever the previous test left it.
    if (button!.getAttribute("aria-pressed") !== "true") {
      await act(async () => {
        fireEvent.click(button!);
      });
    }
    expect(button).toHaveAttribute("aria-pressed", "true");

    await act(async () => events.onPause?.());
    expect(button).toHaveAttribute("aria-pressed", "false");

    await act(async () => events.onPlay?.());
    expect(button).toHaveAttribute("aria-pressed", "true");
  });
});
