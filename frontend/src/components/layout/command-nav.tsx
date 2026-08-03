"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Logo, LogoMark } from "@/components/brand/logo";
import { ModeToggle } from "@/components/layout/mode-toggle";
import { StatusDot } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/panel";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";

/**
 * Command rail.
 *
 * Vertical, fixed, iconographic — the persistent left edge of the instrument.
 * Collapses to a bottom bar on mobile because a 64px vertical rail on a phone
 * steals the one axis that matters.
 */

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
}

const ICON = "size-[18px]";

const NAV: NavItem[] = [
  {
    href: "/command",
    label: "Command",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        className={ICON}
      >
        <circle cx="12" cy="12" r="3" />
        <circle cx="12" cy="12" r="8.5" strokeDasharray="3 3" />
        <path d="M12 1v3M12 20v3M1 12h3M20 12h3" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    href: "/feed",
    label: "Observatory",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        className={ICON}
      >
        <path
          d="M3 8V5a2 2 0 0 1 2-2h3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3"
          strokeLinecap="round"
        />
        <path d="M3 12h18" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    href: "/opportunities",
    label: "Signals",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        className={ICON}
      >
        <path d="M3 14l4-6 4 4 3-7 4 9" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="18" cy="14" r="2.5" />
      </svg>
    ),
  },
  {
    href: "/radar",
    label: "Radar",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        className={ICON}
      >
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="4.5" />
        <path d="M12 3v4M12 17v4M3 12h4M17 12h4" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    href: "/track-record",
    label: "Record",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        className={ICON}
      >
        <path d="M3 19h18" strokeLinecap="round" />
        <rect x="5" y="12" width="3.5" height="7" rx="1" />
        <rect x="10.25" y="7" width="3.5" height="12" rx="1" />
        <rect x="15.5" y="10" width="3.5" height="9" rx="1" />
      </svg>
    ),
  },
  {
    href: "/exit-watch",
    label: "Exit",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        className={ICON}
      >
        <path d="M12 3v10" strokeLinecap="round" />
        <path d="M7.5 6.5a8 8 0 1 0 9 0" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    href: "/division",
    label: "Division",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        className={ICON}
      >
        <circle cx="12" cy="12" r="2.5" />
        <circle cx="12" cy="4" r="2" />
        <circle cx="19" cy="16" r="2" />
        <circle cx="5" cy="16" r="2" />
        <path d="M12 6.2v3.3M13.9 13.4l3.3 1.7M10.1 13.4l-3.3 1.7" />
      </svg>
    ),
  },
  {
    href: "/about",
    label: "About",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        className={ICON}
      >
        <circle cx="12" cy="12" r="9" />
        <path d="M12 16v-5M12 8h.01" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    href: "/system",
    label: "System",
    icon: (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        className={ICON}
      >
        <rect x="3" y="3" width="7.5" height="7.5" rx="1.5" />
        <rect x="13.5" y="3" width="7.5" height="7.5" rx="3.75" />
        <rect x="3" y="13.5" width="7.5" height="7.5" rx="3.75" />
        <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5" />
      </svg>
    ),
  },
];

export function CommandNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();

  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  async function handleSignOut() {
    await logout();
    router.replace("/login");
  }

  return (
    <>
      {/* Desktop rail */}
      <nav
        aria-label="Command navigation"
        className="fixed inset-y-0 left-0 z-40 hidden w-[68px] flex-col items-center border-r border-line bg-abyss/80 py-5 backdrop-blur-xl lg:flex"
      >
        <Link href="/command" aria-label="LETZMOON Command Center" className="mb-8">
          <LogoMark size={26} className="text-plasma" />
        </Link>

        <ul className="flex flex-1 flex-col gap-1.5">
          {NAV.map((item) => {
            const active = isActive(item.href);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "group relative flex size-11 items-center justify-center rounded-card transition-colors duration-150",
                    active
                      ? "bg-plasma/12 text-plasma"
                      : "text-ink-faint hover:bg-elevated/70 hover:text-ink",
                  )}
                >
                  {item.icon}
                  {/* Active marker rides the rail edge, not the icon. */}
                  {active && (
                    <span className="absolute -left-[9px] h-5 w-[2px] rounded-full bg-plasma" />
                  )}
                  <span className="pointer-events-none absolute left-full ml-3 hidden whitespace-nowrap rounded-chip border border-line bg-elevated px-2 py-1 text-xs text-ink group-hover:block">
                    {item.label}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>

        <button
          onClick={handleSignOut}
          aria-label="Sign out"
          className="flex size-11 items-center justify-center rounded-card text-ink-faint transition-colors hover:bg-elevated/70 hover:text-danger"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            className={ICON}
          >
            <path
              d="M15 17l5-5-5-5M20 12H9M11 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </nav>

      {/* Mobile bar */}
      <nav
        aria-label="Command navigation"
        className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-around border-t border-line bg-abyss/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden"
      >
        {NAV.map((item) => {
          const active = isActive(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                // `min-w-0` + truncate: four flex-1 items each had a ~104px
                // min-content width from their label, which forced the bar —
                // and the whole document — past a 375px viewport.
                "flex min-w-0 flex-1 flex-col items-center gap-1 px-1 py-3 transition-colors",
                active ? "text-plasma" : "text-ink-faint",
              )}
            >
              {item.icon}
              <span className="w-full truncate text-center text-[0.5625rem] tracking-wide">
                {item.label}
              </span>
            </Link>
          );
        })}
      </nav>

      {/* Top bar */}
      <header className="sticky top-0 z-30 border-b border-line bg-void/70 backdrop-blur-xl">
        <div className="flex h-14 min-w-0 items-center justify-between gap-3 px-4 lg:gap-4 lg:px-8">
          <div className="flex items-center gap-3 lg:hidden">
            <Logo size={20} />
          </div>

          <div className="hidden items-center gap-2.5 lg:flex">
            <StatusDot tone="var(--color-safe)" />
            <Label>All systems operational</Label>
          </div>

          <div className="flex min-w-0 items-center gap-2 lg:gap-3">
            <ModeToggle />
            <span className="hidden text-xs text-ink-faint sm:inline">
              {user?.display_name ?? user?.email}
            </span>
            <Button variant="ghost" size="sm" className="lg:hidden" onClick={handleSignOut}>
              Sign out
            </Button>
          </div>
        </div>
      </header>
    </>
  );
}
