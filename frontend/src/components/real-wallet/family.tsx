"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useAuth } from "@/hooks/use-auth";
import { ApiError, api } from "@/lib/api-client";

import {
  SinceFirstTradeCard,
  TradesTable,
  type Position,
  type SinceFirstTrade,
} from "./trades";

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

/*
 * THE LOCKS: USER 1-7 (the family investment, 2026-09-28) need the family
 * investment password; USER 8-10 and the fees need the users password. The
 * server keeps only the hashes and answers a right one with a 12-hour token
 * covering every lock this tab has opened, kept in sessionStorage, so closing
 * the tab locks them again.
 */
const TOKEN_KEY = "users-token";

export function readUsersToken(): string | null {
  try {
    return window.sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeUsersToken(token: string | null): void {
  try {
    if (token) window.sessionStorage.setItem(TOKEN_KEY, token);
    else window.sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // A private window without storage still works for this page view.
  }
}

/** Headers for a user-wallet call: the token when this tab has one. */
/*
 * KARTHIK'S DEVICES ONLY (2026-10-01: "this jupiter box should only visible to
 * my macbook"). A browser opens JUPITER only while it holds a device key the
 * server knows; the key arrives once, through a pairing link
 * (`/real-wallet?jupiter-pair=<key>`), and is kept in localStorage. Without it
 * the box is not drawn and the server answers every JUPITER route with 404.
 */
const DEVICE_KEY = "jupiter-device";
const PAIR_PARAM = "jupiter-pair";

export function readDeviceKey(): string | null {
  try {
    return window.localStorage.getItem(DEVICE_KEY);
  } catch {
    return null;
  }
}

/** Keep a key handed over by the pairing link, and take it out of the URL. */
function pairFromUrl(): void {
  try {
    const url = new URL(window.location.href);
    const key = url.searchParams.get(PAIR_PARAM);
    if (!key) return;
    window.localStorage.setItem(DEVICE_KEY, key);
    url.searchParams.delete(PAIR_PARAM);
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  } catch {
    // No storage: this browser cannot be paired.
  }
}

/** This browser's device key, once mounted (never during the server render). */
function useDeviceKey(): string | null | undefined {
  const [key, setKey] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    pairFromUrl();
    setKey(readDeviceKey());
  }, []);
  return key;
}

function usersHeaders(): Record<string, string> | undefined {
  if (typeof window === "undefined") return undefined;
  const token = readUsersToken();
  const device = readDeviceKey();
  const headers: Record<string, string> = {};
  if (token) headers["X-Users-Token"] = token;
  if (device) headers["X-Jupiter-Device"] = device;
  return Object.keys(headers).length ? headers : undefined;
}

/** USER 1-7: the family investment, behind its own password (2026-09-28). */
const INVESTMENT = FAMILY.slice(0, 7);
const OTHERS = FAMILY.slice(7);

/**
 * Either password. The tab's token goes along, so the answer keeps every lock
 * this tab has already opened.
 */
