"use client";

import { useMemo } from "react";

import { Tooltip } from "@/components/ui/tooltip";
import {
  useAddToWatchlist,
  useRemoveFromWatchlist,
  useWatchlistTokens,
  useWatchlists,
} from "@/hooks/use-watchlist";
import { cn } from "@/lib/utils";

/**
 * WATCH / UNWATCH, on the dossier only.
 *
 * WHY NOT ON SCANNER ROWS TOO
 *
 * A watch control needs a *target list*, and a user can have several. On a
 * single-token screen that is answerable — the control names the list it will
 * add to. On fifty scanner rows it would either pick one silently, which makes
 * the button lie about where the token went, or need a per-row menu, which is
 * real state complexity on the one screen whose responsiveness matters most.
 *
 * So it lives here, where there is room to say what it is doing.
 *
 * WHAT IT COSTS
 *
 * Two queries, both already cached across the app: the user's lists, and the
 * tokens on the first one. No per-token request — "is this watched?" is
 * answered by looking in the list already fetched.
 */
export function WatchButton({ mint }: { mint: string }) {
  const lists = useWatchlists();
  // The first list is the default target. The backend has no "primary" flag,
  // and inventing an ordering the user cannot see would be worse than using
  // the one the API returns and naming it on the button.
  const target = lists.data?.[0];

  const tokens = useWatchlistTokens(target?.id);
  const add = useAddToWatchlist();
  const remove = useRemoveFromWatchlist();

  const watched = useMemo(
    () => (tokens.data ?? []).some((item) => item.mint_address === mint),
    [tokens.data, mint],
  );

  const pending = add.isPending || remove.isPending;

  // No list to add to. Say why rather than rendering a button that fails.
  if (!lists.isPending && !target) {
    return (
      <Tooltip
        content="You have no watchlist yet. Create one on the Watchlist screen, then tokens can be added from here."
        side="bottom"
      >
        <span
          aria-disabled="true"
          tabIndex={0}
          className="inline-flex h-7 cursor-not-allowed items-center rounded-md border border-line px-2.5 text-xs text-ink-4"
        >
          Watch
          <span className="sr-only"> — unavailable, no watchlist exists yet</span>
        </span>
      </Tooltip>
    );
  }

  return (
    <Tooltip
      content={
        watched
          ? `Remove this token from “${target?.name}”.`
          : `Add this token to “${target?.name}”. MEMESCOPE records its score now, so you can see what changes afterwards.`
      }
      side="bottom"
    >
      <button
        type="button"
        disabled={pending || !target}
        aria-pressed={watched}
        onClick={() => {
          if (!target) return;
          if (watched) remove.mutate({ listId: target.id, mint });
          else add.mutate({ listId: target.id, mint });
        }}
        className={cn(
          "inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-xs",
          "transition-colors duration-[var(--duration-instant)]",
          "disabled:pointer-events-none disabled:opacity-50",
          watched
            ? "border-accent/40 bg-accent/10 text-accent"
            : "border-line-control text-ink-2 hover:border-line-strong hover:text-ink",
        )}
      >
        {pending ? "…" : watched ? "Watching" : "Watch"}
        <span className="sr-only">
          {watched
            ? ` — on ${target?.name}. Activate to remove.`
            : ` — activate to add to ${target?.name}.`}
        </span>
      </button>
    </Tooltip>
  );
}
