import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Crew, EnterHq } from "@/components/alpha/crew";
import { EMPLOYEES, EMPLOYEE_BY_ID } from "@/lib/hq/employees";

/**
 * The homepage crew must be the office crew.
 *
 * The failure this guards is a second roster: marketing copy that drifts from
 * the data HQ draws, so a visitor meets a "Nova, Mission Director" here and
 * finds a "Nova, CEO" at her desk. Everything below reads from the same
 * `EMPLOYEES` the isometric office does, and asserts the section renders it
 * rather than restating it.
 */
describe("meet the MEMESCOPE team", () => {
  it("shows all ten, by the name and role HQ uses", () => {
    render(<Crew />);
    for (const employee of EMPLOYEES) {
      const card = screen.getByTestId(`crew-${employee.id}`);
      expect(within(card).getByText(employee.name)).toBeInTheDocument();
      expect(within(card).getByText(employee.role)).toBeInTheDocument();
    }
  });

  it("makes Nova the CEO, and says so in her title", () => {
    render(<Crew />);
    const nova = EMPLOYEE_BY_ID.get("nova")!;
    expect(nova.role).toMatch(/CEO/i);
    expect(within(screen.getByTestId("crew-nova")).getByText(nova.role)).toBeInTheDocument();
  });

  it("gives Nova the lead card and nobody else", () => {
    const { container } = render(<Crew />);
    const leads = container.querySelectorAll(".crew-card-lead");
    expect(leads).toHaveLength(1);
    expect(leads[0]!.querySelector("button")).toHaveAttribute("data-testid", "crew-nova");
  });

  it("opens one profile at a time", () => {
    render(<Crew />);
    const radar = screen.getByTestId("crew-radar");
    const luna = screen.getByTestId("crew-luna");

    expect(radar).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(radar);
    expect(radar).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(EMPLOYEE_BY_ID.get("radar")!.whatIDo)).toBeInTheDocument();

    // Opening another closes the first: two open profiles reflow the grid
    // twice and the second one is always the one nobody asked for.
    fireEvent.click(luna);
    expect(radar).toHaveAttribute("aria-expanded", "false");
    expect(luna).toHaveAttribute("aria-expanded", "true");
  });

  it("shows a department and colleagues that exist", () => {
    render(<Crew />);
    fireEvent.click(screen.getByTestId("crew-atlas"));
    const atlas = EMPLOYEE_BY_ID.get("atlas")!;
    for (const id of atlas.worksWith) {
      expect(EMPLOYEE_BY_ID.get(id), `${id} is not on the roster`).toBeDefined();
    }
    expect(screen.getByText("Department")).toBeInTheDocument();
    expect(screen.getByText("Works with")).toBeInTheDocument();
  });

  it("states no metric, count or status anywhere", () => {
    // The cast list is not a dashboard. Numbers belong in HQ, where they are
    // sourced and timestamped; a figure here would be unciteable by design.
    const { container } = render(<Crew />);
    const text = container.textContent ?? "";
    expect(/\d/.test(text.replace(/MEMESCOPE/g, "")), text.slice(0, 200)).toBe(false);
  });

  it("never claims how any subsystem is doing", () => {
    const { container } = render(<Crew />);
    const text = (container.textContent ?? "").toLowerCase();
    for (const claim of ["healthy", "stable", "normal", "profitable", "safe", "guarantee"]) {
      expect(text, `crew said "${claim}"`).not.toContain(claim);
    }
  });
});

describe("the door into HQ", () => {
  it("points at HQ and says why", () => {
    render(<EnterHq />);
    const link = screen.getByRole("link", { name: /enter memescope hq/i });
    expect(link).toHaveAttribute("href", "/hq");
  });
});
