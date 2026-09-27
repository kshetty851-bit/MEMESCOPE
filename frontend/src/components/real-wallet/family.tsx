"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { useAuth } from "@/hooks/use-auth";
import { ApiError, api } from "@/lib/api-client";

/**
 * THE USER WALLETS: USER 1 … USER 10 (the family wallets until 2026-09-27).
 *
 * Each has a Solana wallet of its own: an address to deposit to, a balance,
 * a withdrawal that can only reach Karthik, and trading that copies his
 * nominated strategy on its own switch and size. Only Karthik, signed in as
 * the admin, can open these pages; the server refuses anyone else.
 */

export const FAMILY = Array.from({ length: 10 }, (_, i) => `USER${i + 1}`);

/** "USER7" -> "USER 7". */
function title(member: string): string {
  return member.replace("USER", "USER ");
}

function usd(value: string | number | null | undefined): string {
  const n = Number(value);
  if (value === null || value === undefined || !Number.isFinite(n)) return "—";
  return `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function tone(value: string | number | null | undefined): string {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "text-ink";
  return n > 0 ? "text-up" : "text-down";
}

/** The ten user wallets on the real wallet page, for Karthik only. */
export function FamilySection() {
  const { user } = useAuth();
  if (user?.role !== "admin") return null;
  return (
    <section className="mt-6 rounded-lg border border-line p-5">
      <p className="text-label text-ink-3">User wallets</p>
      <p className="mt-1 max-w-2xl text-sm text-ink-3">
        Each user has a Solana wallet of their own that copies your strategy: its own address,
        balance, trade size and on/off. Withdrawals from it can only go to your address.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        {FAMILY.map((m) => (
          <Link
            key={m}
            href={`/real-wallet/family/${m.toLowerCase()}`}
            className="inline-flex h-10 items-center rounded-md border border-line px-5 text-sm font-medium text-ink hover:border-accent hover:text-accent"
          >
            {title(m)}
          </Link>
        ))}
      </div>
    </section>
  );
}

interface OwnWallet {
  address: string | null;
  explorer?: string;
  withdraws_to?: string | null;
  balance_sol?: string | null;
  balance_usd?: string | null;
  balance_error?: string | null;
}

interface OwnTrade {
  mint: string;
  status: "OPEN" | "CLOSED";
  opened_at: string;
  closed_at: string | null;
  cost_usd: string | null;
  pnl_usd: string | null;
  exit_reason: string | null;
}

interface OwnBook {
  enabled: boolean;
  ticket_usd: string;
  ticket_choices: string[];
  today_pnl_usd: string | null;
  open_positions: number;
  since_first_trade: { trades: number; won: number; lost: number; net_pnl_usd: string | null } | null;
  trades_list: OwnTrade[];
}

interface FamilyView {
  member: string;
  own_wallet?: OwnWallet;
  own_book?: OwnBook | null;
}

function short(address: string): string {
  return `${address.slice(0, 4)}…${address.slice(-4)}`;
}

/**
 * The member's OWN Solana wallet (stage 1, 2026-09-25): an address to deposit
 * to, its balance read from chain, and a way out that can only reach Karthik's
 * address. It does not trade yet; Karthik switches that on later.
 */
function OwnWalletPanel({ member, wallet, book, isOwner, onDone }: {
  member: string;
  wallet: OwnWallet;
  book: OwnBook | null | undefined;
  isOwner: boolean;
  onDone: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [ticket, setTicket] = useState<string | null>(null);
  const own = useMutation({
    mutationFn: (next: { enabled: boolean; ticket: string }) =>
      api.post(`/real-wallet/family/${member.toLowerCase()}/own-settings`,
        { enabled: next.enabled, ticket_usd: next.ticket }),
    onSuccess: () => {
      setTicket(null);
      onDone();
    },
  });
  const [amount, setAmount] = useState("");
  const [armed, setArmed] = useState(false);
  const withdraw = useMutation({
    mutationFn: () =>
      api.post<{ signature: string; explorer: string; sol: string }>(
        `/real-wallet/family/${member.toLowerCase()}/withdraw`,
        { sol_amount: amount, confirmation_phrase: "WITHDRAW_TO_KARTHIK" },
        { skipAuthRetry: true },
      ),
    onSuccess: () => {
      setAmount("");
      setArmed(false);
      onDone();
    },
  });

  if (!wallet.address) {
    return (
      <section className="mt-5 rounded-lg border border-line p-4">
        <p className="text-label text-ink-3">Own wallet</p>
        <p className="mt-1 text-sm text-ink-2">{title(member)}&apos;s own wallet isn&apos;t set up yet.</p>
      </section>
    );
  }

  const address = wallet.address;
  return (
    <section className="mt-5 rounded-lg border border-accent/40 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-label text-accent">{title(member)}&apos;s own wallet</p>
        <span className={`rounded-full border px-2 py-0.5 text-xs ${
          book?.enabled ? "border-up/50 text-up" : "border-line text-ink-3"}`}>
          Trading: {book?.enabled ? "on" : "off"}
        </span>
      </div>

      <p className="mt-3 text-xs text-ink-3">Deposit SOL to this address</p>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <code className="break-all rounded-md bg-surface px-2 py-1 font-mono text-sm text-ink">
          {address}
        </code>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(address).then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            });
          }}
          className="rounded-md border border-line px-2.5 py-1 text-xs text-ink-2 hover:border-line-strong hover:text-ink"
        >
          {copied ? "Copied ✓" : "Copy"}
        </button>
        {wallet.explorer ? (
          <a href={wallet.explorer} target="_blank" rel="noreferrer" className="text-xs text-accent">
            View on Solscan
          </a>
        ) : null}
      </div>

      <p className="mt-4 text-xs text-ink-3">Balance</p>
      <p className="mt-1 text-xl font-medium tabular-nums text-ink">
        {wallet.balance_sol != null
          ? `${Number(wallet.balance_sol).toFixed(4)} SOL`
          : "Couldn’t read it just now"}
        {wallet.balance_usd != null ? (
          <span className="ml-2 text-sm text-ink-3">≈ {usd(wallet.balance_usd)}</span>
        ) : null}
      </p>

      {book ? (
        <div className="mt-4 border-t border-line pt-3">
          <p className="text-xs text-ink-3">Trading from this wallet</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <label className="text-ink-3" htmlFor={`own-ticket-${member}`}>Each trade</label>
            <select
              id={`own-ticket-${member}`}
              value={ticket ?? book.ticket_usd}
              disabled={!isOwner}
              onChange={(e) => setTicket(e.target.value)}
              className="rounded-md border border-line bg-canvas px-2 py-1 text-sm text-ink disabled:opacity-60"
            >
              {book.ticket_choices.map((t) => (
                <option key={t} value={t}>{usd(t)}</option>
              ))}
            </select>
            {book.enabled ? (
              <button
                type="button"
                disabled={own.isPending}
                onClick={() => own.mutate({ enabled: false, ticket: book.ticket_usd })}
                className="rounded-md border border-down/50 px-3 py-1 text-sm text-down"
              >
                Stop trading
              </button>
            ) : (
              <button
                type="button"
                disabled={own.isPending || !isOwner}
                onClick={() => own.mutate({ enabled: true, ticket: ticket ?? book.ticket_usd })}
                className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-canvas disabled:opacity-50"
              >
                Start trading
              </button>
            )}
            {isOwner && ticket && ticket !== book.ticket_usd && book.enabled ? (
              <button
                type="button"
                disabled={own.isPending}
                onClick={() => own.mutate({ enabled: true, ticket })}
                className="rounded-md border border-line px-3 py-1 text-sm text-ink-2"
              >
                Save size
              </button>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-ink-3">
            Buys only while Karthik&apos;s main wallet is also on — when he stops his, this
            one stops buying too.
          </p>
          {own.isError ? (
            <p className="mt-1 text-xs text-down">
              Not changed: {own.error instanceof ApiError ? own.error.message : "try again"}
            </p>
          ) : null}

          <div className="mt-3 grid grid-cols-3 gap-2 text-sm">
            <div>
              <p className="text-xs text-ink-3">Profit so far</p>
              <p className={`tabular-nums ${tone(book.since_first_trade?.net_pnl_usd)}`}>
                {book.since_first_trade ? usd(book.since_first_trade.net_pnl_usd) : "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-ink-3">Today</p>
              <p className={`tabular-nums ${tone(book.today_pnl_usd)}`}>{usd(book.today_pnl_usd)}</p>
            </div>
            <div>
              <p className="text-xs text-ink-3">Trades</p>
              <p className="tabular-nums text-ink">
                {book.since_first_trade
                  ? `${book.since_first_trade.trades} · ${book.since_first_trade.won} won`
                  : "0"}
                {book.open_positions ? ` · ${book.open_positions} open` : ""}
              </p>
            </div>
          </div>

          {book.trades_list.length ? (
            <ul className="mt-3 divide-y divide-line text-xs">
              {book.trades_list.slice(0, 20).map((t) => (
                <li key={`${t.mint}-${t.opened_at}`} className="flex justify-between gap-2 py-1.5">
                  <span className="font-mono text-ink-2">{short(t.mint)}</span>
                  <span className="text-ink-3">
                    {new Date(t.opened_at).toLocaleString(undefined, { timeZone: "Asia/Dubai",
                      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                  </span>
                  <span className="text-ink-3">{usd(t.cost_usd)}</span>
                  <span className={`tabular-nums ${tone(t.pnl_usd)}`}>
                    {t.status === "OPEN" ? "open" : usd(t.pnl_usd)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-xs text-ink-3">No trades from this wallet yet.</p>
          )}
        </div>
      ) : null}

      <div className="mt-4 border-t border-line pt-3">
        <p className="text-xs text-ink-3">
          Withdraw — it can only go to Karthik&apos;s address
          {wallet.withdraws_to ? ` (${short(wallet.withdraws_to)})` : ""}.
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            inputMode="decimal"
            placeholder="SOL"
            value={amount}
            onChange={(e) => {
              setAmount(e.target.value);
              setArmed(false);
            }}
            className="w-28 rounded-md border border-line bg-canvas px-2 py-1 text-sm text-ink"
            aria-label="Amount of SOL to send to Karthik"
          />
          {armed ? (
            <>
              <button
                type="button"
                disabled={withdraw.isPending}
                onClick={() => withdraw.mutate()}
                className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-canvas disabled:opacity-60"
              >
                {withdraw.isPending ? "Sending…" : `Yes, send ${amount} SOL to Karthik`}
              </button>
              <button type="button" onClick={() => setArmed(false)} className="text-sm text-ink-3">
                Cancel
              </button>
            </>
          ) : (
            <button
              type="button"
              disabled={!(Number(amount) > 0)}
              onClick={() => setArmed(true)}
              className="rounded-md border border-line px-3 py-1 text-sm text-ink-2 hover:text-ink disabled:opacity-50"
            >
              Send to Karthik
            </button>
          )}
        </div>
        {withdraw.isSuccess ? (
          <p className="mt-2 text-xs text-up">
            Sent {withdraw.data.sol} SOL.{" "}
            <a href={withdraw.data.explorer} target="_blank" rel="noreferrer" className="underline">
              See it on Solscan
            </a>
            . It is sent once and never retried.
          </p>
        ) : null}
        {withdraw.isError ? (
          <p className="mt-2 text-xs text-down">
            Not sent: {withdraw.error instanceof ApiError ? withdraw.error.message : "try again"}
          </p>
        ) : null}
      </div>
    </section>
  );
}

/** One user's page. The server answers only Karthik, signed in. */
export function FamilyMemberPage({ member }: { member: string }) {
  const key = member.toUpperCase();
  const known = FAMILY.includes(key);
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const view = useQuery({
    queryKey: ["real-wallet", "family", key],
    queryFn: () => api.get<FamilyView>(`/real-wallet/family/${key.toLowerCase()}`),
    enabled: known,
    refetchInterval: 30_000,
    retry: false,
  });

  if (!known) {
    return (
      <main>
        <p className="text-label text-accent">User wallets</p>
        <h1 className="mt-2 text-2xl font-medium text-ink">No such user wallet.</h1>
        <Link href="/real-wallet" className="mt-3 inline-block text-sm text-accent">
          Back to the real wallet
        </Link>
      </main>
    );
  }

  const refused = view.error instanceof ApiError && view.error.status === 403;
  const d = view.data;
  const isOwner = user?.role === "admin";

  return (
    <main>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-label text-accent">User wallets · Real wallet</p>
          <h1 className="mt-2 text-3xl font-medium text-ink">{title(key)}</h1>
        </div>
        <Link href="/real-wallet" className="text-sm text-ink-3 hover:text-ink">Real wallet</Link>
      </div>

      {view.isPending ? <p className="mt-4 text-sm text-ink-3">Reading…</p> : null}
      {refused ? (
        <p className="mt-4 text-sm text-ink-3">Only Karthik, signed in, can open this page.</p>
      ) : view.isError ? (
        <p className="mt-4 text-sm text-down">Could not read this wallet. Try again.</p>
      ) : null}

      {d?.own_wallet ? (
        <OwnWalletPanel
          member={key}
          wallet={d.own_wallet}
          book={d.own_book}
          isOwner={isOwner}
          onDone={() => void queryClient.invalidateQueries({ queryKey: ["real-wallet", "family", key] })}
        />
      ) : null}
    </main>
  );
}
