"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/hooks/use-auth";
import { ApiError, api } from "@/lib/api-client";

/**
 * FAMILY SHARES OF THE ONE REAL WALLET — and, from 2026-09-25, each member's
 * OWN wallet (address, balance, withdraw-to-Karthik; trading comes later).
 *
 * Jaya, Asha and Apoorva each own a slice of the real wallet's orders: their
 * own trade size, their own on/off, their own money. There is still one wallet
 * and one address; the backend adds each switched-on member's ticket to the
 * owner's order and splits the result.
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
        Each person has their own share of this wallet: their own trade size, their own
        on/off and their own money. There is still one wallet and one address.
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

interface FamilyTrade {
  mint: string;
  bought_at: string;
  sold_at: string | null;
  amount_usd: string;
  order_usd: string;
  state: "open" | "closed" | "void";
  pnl_usd: string | null;
  pct: string | null;
}

interface OwnWallet {
  address: string | null;
  explorer?: string;
  withdraws_to?: string | null;
  trading: boolean;
  balance_sol?: string | null;
  balance_usd?: string | null;
  balance_error?: string | null;
}

interface FamilyView {
  member: string;
  own_wallet?: OwnWallet;
  enabled: boolean;
  ticket_usd: string;
  ticket_choices: string[];
  combined_cap_usd: string;
  deposited_usd: string;
  withdrawn_usd: string;
  pnl_usd: string;
  balance_usd: string;
  in_trades_usd: string;
  available_usd: string;
  trades: number;
  wins: number;
  trades_list: FamilyTrade[];
  ledger: { kind: "deposit" | "withdrawal"; amount_usd: string; note: string | null; at: string }[];
}

function Figure({ label, value, hint, cls }: {
  label: string; value: string; hint?: string; cls?: string;
}) {
  return (
    <div className="rounded-lg border border-line p-3">
      <p className="text-label text-ink-3">{label}</p>
      <p className={`mt-1 text-xl font-medium tabular-nums ${cls ?? "text-ink"}`}>{value}</p>
      {hint ? <p className="mt-1 text-xs text-ink-3">{hint}</p> : null}
    </div>
  );
}

function short(address: string): string {
  return `${address.slice(0, 4)}…${address.slice(-4)}`;
}

/**
 * The member's OWN Solana wallet (stage 1, 2026-09-25): an address to deposit
 * to, its balance read from chain, and a way out that can only reach Karthik's
 * address. It does not trade yet; Karthik switches that on later.
 */
