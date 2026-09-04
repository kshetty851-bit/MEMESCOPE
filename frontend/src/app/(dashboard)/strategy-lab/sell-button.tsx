"use client";

/**
 * The sell control, shared by the leaderboard panel and the trades view.
 *
 * Its own module rather than an export from either page: a Next.js App Router
 * `page.tsx` may export only `default` and the route fields, so exporting a
 * component from one would fail `next build` with "not a valid Page export
 * field" — after `tsc --noEmit` had already passed. That mistake cost two
 * silent deploys already.
 */

import { useState } from "react";

import { useCloseLabPosition } from "@/hooks/use-lab";

/**
 * Close one position by hand.
 *
 * Two clicks, because a close cannot be undone: the position leaves the book,
 * the cash returns, and there is no reopening it. A single-click sell next to
 * a scrollable list of rows is a misclick waiting to happen, and the row it
 * lands on is chosen at random.
 *
 * The refusal is rendered, not swallowed. "unmarkable" is the answer that
 * matters — it means no fresh price exists, so the sale would have to invent
 * one, and the reader needs to see that rather than a button that quietly did
 * nothing.
 */
export function SellButton({ id }: { id: string }) {
  const [armed, setArmed] = useState(false);
  const close = useCloseLabPosition();
  const outcome = close.data;

  if (close.isPending) {
    return <span className="text-muted">selling…</span>;
  }
  if (outcome && !outcome.closed) {
    return (
      <span className="text-warn" title={outcome.reason}>
        {outcome.reason === "unmarkable" ? "no price" : outcome.reason}
      </span>
    );
  }
  if (close.isError) {
    // The likeliest cause by far is the admin role, not a bug: the alpha
    // cookie grants no account, so say which rather than "failed".
    return <span className="text-down">refused — admin only?</span>;
  }
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        if (armed) close.mutate(id);
        else setArmed(true);
      }}
      onBlur={() => setArmed(false)}
      className={`rounded border px-1.5 py-0.5 text-[10px] ${
        armed
          ? "border-down text-down"
          : "border-line text-muted hover:border-ink-3 hover:text-ink"
      }`}
    >
      {armed ? "confirm" : "sell"}
    </button>
  );
}
