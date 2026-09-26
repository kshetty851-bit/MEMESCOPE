import { act, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CardPeeker, FloatingCrew, PerchedCrew } from "./space-crew";

describe("the space crew", () => {
  it("seats three animals on the wordmark, all decorative", () => {
    const { container } = render(<PerchedCrew />);
    const imgs = [...container.querySelectorAll("img")];
    expect(imgs.map((i) => i.getAttribute("src"))).toEqual([
      "/crew/hippo.webp", "/crew/panda.webp", "/crew/penguin.webp",
    ]);
    // Screen readers hear the wordmark's own name, not three pictures.
    for (const img of imgs) {
      expect(img).toHaveAttribute("alt", "");
      expect(img).toHaveAttribute("aria-hidden", "true");
    }
  });

  it("leaves when the hero scrolls away and comes back with it", async () => {
    const { container } = render(<FloatingCrew />);
    const front = container.querySelector(".crew-sky--front")!;
    expect(front).not.toHaveAttribute("data-away");

    await act(async () => {
      Object.defineProperty(window, "scrollY", { value: window.innerHeight, configurable: true });
      window.dispatchEvent(new Event("scroll"));
      await new Promise((r) => requestAnimationFrame(() => r(null)));
    });
    expect(front).toHaveAttribute("data-away");

    await act(async () => {
      Object.defineProperty(window, "scrollY", { value: 0, configurable: true });
      window.dispatchEvent(new Event("scroll"));
      await new Promise((r) => requestAnimationFrame(() => r(null)));
    });
    expect(front).not.toHaveAttribute("data-away");
  });

  it("puts a peeker on the side it is asked for", () => {
    const { container } = render(<CardPeeker src="/crew/lion.webp" side="left" />);
    expect(container.querySelector(".crew-peek--left img")).toHaveAttribute("src", "/crew/lion.webp");
  });
});