function OwnWalletPanel({ member, wallet, headers, onDone }: {
  member: string;
  wallet: OwnWallet;
  headers: Record<string, string> | undefined;
  onDone: () => void;
}) {
  const [copied, setCopied] = useState(false);
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
        <span className="rounded-full border border-line px-2 py-0.5 text-xs text-ink-3">
          Trading: {wallet.trading ? "on" : "off — Karthik switches it on"}
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

  const [draft, setDraft] = useState<{ enabled: boolean; ticket: string } | null>(null);
  const settings = useMutation({
    mutationFn: (next: { enabled: boolean; ticket: string }) =>
      api.post(`/real-wallet/family/${key.toLowerCase()}/settings`,
        { enabled: next.enabled, ticket_usd: next.ticket },
        { headers, skipAuthRetry: true }),
    onSuccess: () => {
      setDraft(null);
      void queryClient.invalidateQueries({ queryKey: ["real-wallet", "family", key] });
    },
  });

  const [money, setMoney] = useState({ kind: "deposit", amount: "", note: "" });
  const ledger = useMutation({
    mutationFn: () =>
      api.post(`/real-wallet/family/${key.toLowerCase()}/ledger`,
        { kind: money.kind, amount_usd: money.amount, note: money.note || null },
        { headers }),
    onSuccess: () => {
      setMoney({ kind: "deposit", amount: "", note: "" });
      void queryClient.invalidateQueries({ queryKey: ["real-wallet", "family", key] });
    },
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
  const current = draft ?? (d ? { enabled: d.enabled, ticket: d.ticket_usd } : null);
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
        <p className="mt-4 text-sm text-down">Could not read this share. Try again.</p>
      ) : null}

      {d ? (
        <>
          {d.own_wallet ? (
            <OwnWalletPanel
              member={key}
              wallet={d.own_wallet}
              headers={headers}
              onDone={() => void queryClient.invalidateQueries({ queryKey: ["real-wallet", "family", key] })}
            />
          ) : null}
          <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Figure label="Balance" value={usd(d.balance_usd)} cls={tone(d.pnl_usd)}
              hint={`${usd(d.deposited_usd)} in · ${usd(d.withdrawn_usd)} out`} />
            <Figure label="Profit" value={usd(d.pnl_usd)} cls={tone(d.pnl_usd)}
              hint={`${d.trades} trades · ${d.wins} wins`} />
            <Figure label="Free to trade" value={usd(d.available_usd)} />
            <Figure label="In trades now" value={usd(d.in_trades_usd)} />
          </div>

          <section className="mt-6 rounded-lg border border-line p-5">
            <p className="text-label text-ink-3">Trading</p>
            {current ? (
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-sm text-ink">
                  <input
                    type="checkbox"
                    checked={current.enabled}
                    onChange={(e) => setDraft({ ...current, enabled: e.target.checked })}
                  />
                  {current.enabled ? "On" : "Off"}
                </label>
                <label className="flex items-center gap-2 text-sm text-ink">
                  Trade size
                  <select
                    value={current.ticket}
                    onChange={(e) => setDraft({ ...current, ticket: e.target.value })}
                    className="h-9 rounded-md border border-line bg-transparent px-2 text-sm"
                  >
                    {d.ticket_choices.map((t) => (
                      <option key={t} value={t}>{usd(t)}</option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  disabled={!draft || settings.isPending}
                  onClick={() => draft && settings.mutate(draft)}
                  className="h-9 rounded-md border border-line px-4 text-sm text-ink disabled:opacity-50"
                >
                  {settings.isPending ? "Saving…" : "Save"}
                </button>
              </div>
            ) : null}
            <p className="mt-3 max-w-2xl text-xs text-ink-3">
              Trades the same coins as the main wallet, at the same moment, only while it
              is on. A trade is only taken when there is a whole trade size free. Everyone&apos;s
              orders on one coin add up, and the total is held to {usd(d.combined_cap_usd)}{" "}
              a coin, because above that this strategy loses money.
            </p>
            {settings.isError ? (
              <p className="mt-2 text-sm text-down" role="alert">Could not save. Try again.</p>
            ) : null}
          </section>

          <section className="mt-6 rounded-lg border border-line p-5">
            <p className="text-label text-ink-3">Money in and out</p>
            <p className="mt-1 max-w-2xl text-xs text-ink-3">
              This only records whose money it is. Send the SOL from your own address first;
              withdrawals still go only to your address, from the main wallet.
            </p>
            {isOwner ? (
              <form
                className="mt-3 flex flex-wrap items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (Number(money.amount) > 0) ledger.mutate();
                }}
              >
                <select
                  value={money.kind}
                  onChange={(e) => setMoney({ ...money, kind: e.target.value })}
                  className="h-9 rounded-md border border-line bg-transparent px-2 text-sm"
                >
                  <option value="deposit">Deposit</option>
                  <option value="withdrawal">Withdrawal</option>
                </select>
                <input
                  type="number" min="0.01" step="0.01" inputMode="decimal"
                  value={money.amount}
                  onChange={(e) => setMoney({ ...money, amount: e.target.value })}
                  placeholder="Amount in $"
                  className="h-9 w-32 rounded-md border border-line bg-transparent px-3 text-sm"
                />
                <input
                  value={money.note}
                  maxLength={200}
                  onChange={(e) => setMoney({ ...money, note: e.target.value })}
                  placeholder="Note (optional)"
                  className="h-9 w-48 rounded-md border border-line bg-transparent px-3 text-sm"
                />
                <button
                  type="submit"
                  disabled={!(Number(money.amount) > 0) || ledger.isPending}
                  className="h-9 rounded-md border border-line px-4 text-sm text-ink disabled:opacity-50"
                >
                  Record
                </button>
                {ledger.error ? (
                  <p className="w-full text-sm text-down" role="alert">
                    {ledger.error instanceof ApiError ? ledger.error.message : "Could not record it."}
                  </p>
                ) : null}
              </form>
            ) : (
              <p className="mt-3 text-sm text-ink-3">
                Only the wallet&apos;s owner, signed in, can record money in or out.
              </p>
            )}
            {d.ledger.length ? (
              <ul className="mt-4 space-y-1 text-sm">
                {d.ledger.map((e) => (
                  <li key={`${e.at}-${e.kind}`} className="flex gap-3 tabular-nums">
                    <span className="w-40 text-ink-3">{new Date(e.at).toLocaleString()}</span>
                    <span className={e.kind === "deposit" ? "text-up" : "text-down"}>
                      {e.kind === "deposit" ? "+" : "-"}{usd(e.amount_usd)}
                    </span>
                    <span className="text-ink-3">{e.note ?? ""}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>

          <section className="mt-6 rounded-lg border border-line p-5">
            <p className="text-label text-ink-3">Trades</p>
            {d.trades_list.length === 0 ? (
              <p className="mt-2 text-sm text-ink-3">No trades yet.</p>
            ) : (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-label text-ink-3">
                    <tr>
                      <th className="py-1 pr-3 text-left font-normal">bought</th>
                      <th className="py-1 pr-3 text-left font-normal">coin</th>
                      <th className="py-1 pr-3 text-right font-normal">{title(key)}&apos;s $</th>
                      <th className="py-1 pr-3 text-right font-normal">whole order</th>
                      <th className="py-1 text-right font-normal">result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.trades_list.map((t) => (
                      <tr key={`${t.mint}-${t.bought_at}`} className="border-t border-line/60">
                        <td className="py-1.5 pr-3 tabular-nums text-ink-3">
                          {new Date(t.bought_at).toLocaleString()}
                        </td>
                        <td className="py-1.5 pr-3 font-mono text-xs">{t.mint.slice(0, 8)}…</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums">{usd(t.amount_usd)}</td>
                        <td className="py-1.5 pr-3 text-right tabular-nums text-ink-3">
                          {usd(t.order_usd)}
                        </td>
                        <td className={`py-1.5 text-right tabular-nums ${tone(t.pnl_usd)}`}>
                          {t.state === "closed"
                            ? `${usd(t.pnl_usd)} (${Number(t.pct) >= 0 ? "+" : ""}${t.pct}%)`
                            : t.state === "open" ? "open" : "not filled"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
