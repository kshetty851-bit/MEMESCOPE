"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { LogoMark, Wordmark } from "@/components/brand/logo";
import { AppSidebar, SidebarContent } from "@/components/layout/app-sidebar";
import { AppTopbar } from "@/components/layout/app-topbar";
import { Universe } from "@/components/space/universe";
import { cn } from "@/lib/utils";

/**
 * THE APPLICATION FRAME.
 *
 * What this replaces: `<main className="mx-auto max-w-[1120px] px-6">`. That
 * cap threw away 320px on a 1440px display and 800px on a 1920px one, while
 * the Track Record's table underneath it was `min-w-[1320px]` — so the widest
 * surface in the product was guaranteed to scroll horizontally inside a
 * container narrower than its own content.
 *
 * The frame is now:
 *
 *     ┌───────┬────────────────────────────────────┐
 *     │ rail  │ topbar (48px, sticky)              │
 *     │ 216 / ├────────────────────────────────────┤
 *     │ 56px  │ page — full remaining width        │
 *     └───────┴────────────────────────────────────┘
 *
 * The page column takes everything left over. Screens that are prose rather
 * than data opt into a reading measure themselves via `<PageBody width="prose">`
 * — the constraint belongs to the content, not to the frame, because the frame
 * cannot know whether it is holding a paragraph or a forty-column table.
 *
 * `min-w-0` on the page column is load-bearing. Without it a wide table forces
 * the flex column, and therefore the document, wider than the viewport — which
 * is the exact bug the old shell had.
 */

const MOBILE_DRAWER_FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/**
 * Navigation on small screens.
 *
 * A drawer rather than a bottom tab bar: there are nine destinations across
 * four groups, and a bottom bar tops out at about five before the labels stop
 * fitting — which is how the previous version ended up truncating to "Com…"
 * and "Obse…".
 */
function MobileNav({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [panel, setPanel] = useState<HTMLElement | null>(null);

  useEffect(() => {
    if (!open || !panel) return;

    const previous = document.activeElement as HTMLElement | null;
    panel.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab") return;

      const nodes = Array.from(
        panel.querySelectorAll<HTMLElement>(MOBILE_DRAWER_FOCUSABLE),
      ).filter((node) => node.offsetParent !== null);
      if (nodes.length === 0) return;

      const first = nodes[0]!;
      const last = nodes[nodes.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKeyDown, true);

    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", onKeyDown, true);
      previous?.focus?.();
    };
  }, [open, panel, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex lg:hidden">
      <button
        type="button"
        aria-label="Close navigation"
        onClick={onClose}
        className="absolute inset-0 h-full w-full cursor-default bg-canvas/70"
      />
      <div
        ref={setPanel}
        role="dialog"
        aria-modal="true"
        aria-label="Navigation"
        tabIndex={-1}
        className="relative z-10 flex h-full w-64 max-w-[85vw] flex-col border-r border-line bg-sunken outline-none"
      >
        <div className="flex h-12 shrink-0 items-center gap-2.5 border-b border-line-subtle px-4">
          <LogoMark size={18} className="text-accent" />
          <Wordmark className="text-xs tracking-[0.14em]" />
        </div>
        <SidebarContent collapsed={false} onNavigate={onClose} />
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const pathname = usePathname();

  // A route change from inside the drawer closes it. Without this, tapping a
  // destination navigates behind an open overlay.
  useEffect(() => setNavOpen(false), [pathname]);

  return (
    <>
      {/* The universe is a sibling of the app, not an ancestor: `position:
          fixed` inside a `overflow: hidden` flex container would be clipped by
          it, and nesting it would put a compositing layer between the shell and
          the page for no reason. */}
      <Universe />

      {/*
        `relative z-10` is the whole layering contract. Everything the user
        reads sits in this stacking context, above the entire scene, so no
        object in the sky can ever cross a table row, an input or a dialog.

        The shell itself is transparent — the universe shows through the gutters
        between panels. Surfaces stay opaque, which is what keeps contrast
        fixed regardless of what happens to be drifting behind them.
      */}
      <div className="relative z-10 flex h-dvh overflow-hidden">
        <AppSidebar />
        <MobileNav open={navOpen} onClose={() => setNavOpen(false)} />

        {/* `min-w-0` stops wide tables from widening the document. */}
        <div className="flex min-w-0 flex-1 flex-col">
          <AppTopbar onOpenNav={() => setNavOpen(true)} />
          {/* Padding lives on the scroll container so every screen gets the
              same gutter without each one declaring it, and so a full-bleed
              table can still reach the edges by using a negative margin rather
              than by fighting a wrapper it does not control. */}
          <main id="main" className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {children}
          </main>
        </div>
      </div>
    </>
  );
}

/**
 * An optional reading measure.
 *
 * Width only — the gutter already comes from `<main>`, so this never
 * double-pads. `full` is the default because this is a data product; the
 * constraint belongs to content that is mostly sentences, and the frame cannot
 * know whether it is holding a paragraph or a forty-column table.
 *
 *   full   unbounded — tables, scanners, dashboards
 *   wide   1600px    — mixed layouts on very large monitors
 *   prose  46rem     — settings, methodology, disclosures
 */
export function PageBody({
  width = "full",
  className,
  children,
}: {
  width?: "full" | "wide" | "prose";
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        width === "wide" && "mx-auto w-full max-w-[1600px]",
        width === "prose" && "mx-auto w-full max-w-[46rem]",
        className,
      )}
    >
      {children}
    </div>
  );
}
