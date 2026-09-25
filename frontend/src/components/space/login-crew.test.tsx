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
    expect(container.querySelector(".login-crew__bubble")).toHaveTextContent("Tap anywhere");
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
