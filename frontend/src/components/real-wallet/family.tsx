"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/hooks/use-auth";
import { ApiError, api } from "@/lib/api-client";

/**
 * THE FAMILY'S OWN WALLETS.
 *
 * Jaya, Asha and Apoorva each have a Solana wallet of their own: an address
 * to deposit to, a balance, a withdrawal that can only reach Karthik, and
 * trading on its own switch (off until Karthik, signed in, starts it; anyone
 * with the password can stop it). The shares of the main wallet these pages
 * used to show were removed on 2026-09-25.
 *
 * The password is checked on the server, which keeps only a hash of it. What
 * comes back is a token for ONE member, kept in this tab's sessionStorage, so
 * closing the tab locks the page again.
 */

export const FAMILY = ["JAYA", "ASHA", "APOORVA"] as const;
export type Member = (typeof FAMILY)[number];

const TOKEN_KEY = (m: string) => `family-token:${m.toUpperCase()}`;

function readToken(member: string): string | null {
  try {
    return window.sessionStorage.getItem(TOKEN_KEY(member));
  } catch {
    return null;
  }
}

function writeToken(member: string, token: string | null): void {
  try {
    if (token) window.sessionStorage.setItem(TOKEN_KEY(member), token);
    else window.sessionStorage.removeItem(TOKEN_KEY(member));
  } catch {
    // A private window without storage still works for this page view.
  }
}

function title(member: string): string {
  return member.charAt(0) + member.slice(1).toLowerCase();
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

/** The password box. On success the token is stored and `onOpen` runs. */
export function Unlock({ member, onOpen }: { member: string; onOpen: () => void }) {
  const [password, setPassword] = useState("");
  const unlock = useMutation({
    mutationFn: () =>
      api.post<{ token: string }>(
        "/real-wallet/family/unlock",
        { member, password },
        // A 401 here is a wrong password, not an expired sign-in.
        { skipAuthRetry: true },
      ),
    onSuccess: (out) => {
      writeToken(member, out.token);
      setPassword("");
      onOpen();
    },
  });
  const error = unlock.error;
  return (
    <form
      className="mt-3 flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (password) unlock.mutate();
      }}
    >
      <label className="sr-only" htmlFor={`family-password-${member}`}>
        Password for {title(member)}
      </label>
      <input
        id={`family-password-${member}`}
        type="password"
        autoComplete="current-password"
        autoFocus
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        className="h-9 w-48 rounded-md border border-line bg-transparent px-3 text-sm text-ink"
      />
      <button
        type="submit"
        disabled={!password || unlock.isPending}
        className="h-9 rounded-md border border-line px-4 text-sm text-ink disabled:opacity-50"
      >
        {unlock.isPending ? "Checking…" : "Log in"}
      </button>
      {error ? (
        <p className="w-full text-sm text-down" role="alert">
          {error instanceof ApiError && error.status === 429
            ? "Too many wrong passwords. Wait ten minutes."
            : error instanceof ApiError && error.status === 401
              ? "Wrong password."
              : "Could not check the password. Try again."}
        </p>
      ) : null}
    </form>
  );
}

