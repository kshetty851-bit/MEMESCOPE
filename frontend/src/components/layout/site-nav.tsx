"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Logo } from "@/components/brand/logo";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";

/**
 * Top navigation.
 *
 * Five destinations, named in plain language. Replaces the nine-item
 * iconographic rail, which required hovering to learn what any of it meant and
 * truncated to "Com…", "Obse…", "Divisi…" on a phone.
 *
 * Text labels, not icons: nine unlabelled glyphs is a puzzle, and this product
 * is meant to be readable in ten seconds. Horizontal, not a left rail — on a
 * data product the vertical axis is the one worth spending on content.
 */

interface NavItem {
  href: string;
  label: string;
}

const NAV: NavItem[] = [
  { href: "/command", label: "Radar" },
  { href: "/record", label: "Track record" },
  { href: "/wallet", label: "Paper wallet" },
  // Sprint 26. Sits beside the wallet because it answers the question the
  // wallet raises: the wallet runs one rule, the lab shows how every published
  // rule handled the same detections.
  { href: "/lab", label: "Strategy lab" },
  { href: "/settings", label: "Settings" },
];

export function SiteNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();

  // The Radar is the root, so a prefix match would mark it active everywhere.
  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  async function handleSignOut() {
    await logout();
    router.replace("/login");
  }

  return (
    <>
      <header className="sticky top-0 z-40 border-b border-line bg-abyss/85 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-[1120px] items-center gap-8 px-6">
          <Link href="/command" aria-label="MEMESCOPE — Radar">
            <Logo />
          </Link>

          <nav aria-label="Main" className="hidden flex-1 md:block">
            <ul className="flex items-center gap-6">
              {NAV.map((item) => {
                const active = isActive(item.href);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "text-sm transition-colors duration-150",
                        active ? "text-ink" : "text-ink-faint hover:text-ink",
                      )}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>

          <div className="ml-auto flex items-center gap-4">
            {user ? (
              <button
                type="button"
                onClick={handleSignOut}
                className="text-sm text-ink-faint transition-colors hover:text-ink"
              >
                Sign out
              </button>
            ) : (
              <Link
                href="/login"
                className="text-sm text-ink-faint transition-colors hover:text-ink"
              >
                Sign in
              </Link>
            )}
          </div>
        </div>
      </header>

      {/* Mobile: the same five, at the bottom, with labels that fit. */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-abyss/95 backdrop-blur-xl md:hidden"
      >
        <ul className="flex items-stretch">
          {NAV.map((item) => {
            const active = isActive(item.href);
            return (
              <li key={item.href} className="flex-1">
                <Link
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-14 items-center justify-center px-1 text-center text-xs transition-colors",
                    active ? "text-plasma" : "text-ink-faint",
                  )}
                >
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </>
  );
}
