"use client";

import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { IconExit, IconMenu, IconSearch } from "@/components/layout/nav-icons";
import { Tooltip } from "@/components/ui/tooltip";
import { useDisplayMode } from "@/hooks/use-display-mode";
import { useLiveUpdates } from "@/hooks/use-live-updates";
import { api } from "@/lib/api-client";
import { sectionLabel } from "@/lib/design/nav";
import { cn } from "@/lib/utils";

/**
 * THE GLOBAL TOOLBAR.
 *
 * Compact — 48px — because every pixel here is a pixel the scanner does not
 * get. It carries only what is true across every screen: where you are,
 * whether the stream is connected, and how to leave.
 *
 * Per-screen freshness deliberately stays on the screens. `LiveStatus` reports
 * the newest *market* reading among the rows on view, which is a different
 * question from "is the socket up" and cannot be answered globally without
 * inventing a number.
 */

/**
 * Connection state, in words.
 *
 * Never "LIVE" on its own. This reports the transport — whether the browser
 * holds an open stream — and says so plainly. Whether the *data* is current is
 * the per-screen `FreshnessLabel`'s job, and conflating the two is how a badge
 * ends up saying LIVE beside a three-minute-old price.
 */
function StreamStatus() {
  const { status } = useLiveUpdates();

  const meta = {
    live: { label: "Stream connected", tone: "bg-up", text: "text-ink-2" },
    connecting: { label: "Connecting", tone: "bg-warn", text: "text-ink-3" },
    reconnecting: { label: "Reconnecting", tone: "bg-warn", text: "text-ink-3" },
    offline: { label: "Polling", tone: "bg-ink-4", text: "text-ink-3" },
  }[status];

  const explanation =
    status === "offline"
      ? "No live stream. Screens refresh on their own polling interval, so data is still current — just not pushed."
      : status === "live"
        ? "A live update stream is open. Screens refresh when the server commits a change."
        : "Establishing the live update stream. Screens are polling meanwhile.";

  return (
    <Tooltip content={explanation} side="bottom">
      <span
        className="inline-flex items-center gap-1.5 rounded-sm px-1.5 py-1 text-xs"
        tabIndex={0}
      >
        <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", meta.tone)} />
        <span className={cn("hidden sm:inline", meta.text)}>{meta.label}</span>
        <span className="sr-only">Live update stream: {meta.label}</span>
      </span>
    </Tooltip>
  );
}

/**
 * Global search, structurally present and honestly disabled.
 *
 * There is no search endpoint. The shell reserves the slot so the scanner
 * phase can drop a real control in without moving anything, and the control
 * says what it is rather than opening an input that returns nothing.
 */
function SearchSlot() {
  return (
    <Tooltip content="Token search is not built yet. Open a token from the scanner or the track record." side="bottom">
      <span
        aria-disabled="true"
        className={cn(
          "hidden items-center gap-2 rounded-md border border-line-control bg-sunken",
          "h-7 cursor-not-allowed px-2.5 text-xs text-ink-4 md:inline-flex",
        )}
        tabIndex={0}
      >
        <IconSearch className="size-3.5 shrink-0" />
        <span>Search mint or symbol</span>
        <span className="sr-only">— not available yet</span>
      </span>
    </Tooltip>
  );
}

export function AppTopbar({ onOpenNav }: { onOpenNav: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { mode, toggle } = useDisplayMode();
  const [exit, setExit] = useState<"idle" | "leaving" | "failed">("idle");

  /**
   * Leave the alpha.
   *
   * The `await` used to be unguarded and the redirect sat after it, so any
   * rejection — a dropped connection, a backend restart, a 429 from the
   * rate limiter — skipped the navigation entirely. The button did nothing,
   * you stayed in the dashboard, and the only trace was an unhandled
   * rejection in a console you were not looking at.
   *
   * Swallowing the error and redirecting anyway is not the fix either: a
   * failed request means the cookie is still valid, so the gate's session
   * check would send you straight back here. That is the same dead end with
   * an extra page load in the middle.
   *
   * So a failed logout says so and stays put, and the button can be pressed
   * again. The only way to reach the gate is for the session to actually be
   * gone.
   */
  async function exitAlpha() {
    if (exit === "leaving") return;
    setExit("leaving");
    try {
      await api.post("/alpha/logout", undefined, { skipAuthRetry: true });
    } catch {
      setExit("failed");
      return;
    }
    router.replace("/");
  }

  return (
    <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-3 border-b border-line bg-sunken px-3">
      <button
        type="button"
        onClick={onOpenNav}
        aria-label="Open navigation"
        className={cn(
          "grid size-8 shrink-0 place-items-center rounded-md text-ink-2 lg:hidden",
          "transition-colors duration-[var(--duration-instant)] hover:bg-surface hover:text-ink",
        )}
      >
        <IconMenu />
      </button>

      {/* The current section, as an h1. Screens render their own title in the
          Toolbar below; this is the landmark heading for the frame. */}
      <h1 className="min-w-0 truncate text-sm font-medium text-ink">
        {sectionLabel(pathname)}
      </h1>

      <div className="ml-auto flex shrink-0 items-center gap-2">
        <SearchSlot />
        <StreamStatus />

        <span aria-hidden className="h-4 w-px bg-line" />

        <button
          type="button"
          onClick={toggle}
          aria-pressed={mode === "compact"}
          className={cn(
            "hidden h-7 items-center rounded-md border border-line-control px-2 text-xs sm:inline-flex",
            "transition-colors duration-[var(--duration-instant)]",
            mode === "compact"
              ? "bg-raised text-ink"
              : "text-ink-3 hover:border-line-strong hover:text-ink-2",
          )}
        >
          Dense
          <span className="sr-only"> display mode</span>
        </button>

        {/* A failure here is worth a word, not a toast. The control is two
            centimetres away and the only useful next action is to press it
            again. */}
        {exit === "failed" ? (
          <span role="alert" className="hidden text-xs text-down sm:inline">
            Could not sign out — retry
          </span>
        ) : null}

        <button
          type="button"
          onClick={exitAlpha}
          disabled={exit === "leaving"}
          className={cn(
            "grid size-8 shrink-0 place-items-center rounded-md",
            "transition-colors duration-[var(--duration-instant)] hover:bg-surface hover:text-ink",
            "disabled:cursor-wait disabled:opacity-60",
            exit === "failed" ? "text-down" : "text-ink-3",
          )}
          aria-label={exit === "failed" ? "Retry exit alpha" : "Exit alpha"}
        >
          <IconExit />
        </button>
      </div>
    </header>
  );
}