export function UsersUnlock({ onOpen, label = "Users password", id = "users-password" }: {
  onOpen: () => void;
  label?: string;
  id?: string;
}) {
  const [password, setPassword] = useState("");
  const unlock = useMutation({
    mutationFn: () =>
      api.post<{ token: string }>("/real-wallet/family/unlock", { password },
        { skipAuthRetry: true, headers: usersHeaders() }),
    onSuccess: (out) => {
      writeUsersToken(out.token);
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
      <label className="sr-only" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        type="password"
        autoComplete="current-password"
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
        {unlock.isPending ? "Checking…" : "Open"}
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

/** The ten user wallets on the real wallet page, for Karthik only. */
export function FamilySection() {
  // Only on Karthik's paired browsers (2026-10-01), signed in or not; the
  // JUPITER password opens the view and money actions still need his sign-in.
  const device = useDeviceKey();
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["real-wallet", "family"],
    queryFn: () => api.get<MembersView>("/real-wallet/family", { headers: usersHeaders() }),
    enabled: Boolean(device),
    refetchInterval: 60_000,
  });
  if (!device) return null;
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["real-wallet", "family"] });
  const rows = new Map(list.data?.members.map((m) => [m.member, m]) ?? []);
  const bands = new Map((list.data?.band_choices ?? []).map((b) => [b.key, b.label]));
  const fees = list.data?.fees;
  const unlocked = Boolean(list.data?.unlocked);
  const investmentOpen = Boolean(list.data?.investment_unlocked);
  const lock = (
    <button
      type="button"
      onClick={() => {
        writeUsersToken(null);
        refresh();
      }}
      className="text-xs text-ink-3 hover:text-ink"
    >
      Lock
    </button>
  );
  const link = (m: string) => {
    const row = rows.get(m);
    return (
      <Link
        key={m}
        href={`/real-wallet/family/${m.toLowerCase()}`}
        data-testid={`wallet-${m}`}
        className="flex min-w-[11rem] flex-col gap-0.5 rounded-md border border-line px-3 py-2 text-sm hover:border-accent"
      >
        <span className="flex items-center justify-between gap-3 font-medium text-ink">
          {title(m)}
          {row ? (
            <span className={`text-xs font-normal ${row.enabled ? "text-up" : "text-ink-3"}`}>
              {row.enabled ? "● on" : "off"}
            </span>
          ) : null}
        </span>
        {row?.ticket_usd ? (
          <span className="text-xs text-ink-2">
            {usd(row.ticket_usd).replace(".00", "")} trades ·{" "}
            {row.band && row.band !== "any" ? `${bands.get(row.band) ?? row.band} coins` : "any coin"}
          </span>
        ) : null}
        {row ? (
          <span className="text-xs text-ink-3">
            {Number(row.fee_rate) > 0 ? `${pct(row.fee_rate)} fee` : "no fee"}
          </span>
        ) : null}
      </Link>
    );
  };
  // JUPITER (Karthik, 2026-09-29: "put all this inside JUPITER folder with
  // password, i dont want to display all this"): closed, the section is one
  // box and a password field — no plan, no wallets, not even their count. The
  // password is the family investment one.
  if (!investmentOpen) {
    return (
      <section className="mt-6 rounded-lg border border-line p-5" data-testid="jupiter">
        <p className="text-label text-accent">JUPITER</p>
        <p className="mt-1 text-xs text-ink-3">Locked. Enter the password to open.</p>
        <UsersUnlock onOpen={refresh} label="JUPITER password" id="jupiter-password" />
      </section>
    );
  }
  return (
    <section className="mt-6 rounded-lg border border-line p-5" data-testid="jupiter">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-label text-accent">JUPITER</p>
        {lock}
      </div>
      <p className="mt-1 max-w-2xl text-sm text-ink-3">
        Family investment. Each wallet has its own address, balance, trade size, coin size and
        on/off, and copies your strategy. Withdrawals can only go to your address. Deposit a couple
        of dollars over a wallet&apos;s trade size for network fees; a wallet trades only after you
        press Start on its page.
      </p>
      <div className="mt-4 rounded-md border border-accent/40 p-4" data-testid="investment-area">
        <p className="text-sm font-medium text-ink">USER 1 – USER 7</p>
        <div className="mt-3 flex flex-wrap gap-2">{INVESTMENT.map(link)}</div>
      </div>

      <SideBySide rows={list.data?.compare ?? []} />

      <div className="mt-5 rounded-md border border-line p-4" data-testid="users-locked-area">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm font-medium text-ink">USER 8 – USER 10 and fees</p>
        </div>
        {!unlocked ? (
          <>
            <p className="mt-1 text-xs text-ink-3">Locked. Enter the users password to open.</p>
            <UsersUnlock onOpen={refresh} />
          </>
        ) : (
          <>
            {fees ? (
              <div className="mt-3 flex flex-wrap gap-x-8 gap-y-2 text-sm">
                <div>
                  <p className="text-xs text-ink-3">Profit fees collected</p>
                  <p className="text-lg font-medium tabular-nums text-up">{usd(fees.collected_usd)}</p>
                </div>
                <div>
                  <p className="text-xs text-ink-3">Waiting to collect</p>
                  <p className="text-lg font-medium tabular-nums text-ink">{usd(fees.waiting_usd)}</p>
                </div>
                {fees.to_check > 0 ? (
                  <p className="self-end text-xs text-down">
                    {fees.to_check} fee send{fees.to_check === 1 ? "" : "s"} to check on Solscan
                  </p>
                ) : null}
              </div>
            ) : null}
            <div className="mt-4 flex flex-wrap gap-2">{OTHERS.map(link)}</div>
          </>
        )}
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

interface WalletDay {
  day: string;
  running: boolean;
  pnl_usd: string;
  trades: number;
  won: number;
}

interface OwnBook {
  enabled: boolean;
  ticket_usd: string;
  ticket_choices: string[];
  band?: string;
  band_choices?: BandChoice[];
  today_pnl_usd: string | null;
  open_positions: number;
  open_trade_usd?: string | null;
  since_first_trade: SinceFirstTrade | null;
  days?: WalletDay[];
  positions?: Position[];
}

interface FeeMonth {
  month: string;
  profit_usd: string;
  high_water_usd: string;
  rate: string;
  fee_usd: string;
  status: "none" | "due" | "sending" | "paid" | "uncertain";
  explorer: string | null;
}

interface FamilyView {
  member: string;
  own_wallet?: OwnWallet;
  own_book?: OwnBook | null;
  fee?: { rate: string; months: FeeMonth[] };
}

interface FeeTotals {
  collected_usd: string;
  waiting_usd: string;
  to_check: number;
  fee_address: string | null;
}

interface BandChoice {
  key: string;
  label: string;
}

interface MemberRow {
  member: string;
  label: string;
  fee_rate: string | null;
  enabled?: boolean;
  ticket_usd?: string | null;
  band?: string;
  address?: string | null;
}

/** One wallet's closed trades, today (Dubai) and since it began. */
interface CompareRow {
  label: string;
  today_trades: number;
  today_won: number;
  today_pnl_usd: string;
  today_avg_pct: string | null;
  all_trades: number;
  all_pnl_usd: string;
  all_avg_pct: string | null;
}

interface MembersView {
  compare?: CompareRow[];
  members: MemberRow[];
  band_choices?: BandChoice[];
  unlocked?: boolean;
  investment_unlocked?: boolean;
  fees?: FeeTotals;
}

function pct(rate: string | null | undefined): string {
  return `${Math.round(Number(rate ?? 0) * 100)}%`;
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
  const [band, setBand] = useState<string | null>(null);
  const own = useMutation({
    mutationFn: (next: { enabled: boolean; ticket: string }) =>
      api.post(`/real-wallet/family/${member.toLowerCase()}/own-settings`,
        { enabled: next.enabled, ticket_usd: next.ticket, band: band ?? book?.band },
        { headers: usersHeaders() }),
    onSuccess: () => {
      setTicket(null);
      setBand(null);
      onDone();
    },
  });
  // Typed in dollars (Karthik, 2026-10-01), sent as SOL at the price the
  // balance was just read at; the confirm button names both.
  const [amount, setAmount] = useState("");
  const [armed, setArmed] = useState(false);
  const solPrice = Number(wallet.balance_usd) / Number(wallet.balance_sol);
  const solAmount = Number(amount) > 0 && solPrice > 0
    ? (Math.floor((Number(amount) / solPrice) * 1e6) / 1e6).toString()
    : null;
  const withdraw = useMutation({
    mutationFn: () =>
      api.post<{ signature: string; explorer: string; sol: string }>(
        `/real-wallet/family/${member.toLowerCase()}/withdraw`,
        { sol_amount: solAmount, confirmation_phrase: "WITHDRAW_TO_KARTHIK" },
        { skipAuthRetry: true, headers: usersHeaders() },
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
        {wallet.balance_usd != null
          ? usd(wallet.balance_usd)
          : wallet.balance_sol != null
            ? `${Number(wallet.balance_sol).toFixed(4)} SOL`
            : "Couldn’t read it just now"}
        {wallet.balance_usd != null && wallet.balance_sol != null ? (
          <span className="ml-2 text-sm text-ink-3">{Number(wallet.balance_sol).toFixed(4)} SOL</span>
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
            {book.band_choices?.length ? (
              <>
                <label className="text-ink-3" htmlFor={`own-band-${member}`}>Coins worth</label>
                <select
                  id={`own-band-${member}`}
                  value={band ?? book.band ?? "any"}
                  disabled={!isOwner}
                  onChange={(e) => setBand(e.target.value)}
                  className="rounded-md border border-line bg-canvas px-2 py-1 text-sm text-ink disabled:opacity-60"
                >
                  {book.band_choices.map((b) => (
                    <option key={b.key} value={b.key}>{b.label}</option>
                  ))}
                </select>
              </>
            ) : null}
            {book.enabled ? (
              <button
                type="button"
                disabled={own.isPending || !isOwner}
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
            {isOwner && book.enabled && ((ticket && ticket !== book.ticket_usd)
              || (band && band !== book.band)) ? (
              <button
                type="button"
                disabled={own.isPending}
                onClick={() => own.mutate({ enabled: true, ticket: ticket ?? book.ticket_usd })}
                className="rounded-md border border-line px-3 py-1 text-sm text-ink-2"
              >
                Save
              </button>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-ink-3">
            Buys only while Karthik&apos;s main wallet is also on — when he stops his, this
            one stops buying too. A coin outside its market-cap range is skipped.
          </p>
          {own.isError ? (
            <p className="mt-1 text-xs text-down">
              Not changed: {own.error instanceof ApiError ? own.error.message : "try again"}
            </p>
          ) : null}

        </div>
      ) : null}

      {!isOwner ? (
        <p className="mt-4 border-t border-line pt-3 text-xs text-ink-3" data-testid="view-only">
          Sign in as Karthik to start, stop or resize.
        </p>
      ) : null}
      {/* Karthik, 2026-10-01: withdraw like the main wallet. JUPITER is on his
          paired devices only, and the money can only reach his address. */}
      <div className="mt-4 border-t border-line pt-3">
        <p className="text-xs text-ink-3">
          Withdraw — it can only go to Karthik&apos;s address
          {wallet.withdraws_to ? ` (${short(wallet.withdraws_to)})` : ""}.
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            inputMode="decimal"
            placeholder="$"
            value={amount}
            onChange={(e) => {
              setAmount(e.target.value);
              setArmed(false);
            }}
            className="w-28 rounded-md border border-line bg-canvas px-2 py-1 text-sm text-ink"
            aria-label="Dollars to send to Karthik"
          />
          {armed && solAmount ? (
            <>
              <button
                type="button"
                disabled={withdraw.isPending}
                onClick={() => withdraw.mutate()}
                className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-canvas disabled:opacity-60"
              >
                {withdraw.isPending
                  ? "Sending…"
                  : `Yes, send ${usd(amount)} (${solAmount} SOL) to Karthik`}
              </button>
              <button type="button" onClick={() => setArmed(false)} className="text-sm text-ink-3">
                Cancel
              </button>
            </>
          ) : (
            <button
              type="button"
              disabled={!solAmount}
              onClick={() => setArmed(true)}
              className="rounded-md border border-line px-3 py-1 text-sm text-ink-2 hover:text-ink disabled:opacity-50"
            >
              Send to Karthik
            </button>
          )}
        </div>
        {Number(amount) > 0 && !solAmount ? (
          <p className="mt-2 text-xs text-ink-3">
            Can&apos;t read the SOL price just now, so the dollars can&apos;t be converted. Try again shortly.
          </p>
        ) : null}
        {withdraw.isSuccess ? (
          <p className="mt-2 text-xs text-up">
            Sent {withdraw.data.sol} SOL
            {solPrice > 0 ? ` (≈ ${usd(Number(withdraw.data.sol) * solPrice)})` : ""}.{" "}
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

const FEE_STATUS: Record<FeeMonth["status"], string> = {
  none: "No new profit",
  due: "Due",
  sending: "Sending — check Solscan",
  paid: "Paid",
  uncertain: "Sent? Check Solscan",
};

/** The user's profit fee: the rate, every month, and your Collect button. */
function FeePanel({ member, fee, onDone, canCollect = true }: {
  member: string;
  fee: { rate: string; months: FeeMonth[] };
  onDone: () => void;
  canCollect?: boolean;
}) {
  const [armed, setArmed] = useState(false);
  const due = fee.months
    .filter((m) => m.status === "due")
    .reduce((sum, m) => sum + Number(m.fee_usd), 0);
  const collect = useMutation({
    mutationFn: () =>
      api.post<{ status: string; usd: string; sol: string; explorer: string }>(
        `/real-wallet/family/${member.toLowerCase()}/collect-fee`,
        { confirmation_phrase: "COLLECT_FEE" },
        { skipAuthRetry: true, headers: usersHeaders() },
      ),
    onSuccess: () => {
      setArmed(false);
      onDone();
    },
  });
  const charged = Number(fee.rate) > 0;
  return (
    <section className="mt-5 rounded-lg border border-line p-4">
      <p className="text-label text-ink-3">Profit fee</p>
      <p className="mt-1 text-sm text-ink-2">
        {charged
          ? `${pct(fee.rate)} of the new trading profit each month (UTC), above this wallet’s best total so far. A month that loses, or only wins a loss back, pays nothing. Deposits and withdrawals never count as profit.`
          : "No profit fee on this wallet."}
      </p>
      {fee.months.length ? (
        <table className="mt-3 w-full text-left text-sm tabular-nums">
          <thead className="text-xs text-ink-3">
            <tr>
              <th className="py-1 font-normal">Month</th>
              <th className="py-1 font-normal">Profit to date</th>
              <th className="py-1 font-normal">Fee</th>
              <th className="py-1 font-normal">Status</th>
            </tr>
          </thead>
          <tbody>
            {fee.months.map((m) => (
              <tr key={m.month} className="border-t border-line">
                <td className="py-1">{m.month}</td>
                <td className={`py-1 ${tone(m.profit_usd)}`}>{usd(m.profit_usd)}</td>
                <td className="py-1">{usd(m.fee_usd)}</td>
                <td className="py-1 text-ink-3">
                  {m.explorer ? (
                    <a href={m.explorer} target="_blank" rel="noreferrer" className="text-accent">
                      {FEE_STATUS[m.status]}
                    </a>
                  ) : (
                    FEE_STATUS[m.status]
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="mt-2 text-xs text-ink-3">The first month is worked out on the 1st.</p>
      )}
      {due > 0 && canCollect ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {armed ? (
            <>
              <button
                type="button"
                onClick={() => collect.mutate()}
                disabled={collect.isPending}
                className="h-9 rounded-md border border-accent px-4 text-sm text-accent disabled:opacity-50"
              >
                {collect.isPending ? "Sending…" : `Yes, collect ${usd(due)}`}
              </button>
              <button type="button" onClick={() => setArmed(false)} className="text-sm text-ink-3">
                Cancel
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setArmed(true)}
              className="h-9 rounded-md border border-line px-4 text-sm text-ink"
            >
              Collect fee ({usd(due)})
            </button>
          )}
        </div>
      ) : null}
      {collect.isError ? (
        <p className="mt-2 text-xs text-down">
          Not sent: {collect.error instanceof ApiError ? collect.error.message : "try again"}
        </p>
      ) : null}
    </section>
  );
}

/** One user's page. The server answers only Karthik, signed in. */
const signedPct = (v: string | null) =>
  v == null ? "—" : `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(2)}%`;

/** Every wallet's results next to the others (Karthik, 2026-10-01). */
export function SideBySide({ rows }: { rows: CompareRow[] }) {
  if (!rows.length) return null;
  const head = "py-1.5 px-2 text-right font-normal";
  return (
    <div className="mt-4 rounded-md border border-line p-4" data-testid="side-by-side">
      <p className="text-sm font-medium text-ink">Side by side</p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-[12px] tabular-nums">
          <thead className="text-[11px] uppercase tracking-wider text-ink-3">
            <tr>
              <th className="py-1.5 pr-2 text-left font-normal">Wallet</th>
              <th className={head}>Today</th>
              <th className={head}>Trades · won</th>
              <th className={head}>Avg / trade</th>
              <th className={head}>All time</th>
              <th className={head}>Trades</th>
              <th className="py-1.5 pl-2 text-right font-normal">Avg / trade</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="border-t border-line">
                <td className="py-1.5 pr-2 text-ink">{r.label}</td>
                <td className={`px-2 text-right ${tone(r.today_pnl_usd)}`}>
                  {r.today_trades ? `${Number(r.today_pnl_usd) >= 0 ? "+" : ""}${usd(r.today_pnl_usd)}` : "—"}
                </td>
                <td className="px-2 text-right text-ink-2">
                  {r.today_trades ? `${r.today_trades} · ${r.today_won}` : "0"}
                </td>
                <td className={`px-2 text-right ${tone(r.today_avg_pct)}`}>{signedPct(r.today_avg_pct)}</td>
                <td className={`px-2 text-right ${tone(r.all_pnl_usd)}`}>
                  {r.all_trades ? `${Number(r.all_pnl_usd) >= 0 ? "+" : ""}${usd(r.all_pnl_usd)}` : "—"}
                </td>
                <td className="px-2 text-right text-ink-2">{r.all_trades}</td>
                <td className={`pl-2 text-right ${tone(r.all_avg_pct)}`}>{signedPct(r.all_avg_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-ink-3">
        Closed trades only, after fees. &ldquo;Today&rdquo; runs from midnight Dubai. Wallets buy the
        same coins a few seconds apart, so each later one usually makes a little less.
      </p>
    </div>
  );
}

/** "30 Sep" in Dubai. */
function dayLabel(day: string): string {
  return new Date(`${day}T12:00:00Z`)
    .toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "Asia/Dubai" })
    .replace("Sept", "Sep");
}

/**
 * The same page as the main real wallet (Karthik, 2026-09-30): what the
 * wallet is worth with its open trade, today, profit per day in dollars,
 * since the first trade, and every trade open and closed.
 */
export function WalletDashboard({ book, wallet }: { book: OwnBook; wallet?: OwnWallet }) {
  const open = Number(book.open_trade_usd ?? 0);
  const free = wallet?.balance_usd != null ? Number(wallet.balance_usd) : null;
  return (
    <div data-testid="wallet-dashboard">
      <section className="mt-6 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-line p-4">
          <p className="text-label text-ink-3">Worth now</p>
          <p className="mt-1 text-2xl tabular-nums text-ink">
            {free != null ? usd(free + open) : "—"}
          </p>
          <p className="mt-1 text-xs text-ink-3">
            {open > 0 ? `incl. ${usd(open)} in an open trade` : "nothing held right now"}
          </p>
        </div>
        <div className="rounded-lg border border-line p-4">
          <p className="text-label text-ink-3">Today (Dubai)</p>
          <p className={`mt-1 text-2xl tabular-nums ${tone(book.today_pnl_usd)}`}>
            {usd(book.today_pnl_usd)}
          </p>
        </div>
        <div className="rounded-lg border border-line p-4">
          <p className="text-label text-ink-3">Open now</p>
          <p className="mt-1 text-2xl tabular-nums text-ink">{book.open_positions}</p>
        </div>
      </section>

      {book.days?.length ? (
        <div className="-mx-1 mt-4 flex gap-2 overflow-x-auto px-1 pb-1" data-testid="wallet-days">
          {book.days.map((d) => (
            <div
              key={d.day}
              className={`min-w-[104px] shrink-0 rounded-lg border p-2 ${
                d.running ? "border-dashed border-line" : "border-line"
              }`}
            >
              <div className="text-[10px] uppercase tracking-wider text-ink-3">
                {dayLabel(d.day)}
                {d.running ? " · so far" : ""}
              </div>
              <div className={`mt-0.5 text-base font-semibold tabular-nums ${tone(d.pnl_usd)}`}>
                {Number(d.pnl_usd) >= 0 ? "+" : ""}
                {usd(d.pnl_usd)}
              </div>
              <div className="text-[11px] tabular-nums text-ink-3">
                {d.trades} trades{d.trades ? ` · ${d.won} won` : ""}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      <SinceFirstTradeCard since={book.since_first_trade} />
      <TradesTable positions={book.positions ?? []} inDollars />
    </div>
  );
}

export function FamilyMemberPage({ member }: { member: string }) {
  const key = member.toUpperCase();
  const device = useDeviceKey();
  const known = FAMILY.includes(key) && Boolean(device);
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const view = useQuery({
    queryKey: ["real-wallet", "family", key],
    queryFn: () =>
      api.get<FamilyView>(`/real-wallet/family/${key.toLowerCase()}`, {
        headers: usersHeaders(),
        skipAuthRetry: true,
      }),
    enabled: known,
    refetchInterval: 30_000,
    retry: false,
  });

  if (device === undefined) return null;  // still reading this browser's key
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
  const needsPassword =
    view.error instanceof ApiError && view.error.status === 401;
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
      {needsPassword ? (
        <div className="mt-4">
          <p className="text-sm text-ink-3">
            Enter the {INVESTMENT.includes(key) ? "JUPITER" : "users"} password to open {title(key)}.
          </p>
          <UsersUnlock
            onOpen={() => void view.refetch()}
            label={INVESTMENT.includes(key) ? "JUPITER password" : "Users password"}
          />
        </div>
      ) : refused ? (
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
      {d?.own_book ? <WalletDashboard book={d.own_book} wallet={d.own_wallet} /> : null}
      {d?.fee ? (
        <FeePanel
          member={key}
          fee={d.fee}
          canCollect={isOwner}
          onDone={() => void queryClient.invalidateQueries({ queryKey: ["real-wallet", "family"] })}
        />
      ) : null}
    </main>
  );
}
