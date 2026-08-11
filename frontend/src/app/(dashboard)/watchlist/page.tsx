"use client";

import { useCallback, useMemo, useState } from "react";

import { TokenCell } from "@/components/scanner/token-cell";
import { DataTable, useTableSort, type Column } from "@/components/ui/data-table";
import { Num } from "@/components/ui/num";
import { Panel } from "@/components/ui/panel";
import { Tabs } from "@/components/ui/tabs";
import { Toolbar } from "@/components/ui/toolbar";
import { InfoTip } from "@/components/ui/tooltip";
import { ErrorState } from "@/components/ui/states";
import {
  useAddToWatchlist,
  useCreateWatchlist,
  useDeleteWatchlist,
  useRemoveFromWatchlist,
  useWatchlistTokens,
  useWatchlists,
} from "@/hooks/use-watchlist";
import { isUnpersistedAccount } from "@/lib/watchlist";
import { num } from "@/lib/design/bands";
import { formatDate } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { WatchlistItem } from "@/types/watchlist";

/**
 * WATCHLIST.
 *
 * WHAT THIS SCREEN IS FOR
 *
 * Not a second scanner. The watchlist API returns only a mint per row — no
 * name, symbol, price or market cap — and there is no batch token lookup, so
 * rebuilding a scanner row here would cost one request per token.
 *
 * What it returns instead is the thing no other screen has: the token's state
 * **when you added it**, beside its state **now**. `added_score` is written
 * once and never updated. So this screen answers "what has changed since I
 * started watching this?", which is a question the Scanner cannot answer at
 * all, and it leans on that rather than apologising for the columns it lacks.
 *
 * WHY IT MAY REFUSE TO CREATE A LIST HERE
 *
 * Watchlists are the first user-owned resource in MEMESCOPE: every route is
 * scoped to a real `users` row. The alpha cookie is a gate, not an identity.
 * With `DEVELOPMENT_BYPASS_AUTH=true` the backend issues a synthetic principal
 * it deliberately never persists, so reads return empty and the first write
 * comes back 409. That is a configuration state, and this screen says so in
 * those words rather than showing "something went wrong".
 */

const MINT_PATTERN = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

/** Score when added, score now, and the move between them. */
function ScoreShift({ item }: { item: WatchlistItem }) {
  const then = num(item.added_score);
  const now = num(item.current_score);

  if (then === null && now === null) {
    return <Num value={null} absentLabel="never scored" />;
  }

  const delta = then !== null && now !== null ? now - then : null;

  return (
    <span className="inline-flex items-baseline justify-end gap-1.5">
      <Num
        value={item.added_score}
        format={(v) => Math.round(Number(v)).toString()}
        tone="muted"
        className="text-xs"
      />
      <span aria-hidden className="text-ink-4">
        →
      </span>
      <Num
        value={item.current_score}
        format={(v) => Math.round(Number(v)).toString()}
        className="text-sm font-medium"
      />
      {delta !== null && Math.round(delta) !== 0 ? (
        <span
          data-numeric
          className={cn("text-xs", delta > 0 ? "text-up" : "text-down")}
        >
          {delta > 0 ? "+" : "−"}
          {Math.abs(Math.round(delta))}
        </span>
      ) : null}
      <span className="sr-only">
        {then !== null ? `Scored ${Math.round(then)} when added` : "Not scored when added"}
        {now !== null ? `, ${Math.round(now)} now` : ", not scored now"}
      </span>
    </span>
  );
}

