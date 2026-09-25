import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FrogVoice } from "./frog-voice";

function stubSpeech() {
  const said: string[] = [];
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      text: string;
      pitch = 1;
      rate = 1;
      volume = 1;
      voice = null;
      constructor(text: string) {
        this.text = text;
      }
    },
  );
  vi.stubGlobal("speechSynthesis", {
    speaking: false,
    cancel: vi.fn(),
    getVoices: () => [],
    speak: (u: { text: string }) => said.push(u.text),
  });
  return said;
}

describe("the frog calls the launch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("says access approved to Karthik, counts down, and cheers", () => {
    const said = stubSpeech();
    const { rerender, container } = render(<FrogVoice phase="approved" count={null} />);
    expect(container.querySelector(".frog-bubble")).toHaveTextContent("Access approved, Captain Karthik!");
    for (const n of [5, 4, 3, 2, 1]) rerender(<FrogVoice phase="countdown" count={n} />);
    expect(container.querySelector(".frog-bubble")).toHaveTextContent("1!");
    rerender(<FrogVoice phase="ignition" count={null} />);
    expect(container.querySelector(".frog-bubble")).toHaveTextContent("WOO-HOO-HOO!");
    expect(said).toEqual([
      "Access approved, Captain Karthik! Launching in…",
      "five!", "four!", "three!", "two!", "one!",
      "Woo-hoo-hoo!",
    ]);
  });

  it("stays silent when the crew is muted", () => {
    const said = stubSpeech();
    window.localStorage.setItem("memescope.loginCrewSound", "off");
    render(<FrogVoice phase="approved" count={null} />);
    expect(said).toEqual([]);
  });

  it("says nothing before a code is accepted", () => {
    const said = stubSpeech();
    const { container } = render(<FrogVoice phase="idle" count={null} />);
    expect(said).toEqual([]);
    expect(container.querySelector(".frog-bubble")).toBeNull();
  });
});

describe("the frog's voice", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("is a male voice when the browser has one", () => {
    const lines: { voice: { name: string } | null; pitch: number }[] = [];
    vi.stubGlobal("SpeechSynthesisUtterance", class { voice = null; pitch = 1; rate = 1; volume = 1; constructor(public text: string) {} });
    vi.stubGlobal("speechSynthesis", {
      speaking: false,
      cancel: vi.fn(),
      getVoices: () => [
        { name: "Samantha", lang: "en-US" },
        { name: "Daniel", lang: "en-GB" },
      ],
      speak: (u: { voice: { name: string } | null; pitch: number }) => lines.push(u),
    });
    render(<FrogVoice phase="approved" count={null} />);
    expect(lines[0]?.voice?.name).toBe("Daniel");
  });
});
