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

  it("says access approved, counts down, and cheers — in a squeaky voice", () => {
    const said = stubSpeech();
    const { rerender, container } = render(<FrogVoice phase="approved" count={null} />);
    expect(container.querySelector(".frog-bubble")).toHaveTextContent("Access approved! Launching in…");
    for (const n of [5, 4, 3, 2, 1]) rerender(<FrogVoice phase="countdown" count={n} />);
    expect(container.querySelector(".frog-bubble")).toHaveTextContent("1!");
    rerender(<FrogVoice phase="ignition" count={null} />);
    expect(container.querySelector(".frog-bubble")).toHaveTextContent("WOO-HOO!");
    expect(said).toEqual(["Access approved! Launching in…", "five", "four", "three", "two", "one", "Woo-hoo!"]);
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
