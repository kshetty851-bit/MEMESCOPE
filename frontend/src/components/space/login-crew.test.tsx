import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DockCrew, LoginCrew } from "./login-crew";

describe("the crew at the airlock", () => {
  afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it("looks away while a password is typed, and is decorative throughout", () => {
    const { container } = render(
      <>
        <LoginCrew />
        <input type="password" aria-label="Password" />
      </>,
    );
    const crew = container.querySelector(".login-crew")!;
    expect(crew).toHaveAttribute("aria-hidden");

    fireEvent.focusIn(screen.getByLabelText("Password"));
    expect(crew).toHaveAttribute("data-mood", "shy");
    expect(container.querySelector(".login-crew__bubble")).toHaveTextContent("I'm not looking!");

    fireEvent.focusOut(screen.getByLabelText("Password"));
    expect(crew).not.toHaveAttribute("data-mood");
  });

  it("says something to the visitor on its own", () => {
    vi.useFakeTimers();
    const { container } = render(<LoginCrew />);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(container.querySelector(".login-crew__bubble")).toHaveTextContent("Welcome back");
  });

  it("remembers the mute choice", () => {
    render(<LoginCrew />);
    const button = screen.getByRole("button", { name: /mute the crew/i });
    expect(button).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: /sound on/i })).toHaveAttribute("aria-pressed", "false");
    expect(window.localStorage.getItem("memescope.loginCrewSound")).toBe("off");
  });
});

describe("the crew after sign-in", () => {
  afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it("says hello for the page, talks when tapped, and can be tucked away", () => {
    vi.useFakeTimers();
    const { container } = render(<DockCrew pathname="/karthik-lab" />);
    act(() => {
      vi.advanceTimersByTime(1300);
    });
    expect(container.querySelector(".login-crew__bubble")).toHaveTextContent("Welcome to your lab, captain!");

    fireEvent.click(container.querySelector(".dock-crew__mate--tiger img")!);
    expect(container.querySelector(".dock-crew__mate--tiger .login-crew__bubble")).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Hide the crew" }));
    expect(container.querySelector(".dock-crew")).toBeNull();
    expect(window.localStorage.getItem("memescope.crewDock")).toBe("hidden");
    fireEvent.click(screen.getByRole("button", { name: "Bring the crew back" }));
    expect(container.querySelector(".dock-crew")).not.toBeNull();
  });
});

describe("sound", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("never plays on a timer, only when the visitor does something", () => {
    // A fake Web Audio that counts every tone started.
    const tones = vi.fn();
    const node = () => ({
      connect: () => node(),
      gain: { value: 0, setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn(), setTargetAtTime: vi.fn() },
      frequency: { value: 0, setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
      Q: { value: 0 },
      start: tones,
      stop: vi.fn(),
    });
    vi.stubGlobal("AudioContext", class {
      currentTime = 0;
      sampleRate = 8000;
      destination = {};
      createGain = node;
      createOscillator = node;
      createBiquadFilter = node;
      createBufferSource = node;
      createBuffer = () => ({ getChannelData: () => new Float32Array(8) });
      resume = vi.fn();
      close = vi.fn();
    });
    vi.useFakeTimers();
    const { container } = render(<DockCrew pathname="/karthik-lab" />);
    fireEvent.pointerDown(window);                 // sound unlocked, as in a browser
    act(() => {
      vi.advanceTimersByTime(55_000);              // ~a minute of chatter, mid-bubble
    });
    expect(container.querySelector(".login-crew__bubble")).not.toBeNull();
    expect(tones).not.toHaveBeenCalled();

    fireEvent.click(container.querySelector(".dock-crew__mate--tiger img")!);
    expect(tones).toHaveBeenCalled();
  });
});
