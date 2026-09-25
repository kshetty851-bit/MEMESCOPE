import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render as rtlRender, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-client", async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  api: { get: (...a: unknown[]) => get(...a) },
}));

import { DockCrew, LoginCrew } from "./login-crew";

/** The crew's news strip reads through react-query, so every render gets a client. */
function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return rtlRender(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

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

  function fakeAudio() {
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
    return tones;
  }

  it("pops when the crew talks, on a timer too (asked for back, 2026-09-25)", () => {
    const tones = fakeAudio();
    vi.useFakeTimers();
    render(<DockCrew pathname="/karthik-lab" />);
    fireEvent.pointerDown(window);                 // sound unlocked, as in a browser
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    expect(tones).toHaveBeenCalled();
  });

  it("stays silent when muted", () => {
    window.localStorage.setItem("memescope.loginCrewSound", "off");
    const tones = fakeAudio();
    vi.useFakeTimers();
    const { container } = render(<DockCrew pathname="/karthik-lab" />);
    fireEvent.pointerDown(window);
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    fireEvent.click(container.querySelector(".dock-crew__mate--tiger img")!);
    // Muted means the master gain is zero; nothing is scheduled at all when
    // the say() path sees the switch off.
    expect(tones).not.toHaveBeenCalled();
  });
});

describe("the panda's news desk in the sidebar", () => {
  afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
    get.mockReset();
  });

  it("shows the latest Solana headline and reads it out short", async () => {
    get.mockResolvedValue({ items: [
      { title: "Solana Foundation hires two executives to drive global payments adoption",
        source: "FF News", url: "https://example.com/a", published_at: new Date().toISOString() },
    ] });
    const { container } = render(<DockCrew pathname="/karthik-lab" placement="rail" />);
    expect(await screen.findByRole("link", { name: /Solana Foundation hires/ })).toHaveAttribute(
      "href", "https://example.com/a");
    expect(screen.getByText(/FF News/)).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/news/solana", expect.anything());
    // Only the panda lives in the rail's gap now.
    expect(container.querySelectorAll(".dock-crew__mate")).toHaveLength(1);
    fireEvent.click(container.querySelector(".dock-crew__mate--panda img")!);
    expect(container.querySelector(".login-crew__bubble")?.textContent).toMatch(/^📰 Solana Foundation hires/);
  });
});
