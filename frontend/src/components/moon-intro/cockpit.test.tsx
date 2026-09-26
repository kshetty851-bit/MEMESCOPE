import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Cockpit, type CockpitProps } from "./cockpit";

afterEach(cleanup);

function setup(props: Partial<CockpitProps> & { keys?: string[] }) {
  const { keys = [], ...rest } = props;
  const handlers = { onSkip: vi.fn(), onToggleSound: vi.fn() };
  const view = render(
    <Cockpit phase="seatbelt" mode="full" soundOn={false} passed={new Set(keys)} {...handlers} {...rest} />,
  );
  return { ...view, ...handlers };
}

describe("Cockpit", () => {
  it("shows SECURED only once the seatbelt moment has passed", () => {
    setup({ keys: ["seatbelt.typeEnd", "seatbelt.buckle"] });
    expect(screen.getByText("FASTEN YOUR SEATBELT")).toBeInTheDocument();
    expect(screen.queryByText("SECURED ✓")).toBeNull();
    cleanup();

    setup({ keys: ["seatbelt.buckle", "seatbelt.secured"] });
    expect(screen.getByText("SECURED ✓")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Seatbelt secured");
  });

  it("lights each switch as its key passes, PAPER HANDS included", () => {
    const { container } = setup({ phase: "cockpit", keys: ["cockpit.switches.0", "cockpit.switches.1"] });
    expect(container.querySelectorAll(".mi-switch[data-on]")).toHaveLength(2);
    expect(screen.getByText("DIAMOND HANDS: ENGAGED")).toBeInTheDocument();
    expect(screen.getByText("PAPER HANDS: DISABLED").closest("li")).toHaveAttribute("data-bad");
    expect(screen.getByText("RUG SHIELD: ---")).toBeInTheDocument();
  });

  it("raises HULL BREACH at the near miss and clears it once repaired", () => {
    setup({ phase: "approach", mode: "full", keys: ["approach.nearMiss"] });
    expect(screen.getByText("HULL BREACH")).toBeInTheDocument();
    cleanup();

    setup({ phase: "approach", mode: "full", keys: ["approach.nearMiss", "approach.repaired"] });
    expect(screen.queryByText("HULL BREACH")).toBeNull();
    expect(screen.getByText("AUTO-REPAIR ✓")).toBeInTheDocument();
  });

  it("wires skip and sound, and hides skip in the reveal", () => {
    const { onSkip, onToggleSound } = setup({ phase: "warp" });
    fireEvent.click(screen.getByRole("button", { name: /skip to moon/i }));
    expect(onSkip).toHaveBeenCalledOnce();
    const sound = screen.getByRole("button", { name: "Sound off" });
    expect(sound).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(sound);
    expect(onToggleSound).toHaveBeenCalledOnce();
    cleanup();

    setup({ phase: "reveal", soundOn: true });
    expect(screen.queryByRole("button", { name: /skip/i })).toBeNull();
    expect(screen.getByRole("button", { name: "Sound on" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("LANDING CONSOLE")).toBeInTheDocument();
  });
});
