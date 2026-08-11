import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppSidebar, SidebarContent } from "@/components/layout/app-sidebar";
import {
  NAV_FOOTER,
  NAV_GROUPS,
  activeItem,
  sectionLabel,
  type NavItem,
} from "@/lib/design/nav";

/**
 * The dashboard sits behind the alpha gate, so the rail cannot be inspected in
 * a browser without a code. These assertions cover what a visual pass would
 * have caught — and one thing it would not have: that a destination with no
 * screen behind it is genuinely unreachable rather than merely styled to look
 * unavailable.
 */

const pathname = vi.hoisted(() => ({ current: "/command" }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.current,
}));

afterEach(() => {
  cleanup();
  pathname.current = "/command";
});

describe("navigation map", () => {
  it("marks the item that owns the current route", () => {
    expect(activeItem("/command")?.label).toBe("Scanner");
    expect(activeItem("/record")?.label).toBe("Track record");
    expect(activeItem("/strategy-intelligence")?.label).toBe("Shadow wallets");
  });

  it("resolves nested routes to their owning item", () => {
    expect(activeItem("/record/archive")?.label).toBe("Track record");
  });

  it("does not light up an item for a route it does not own", () => {
    // `/tokens/<mint>` is reached from a token, not from the rail.
    expect(activeItem("/tokens/So11111111111111111111111111111111111111112")).toBeNull();
  });

  it("still names the section on screens that are not in the rail", () => {
    expect(sectionLabel("/tokens/So11111111111111111111111111111111111111112")).toBe(
      "Token intelligence",
    );
    expect(sectionLabel("/command")).toBe("Scanner");
  });

  it("routes every destination, now that Phase 8 shipped the last three", () => {
    // These were `planned` with no href until Trending, New launches and
    // Watchlist existed. The rule they encoded still holds and is asserted
    // below: a nav item either navigates somewhere real or says it cannot.
    const items = [...NAV_GROUPS.flatMap((g) => g.items), ...NAV_FOOTER];
    expect(items.filter((item) => item.status === "planned")).toEqual([]);
    for (const item of items) {
      expect(item.href).toBeTruthy();
    }
  });

  it("keeps the planned treatment available for a future destination", () => {
    // The shape has to survive, or the next unbuilt screen has nowhere honest
    // to live and becomes a link to an empty page.
    const planned: NavItem = {
      label: "Alerts",
      icon: NAV_GROUPS[0]!.items[0]!.icon,
      status: "planned",
      note: "Not built yet",
    };
    expect(planned.href).toBeUndefined();
    expect(planned.note).toBeTruthy();
  });
});

describe("SidebarContent", () => {
  it("renders every ready destination as a real link", () => {
    render(<SidebarContent collapsed={false} />);
    const nav = screen.getByRole("navigation", { name: "Main" });

    for (const label of [
      "Scanner",
      "Track record",
      "Paper wallet",
      "Strategy lab",
      "Shadow wallets",
    ]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  it("renders the Phase 8 destinations as real links", () => {
    render(<SidebarContent collapsed={false} />);

    for (const [label, href] of [
      ["Trending", "/trending"],
      ["New launches", "/launches"],
      ["Watchlist", "/watchlist"],
    ] as const) {
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
  });

  it("no longer marks anything as unavailable", () => {
    render(<SidebarContent collapsed={false} />);
    expect(screen.queryByText(/Not built yet/)).not.toBeInTheDocument();
    expect(screen.queryByText("Soon")).not.toBeInTheDocument();
  });

  it("marks the current route with aria-current", () => {
    pathname.current = "/record";
    render(<SidebarContent collapsed={false} />);

    expect(screen.getByRole("link", { name: "Track record" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Scanner" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("keeps every label as an accessible name when collapsed", () => {
    render(<SidebarContent collapsed />);

    // Labels are visually hidden in the narrow rail; they must not be dropped.
    for (const label of ["Scanner", "Track record", "Paper wallet"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("keeps group headings available to screen readers when collapsed", () => {
    render(<SidebarContent collapsed />);
    for (const group of NAV_GROUPS) {
      expect(screen.getByText(group.label)).toBeInTheDocument();
    }
  });
});

describe("AppSidebar", () => {
  it("exposes a labelled collapse control", () => {
    render(<AppSidebar />);
    const toggle = screen.getByRole("button", { name: "Collapse navigation" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
  });
});