/** The three family members on the real wallet page. */
export function FamilySection() {
  const router = useRouter();
  const [asking, setAsking] = useState<Member | null>(null);
  return (
    <section className="mt-6 rounded-lg border border-line p-5">
      <p className="text-label text-ink-3">Family</p>
      <p className="mt-1 max-w-2xl text-sm text-ink-3">
        Each person has a Solana wallet of their own: its own address, balance, trade
        size and on/off. Withdrawals from it can only go to Karthik&apos;s address.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        {FAMILY.map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => {
              if (readToken(m)) router.push(`/real-wallet/family/${m.toLowerCase()}`);
              else setAsking(asking === m ? null : m);
            }}
            aria-expanded={asking === m}
            className={`h-10 rounded-md border px-5 text-sm font-medium ${
              asking === m ? "border-accent text-accent" : "border-line text-ink"
            }`}
          >
            {title(m)}
          </button>
        ))}
      </div>
      {asking ? (
        <Unlock
          key={asking}
          member={asking}
          onOpen={() => router.push(`/real-wallet/family/${asking.toLowerCase()}`)}
        />
      ) : null}
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
function OwnWalletPanel({ member, wallet, book, isOwner, headers, onDone }: {
  member: string;
  wallet: OwnWallet;
  book: OwnBook | null | undefined;
  isOwner: boolean;
  headers: Record<string, string> | undefined;
  onDone: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [ticket, setTicket] = useState<string | null>(null);
  const own = useMutation({
    mutationFn: (next: { enabled: boolean; ticket: string }) =>
      api.post(`/real-wallet/family/${member.toLowerCase()}/own-settings`,
        { enabled: next.enabled, ticket_usd: next.ticket }, { headers }),
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
        { headers, skipAuthRetry: true },
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
          {!isOwner ? (
            <p className="mt-1 text-xs text-ink-3">
              Only Karthik, signed in, can start this wallet or change its size. Anyone can stop it.
            </p>
          ) : null}
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

/** One member's page. Asks for the password when this tab has no token. */
export function FamilyMemberPage({ member }: { member: string }) {
  const key = member.toUpperCase();
  const known = (FAMILY as readonly string[]).includes(key);
  // Read after mount, not during render: the server has no sessionStorage,
  // and reading it while rendering would make the two disagree.
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setToken(readToken(key));
    setReady(true);
  }, [key]);
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const headers = token ? { "X-Family-Token": token } : undefined;

  const view = useQuery({
    queryKey: ["real-wallet", "family", key, token],
    queryFn: () =>
      api.get<FamilyView>(`/real-wallet/family/${key.toLowerCase()}`, {
        headers,
        skipAuthRetry: true,
      }),
    enabled: known && Boolean(token),
    refetchInterval: 30_000,
    retry: false,
  });

  const lock = () => {
    writeToken(key, null);
    setToken(null);
  };

  if (!known) {
    return (
      <main>
        <p className="text-label text-accent">Family</p>
        <h1 className="mt-2 text-2xl font-medium text-ink">No such family member.</h1>
        <Link href="/real-wallet" className="mt-3 inline-block text-sm text-accent">
          Back to the real wallet
        </Link>
      </main>
    );
  }

  if (!ready) {
    return (
      <main>
        <p className="text-label text-accent">Family · Real wallet</p>
        <p className="mt-2 text-sm text-ink-3">Reading…</p>
      </main>
    );
  }

  const expired = view.error instanceof ApiError && view.error.status === 401;
  if (!token || expired) {
    return (
      <main>
        <p className="text-label text-accent">Family · Real wallet</p>
        <h1 className="mt-2 text-3xl font-medium text-ink">{title(key)}</h1>
        <p className="mt-2 text-sm text-ink-3">
          {expired ? "This login has ended. " : ""}Enter the family password to open{" "}
          {title(key)}&apos;s share.
        </p>
        <Unlock member={key} onOpen={() => setToken(readToken(key))} />
      </main>
    );
  }

  const d = view.data;
  const isOwner = user?.role === "admin";

  return (
    <main>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-label text-accent">Family · Real wallet</p>
          <h1 className="mt-2 text-3xl font-medium text-ink">{title(key)}</h1>
        </div>
        <div className="flex gap-3 text-sm">
          <Link href="/real-wallet" className="text-ink-3 hover:text-ink">Real wallet</Link>
          <button type="button" onClick={lock} className="text-ink-3 hover:text-ink">
            Lock
          </button>
        </div>
      </div>

      {view.isPending ? <p className="mt-4 text-sm text-ink-3">Reading…</p> : null}
      {view.isError && !expired ? (
        <p className="mt-4 text-sm text-down">Could not read this wallet. Try again.</p>
      ) : null}

      {d ? (
        <>
          {d.own_wallet ? (
            <OwnWalletPanel
              member={key}
              wallet={d.own_wallet}
              book={d.own_book}
              isOwner={isOwner}
              headers={headers}
              onDone={() => void queryClient.invalidateQueries({ queryKey: ["real-wallet", "family", key] })}
            />
          ) : null}
        </>
      ) : null}
    </main>
  );
}
