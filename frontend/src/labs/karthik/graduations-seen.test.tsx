import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GraduationsSeen } from "./page";

describe("graduations seen", () => {
  it("shows every graduation since the start, bought or not", () => {
    render(<GraduationsSeen count={6843} />);
    expect(screen.getByTestId("graduations-seen")).toHaveTextContent("6,843");
    expect(screen.getByText(/graduations seen/i)).toHaveTextContent("taken or not");
  });

  it("stays out of the way against an older API that does not send it", () => {
    const { container } = render(<GraduationsSeen count={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
