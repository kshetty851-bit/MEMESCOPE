"use client";

import type { FormEvent } from "react";
import { useEffect, useState } from "react";

import { ALPHA_ACCESS, BUILD } from "@/lib/env";
import { ApiError, api } from "@/lib/api-client";
import type { GatePhase } from "@/lib/launch";
import { cn } from "@/lib/utils";
import type { AlphaSessionStatus } from "@/types/api";

/**
 * The access gate.
 *
 * It owns the credential and nothing else. It reports what happened through
 * `onPhase` and the landing page decides what the sky does about it — which is
 * why the launch sequence could be added without a line of authentication
 * changing: the unlock request, the server-set cookie and the redirect for an
 * already-authenticated visitor are exactly what they were.
 *
 * Navigation into the terminal moved out of this component with the sequence.
 * It used to fire on a fixed 1.7s timer here; the cinematic that replaced that
 * timer is owned by the page, so the page is what pushes the route when the
 * mission ends. The session is written the moment the server accepts, before
 * any of it plays, so a visitor who reloads mid-countdown is already in.
 */
export function AlphaAccess({ onPhase }: { onPhase: (phase: GatePhase | "approved") => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [unlocking, setUnlocking] = useState(false);
  /**
   * Whether this visitor already holds a live alpha session.
   *
   * `null` while unknown, which is not the same as `false` — the card must not
   * flash the code form at somebody who is already in, nor flash the
   * already-in state at somebody who is not.
   */
  const [returning, setReturning] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;

    void api
      .get<AlphaSessionStatus>("/alpha/session", { skipAuthRetry: true })
      .then((session) => {
        if (!cancelled) setReturning(session.authenticated);
      })
      .catch(() => {
        // The launch screen is the safe fallback. Do not surface network errors
        // as password failures before the visitor submits anything.
        if (!cancelled) setReturning(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (unlocking) return;

    setError(null);
    setUnlocking(true);
    onPhase("validating");
    try {
      await api.post<AlphaSessionStatus>(
        "/alpha/unlock",
        { code },
        { skipAuthRetry: true },
      );
      // The secure cookie from the accepted unlock is now attached to this
      // first-party request. Failure is non-blocking: telemetry must never
      // prevent a successful alpha entrant from reaching the dashboard.
      void api.post("/alpha/activity", { path: "/" }, { skipAuthRetry: true });
      window.sessionStorage.setItem(ALPHA_ACCESS.transitionKey, "true");
      // The form stays locked from here. There is no path back to `idle` after
      // an accepted code, which is what makes a second submission impossible
      // while the sequence plays.
      onPhase("approved");
    } catch (error) {
      setError(
        error instanceof ApiError && error.status !== 401
          ? "Access service is temporarily unavailable. Please retry."
          : "Access code not recognised.",
      );
      setUnlocking(false);
      onPhase("denied");
    }
  }

  /**
   * A visitor who is already in gets a door, not a form — and stays on the page.
   *
   * This used to `router.replace` to the dashboard the moment the session check
   * came back authenticated, which meant a returning visitor never saw the
   * homepage at all: they typed the address and arrived in the Scanner. That
   * was defensible while the homepage was only a gate. It stopped being
   * defensible the moment the homepage acquired the crew, the wordmark and the
   * route into HQ — the page now has a reason to exist, and force-navigating
   * away from a page somebody explicitly asked for is not routing, it is a
   * redirect loop with better manners.
   *
   * **The gate itself is untouched.** A visitor without a session still sees
   * the code form and still cannot pass without a valid code; nothing here
   * grants access. All that changed is that being *already* authenticated no
   * longer forbids you from reading the front page of the product you use.
   */
  if (returning) {
    return (
      <div
        aria-labelledby="alpha-access-heading"
        className="w-full rounded-lg border border-line bg-surface p-5 shadow-e3"
      >
        <h2
          id="alpha-access-heading"
          className="text-label font-medium uppercase tracking-[0.16em] text-accent"
        >
          Alpha access
        </h2>
        <p className="mt-1.5 text-sm text-ink-2">
          You are signed in to the private alpha.
        </p>
        <a
          href={ALPHA_ACCESS.dashboardPath}
          data-testid="alpha-enter-terminal"
          className={cn(
            "mt-4 flex h-10 w-full items-center justify-center rounded-md",
            "border border-accent/40 bg-accent/10",
            "text-sm font-medium tracking-[0.08em] text-accent",
            "transition-colors duration-[var(--duration-instant)]",
            "hover:border-accent/70 hover:bg-accent/16",
          )}
        >
          Enter the terminal
        </a>
        <div className="mt-4 border-t border-line-subtle pt-3">
          <p data-numeric className="text-xs text-ink-3">
            Version {BUILD.version.replace(/^v/i, "")} · alpha
          </p>
        </div>
      </div>
    );
  }

  return (
    // Opaque. The panel used to be `bg-abyss/55` with a backdrop blur, floating
    // over the mascot photograph — which meant its own labels, version string
    // and disclosure were read against whatever pixels happened to be behind
    // them. A gate that collects input is the last surface in a product that
    // should be translucent.
    <form
      onSubmit={submit}
      aria-labelledby="alpha-access-heading"
      className="w-full rounded-lg border border-line bg-surface p-5 shadow-e3"
    >
      <h2
        id="alpha-access-heading"
        className="text-label font-medium uppercase tracking-[0.16em] text-accent"
      >
        Alpha access
      </h2>
      <p className="mt-1.5 text-sm text-ink-2">
        Enter the code you were issued to open the terminal.
      </p>

      <label htmlFor="alpha-code" className="sr-only">
        Enter access code
      </label>
      <input
        id="alpha-code"
        value={code}
        onChange={(event) => {
          setCode(event.target.value);
          setError(null);
        }}
        inputMode="numeric"
        autoComplete="one-time-code"
        placeholder="Access code"
        disabled={unlocking}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? "alpha-code-error" : undefined}
        className={cn(
          "mt-4 h-11 w-full rounded-md border bg-sunken px-4 text-center",
          "font-mono text-md tracking-[0.24em] text-ink",
          "transition-colors duration-[var(--duration-instant)]",
          "placeholder:tracking-normal placeholder:text-ink-4",
          "disabled:opacity-70",
          error ? "border-down" : "border-line-control hover:border-line-strong",
        )}
      />

      {error ? (
        <p id="alpha-code-error" role="alert" className="mt-2 text-xs text-down">
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={unlocking}
        className={cn(
          "mt-3 h-10 w-full rounded-md border border-accent/40 bg-accent/10",
          "text-sm font-medium tracking-[0.08em] text-accent",
          "transition-colors duration-[var(--duration-instant)]",
          "hover:border-accent/70 hover:bg-accent/16",
          "disabled:cursor-wait disabled:opacity-70",
        )}
      >
        {unlocking ? "Unlocking…" : "Unlock"}
      </button>

      <div className="mt-4 border-t border-line-subtle pt-3">
        <p data-numeric className="text-xs text-ink-3">
          Version {BUILD.version.replace(/^v/i, "")} · alpha
        </p>
        <p className="mt-1.5 text-xs leading-relaxed text-ink-3">
          During alpha testing, MEMESCOPE records basic session activity and page
          usage to improve the product.
        </p>
      </div>
    </form>
  );
}