export default function WatchlistPage() {
  const lists = useWatchlists();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [newListName, setNewListName] = useState("");
  const [mintInput, setMintInput] = useState("");

  const createList = useCreateWatchlist();
  const deleteList = useDeleteWatchlist();
  const addToken = useAddToWatchlist();
  const removeToken = useRemoveFromWatchlist();

  const available = lists.data ?? [];
  const selected = available.find((l) => l.id === activeId) ?? available[0];
  const tokens = useWatchlistTokens(selected?.id);

  const rows = useMemo(() => tokens.data ?? [], [tokens.data]);

  const selectValue = useCallback((row: WatchlistItem, key: string) => {
    switch (key) {
      case "added":
        return new Date(row.created_at).getTime();
      case "score":
        return num(row.current_score);
      case "change":
        return row.last_change_at ? new Date(row.last_change_at).getTime() : null;
      default:
        return null;
    }
  }, []);

  const { sort, setSort, sorted } = useTableSort<WatchlistItem>(rows, selectValue, null);

  const columns = useMemo<Column<WatchlistItem>[]>(
    () => [
      {
        key: "token",
        header: "Token",
        pinned: true,
        width: "200px",
        cell: (row) => (
          // The API carries no name or symbol, so `TokenCell` falls back to the
          // shortened mint. It still links into the dossier, which is where the
          // identity lives.
          <TokenCell mint={row.mint_address} name={null} symbol={null} />
        ),
      },
      {
        key: "added",
        header: "Watching since",
        align: "right",
        width: "150px",
        sortable: true,
        cell: (row) => (
          <span data-numeric className="text-xs text-ink-3">
            {formatDate(row.created_at)}
          </span>
        ),
      },
      {
        key: "score",
        header: "Score then → now",
        align: "right",
        width: "168px",
        sortable: true,
        srHeader: "MEMESCOPE score when added, compared with now",
        cell: (row) => <ScoreShift item={row} />,
      },
      {
        key: "priority",
        header: "Priority",
        width: "104px",
        headerClassName: "hidden lg:table-cell",
        cellClassName: "hidden lg:table-cell",
        cell: (row) =>
          row.current_priority ? (
            <span className="text-xs capitalize text-ink-2">
              {row.current_priority.replaceAll("_", " ")}
            </span>
          ) : (
            <Num value={null} absentLabel="no priority recorded" />
          ),
      },
      {
        key: "change",
        header: "Last change",
        width: "260px",
        sortable: true,
        headerClassName: "hidden xl:table-cell",
        cellClassName: "hidden xl:table-cell",
        cell: (row) =>
          // Rendered by the backend. Displayed verbatim.
          row.last_change ? (
            <span className="flex min-w-0 flex-col">
              <span className="truncate text-xs text-ink-2">{row.last_change}</span>
              {row.last_change_at ? (
                <span data-numeric className="text-micro text-ink-4">
                  {formatDate(row.last_change_at)}
                </span>
              ) : null}
            </span>
          ) : (
            <Num value={null} absentLabel="nothing recorded since adding" />
          ),
      },
      {
        key: "remove",
        header: "",
        align: "right",
        width: "80px",
        srHeader: "Remove from watchlist",
        cell: (row) => (
          <button
            type="button"
            disabled={!selected || removeToken.isPending}
            onClick={() =>
              selected &&
              removeToken.mutate({ listId: selected.id, mint: row.mint_address })
            }
            className={cn(
              "rounded-sm px-1.5 py-0.5 text-xs text-ink-3",
              "transition-colors duration-[var(--duration-instant)]",
              "hover:bg-raised hover:text-down",
              "disabled:pointer-events-none disabled:opacity-40",
            )}
          >
            Remove
            <span className="sr-only"> {row.mint_address} from {selected?.name}</span>
          </button>
        ),
      },
    ],
    [selected, removeToken],
  );

  const blocked = isUnpersistedAccount(createList.error);
  const mintValid = MINT_PATTERN.test(mintInput.trim());

  if (lists.isError) {
    return (
      <ErrorState
        body="The watchlist service is not responding. Anything already saved is safe — this view will recover on its own."
        onRetry={() => void lists.refetch()}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Toolbar
        eyebrow="Watchlist"
        title="Tokens you are tracking"
        description="Each token keeps the score it had when you added it, beside its score now — so this screen answers what has changed since you started watching."
      />

      {/* The environment blocker, stated once and plainly. */}
      {blocked ? (
        <Panel density="comfortable" className="border-warn/30 bg-warn/[0.05]">
          <h2 className="text-sm font-medium text-warn">
            Watchlists need a real account
          </h2>
          <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-ink-2">
            This environment runs with <code className="text-ink">DEVELOPMENT_BYPASS_AUTH=true</code>,
            which authenticates every request as a synthetic principal the backend
            deliberately never writes to the database. Watchlists are the first
            user-owned resource in MEMESCOPE, so they are the first thing to need a
            real row.
          </p>
          <p className="mt-2 max-w-2xl text-xs leading-relaxed text-ink-3">
            Seed an account and turn the bypass off to use this screen. Everything
            below is wired to the real API and will work unchanged.
          </p>
        </Panel>
      ) : null}

      {available.length > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Tabs
            items={available.map((list) => ({
              value: list.id,
              label: list.name,
              count: list.item_count,
            }))}
            value={selected?.id ?? ""}
            onChange={setActiveId}
            aria-label="Your watchlists"
          />
          {selected ? (
            <button
              type="button"
              onClick={() => {
                deleteList.mutate(selected.id);
                setActiveId(null);
              }}
              className="rounded-sm px-2 py-1 text-xs text-ink-3 transition-colors hover:text-down"
            >
              Delete “{selected.name}”
            </button>
          ) : null}
        </div>
      ) : null}

      {available.length === 0 && !lists.isPending ? (
        <Panel density="comfortable" className="flex flex-col gap-3">
          <div>
            <h2 className="text-sm font-medium text-ink">No watchlists yet</h2>
            <p className="mt-1 max-w-md text-xs leading-relaxed text-ink-3">
              Create one to start tracking tokens. MEMESCOPE records each token&rsquo;s
              score at the moment you add it, so you can see what moved afterwards.
            </p>
          </div>
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (!newListName.trim()) return;
              createList.mutate(
                { name: newListName.trim() },
                { onSuccess: () => setNewListName("") },
              );
            }}
          >
            <label className="sr-only" htmlFor="new-list">
              Watchlist name
            </label>
            <input
              id="new-list"
              value={newListName}
              onChange={(event) => setNewListName(event.target.value)}
              placeholder="e.g. Watching closely"
              maxLength={64}
              className="h-8 w-56 rounded-md border border-line-control bg-sunken px-2.5 text-xs text-ink placeholder:text-ink-4 hover:border-line-strong"
            />
            <button
              type="submit"
              disabled={!newListName.trim() || createList.isPending}
              className="h-8 rounded-md border border-accent/40 bg-accent/10 px-3 text-xs font-medium text-accent transition-colors hover:bg-accent/16 disabled:pointer-events-none disabled:opacity-40"
            >
              {createList.isPending ? "Creating…" : "Create watchlist"}
            </button>
          </form>
          {createList.isError && !blocked ? (
            <p role="alert" className="text-xs text-down">
              {createList.error instanceof Error
                ? createList.error.message
                : "Could not create that watchlist."}
            </p>
          ) : null}
        </Panel>
      ) : null}

      {selected ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="flex items-center gap-1.5 text-sm font-medium text-ink">
              {selected.name}{" "}
              <span data-numeric className="font-normal text-ink-3">
                ({sorted.length})
              </span>
              <InfoTip
                label="score then and now"
                content="The score on the left is the one recorded when you added the token; it is written once and never updated. The score on the right is current. MEMESCOPE has no holder, wallet or social data for watched tokens."
              />
            </h2>

            <form
              className="flex flex-wrap items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (!mintValid) return;
                addToken.mutate(
                  { listId: selected.id, mint: mintInput.trim() },
                  { onSuccess: () => setMintInput("") },
                );
              }}
            >
              <label className="sr-only" htmlFor="add-mint">
                Mint address to watch
              </label>
              <input
                id="add-mint"
                value={mintInput}
                onChange={(event) => setMintInput(event.target.value)}
                placeholder="Paste a mint address"
                aria-invalid={mintInput.length > 0 && !mintValid}
                className={cn(
                  "h-8 w-64 rounded-md border bg-sunken px-2.5 font-mono text-xs text-ink",
                  "placeholder:font-sans placeholder:text-ink-4",
                  mintInput.length > 0 && !mintValid
                    ? "border-down"
                    : "border-line-control hover:border-line-strong",
                )}
              />
              <button
                type="submit"
                disabled={!mintValid || addToken.isPending}
                className="h-8 rounded-md border border-line-control px-3 text-xs text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:pointer-events-none disabled:opacity-40"
              >
                {addToken.isPending ? "Adding…" : "Watch"}
              </button>
            </form>
          </div>

          <DataTable
            columns={columns}
            rows={sorted}
            getRowId={(row) => row.mint_address}
            caption={`Tokens on ${selected.name}, with the score recorded when each was added`}
            sort={sort}
            onSortChange={setSort}
            density="compact"
            stickyHeader
            maxHeight="calc(100dvh - 20rem)"
            minWidth="620px"
            isPending={tokens.isPending}
            pendingRows={6}
            empty={
              <div className="px-3 py-12 text-center">
                <p className="text-sm text-ink">Nothing on this list yet</p>
                <p className="mt-1.5 text-xs text-ink-3">
                  Paste a mint address above, or open a token and add it from its
                  intelligence page.
                </p>
              </div>
            }
          />

          {addToken.isError ? (
            <p role="alert" className="text-xs text-down">
              {addToken.error instanceof Error
                ? addToken.error.message
                : "Could not add that token."}
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
