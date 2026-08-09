import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TokenAvatar } from "@/components/brand/token-avatar";

describe("TokenAvatar", () => {
  it("uses the token image when one is available", () => {
    render(<TokenAvatar mint="MintA" imageUrl="https://cdn.test/a.png" />);

    const image = screen.getByRole("presentation", { hidden: true });
    expect(image).toHaveAttribute("src", "https://cdn.test/a.png");
  });

  it("falls back deterministically when no image exists", () => {
    const { container } = render(<TokenAvatar mint="MintA" />);

    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("does not carry a failed image state from one mint to the next", () => {
    const { rerender } = render(
      <TokenAvatar mint="MintA" imageUrl="https://cdn.test/broken.png" />,
    );

    fireEvent.error(screen.getByRole("presentation", { hidden: true }));
    expect(screen.queryByRole("presentation", { hidden: true })).not.toBeInTheDocument();

    rerender(<TokenAvatar mint="MintB" imageUrl="https://cdn.test/b.png" />);

    const image = screen.getByRole("presentation", { hidden: true });
    expect(image).toHaveAttribute("src", "https://cdn.test/b.png");
  });
});
