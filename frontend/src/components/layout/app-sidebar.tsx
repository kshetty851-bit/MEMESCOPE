"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { LogoMark, Wordmark } from "@/components/brand/logo";
import { IconCollapse, IconExpand } from "@/components/layout/nav-icons";
import { Tooltip } from "@/components/ui/tooltip";
import { useNavRail } from "@/hooks/use-nav-rail";
import { NAV_FOOTER, NAV_GROUPS, activeItem, type NavItem } from "@/lib/design/nav";
import { cn } from "@/lib/utils";

/**
 * THE NAVIGATION RAIL.
 *
 * Replaces a six-item horizontal strip that spent the full page width on
 * chrome. A vertical rail costs 216px of a 1440px screen and gives back every
 * pixel of vertical space — which is the axis a scanner is read on.
 *
 * Restraint, specifically:
 *
 *  - The active item is a **1px left marker plus a raised surface**. No filled
 *    accent pill, no glow. On a screen where colour means bullish, bearish or
 *    risk, spending an accent fill on "you are here" is spending it on the one
 *    thing the user already knows.
 *  - Unavailable destinations are `aria-disabled` spans, not links. They are
 *    visibly deferred and cannot be clicked, tabbed to, or followed.
 *  - Collapsed, every label survives as the link's accessible name and as a
 *    tooltip that opens on focus — not hover alone.
 */

function railItemClasses(active: boolean, collapsed: boolean) {
  return cn(
    "relative flex items-center rounded-md text-sm",
    "transition-colors duration-[var(--duration-instant)]",
    collapsed ? "h-9 w-9 justify-center" : "h-9 gap-2.5 px-2.5",
    active ? "bg-raised text-ink" : "text-ink-2 hover:bg-surface hover:text-ink",
  );
}

function ActiveMarker({ collapsed }: { collapsed: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-accent",
        collapsed && "left-[-6px]",
      )}
    />
  );
}

function RailLink({
  item,
  active,
  collapsed,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const Icon = item.icon;

  // Planned destinations are not links. Rendering an anchor to nowhere — or to
  // a placeholder page — is the thing this deliberately does not do.
  if (item.status === "planned" || !item.href) {
    const content = (
      <span
        aria-disabled="true"
        className={cn(
          railItemClasses(false, collapsed),
          "cursor-not-allowed text-ink-4 hover:bg-transparent hover:text-ink-4",
        )}
      >
        <Icon className="shrink-0" />
        {collapsed ? null : (
          <>
            <span className="truncate">{item.label}</span>
            <span className="ml-auto shrink-0 text-label uppercase text-ink-4">
              Soon
            </span>
          </>
        )}
        <span className="sr-only">
          {item.label} — {item.note ?? "not available yet"}
        </span>
      </span>
    );

    return collapsed ? (
      <Tooltip content={`${item.label} — ${item.note ?? "not available yet"}`} side="bottom">
        {content}
      </Tooltip>
    ) : (
      content
    );
  }

  const link = (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      onClick={onNavigate}
      className={railItemClasses(active, collapsed)}
    >
      {active ? <ActiveMarker collapsed={collapsed} /> : null}
      <Icon className={cn("shrink-0", active ? "text-accent" : undefined)} />
      {collapsed ? (
        <span className="sr-only">{item.label}</span>
      ) : (
        <span className="truncate">{item.label}</span>
      )}
    </Link>
  );

  return collapsed ? (
    <Tooltip content={item.label} side="bottom">
      {link}
    </Tooltip>
  ) : (
    link
  );
}

export function SidebarContent({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const active = activeItem(pathname);

  return (
    <>
      <nav aria-label="Main" className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="mb-4 last:mb-0">
            {collapsed ? (
              // The heading still has to exist for screen readers; only its
              // visual form changes when the rail narrows.
              <span className="sr-only">{group.label}</span>
            ) : (
              <p className="mb-1.5 px-2.5 text-label font-medium uppercase text-ink-4">
                {group.label}
              </p>
            )}
            <ul className="flex flex-col gap-0.5">
              {group.items.map((item) => (
                <li key={item.label}>
                  <RailLink
                    item={item}
                    active={active?.label === item.label}
                    collapsed={collapsed}
                    onNavigate={onNavigate}
                  />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-line-subtle px-3 py-3">
        <ul className="flex flex-col gap-0.5">
          {NAV_FOOTER.map((item) => (
            <li key={item.label}>
              <RailLink
                item={item}
                active={active?.label === item.label}
                collapsed={collapsed}
                onNavigate={onNavigate}
              />
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}

/**
 * The persistent rail. Hidden below `lg`, where the drawer takes over — a
 * 216px rail on a 768px tablet would spend 28% of the width on navigation.
 */
export function AppSidebar() {
  const { collapsed, toggle } = useNavRail();

  return (
    <aside
      className="hidden shrink-0 flex-col border-r border-line bg-sunken lg:flex"
      // Width is an inline value rather than a utility pair because 13.5rem is
      // not on the spacing scale and inventing an arbitrary class for a single
      // measurement would put a layout constant somewhere it cannot be found.
      style={{ width: collapsed ? "3.5rem" : "13.5rem" }}
    >
      <div
        className={cn(
          "flex h-12 shrink-0 items-center border-b border-line-subtle",
          collapsed ? "justify-center px-2" : "gap-2.5 px-4",
        )}
      >
        <Link
          href="/command"
          aria-label="MEMESCOPE — Scanner"
          className="flex min-w-0 items-center gap-2.5 rounded-sm"
        >
          <LogoMark size={18} className="text-accent" />
          {collapsed ? null : <Wordmark className="text-xs tracking-[0.14em]" />}
        </Link>
      </div>

      <SidebarContent collapsed={collapsed} />

      <div className="border-t border-line-subtle p-2">
        <button
          type="button"
          onClick={toggle}
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          aria-pressed={collapsed}
          className={cn(
            "flex h-8 w-full items-center rounded-md text-ink-3",
            "transition-colors duration-[var(--duration-instant)]",
            "hover:bg-surface hover:text-ink-2",
            collapsed ? "justify-center" : "gap-2.5 px-2.5",
          )}
        >
          {collapsed ? <IconExpand /> : <IconCollapse />}
          {collapsed ? null : <span className="text-xs">Collapse</span>}
        </button>
      </div>
    </aside>
  );
}
