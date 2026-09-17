"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useAuth } from "@/hooks/use-auth";
import { ApiError, api } from "@/lib/api-client";

/**
 * The real wallet: what it holds, what it trades, and the two switches.
 *
 * Who may do what is the server's decision (2026-09-16): reading, STOP and
 * withdrawing need only the site code; START needs the administrator account.
 * The page shows Start to a signed-in administrator and a sign-in link to
 * everyone else — the server refuses a Start from anyone else regardless.
 */

type Position = {
  id: string;
  mint_address: string;
  symbol: string | null;
  status: string;
  strategy_id: string | null;
  quantity: string;
  cost_usd: string;
  spent: string | null;
  received: string | null;
  realised_gross_pnl_usd: string | null;
  realised_net_pnl_usd: string | null;
  exit_reason: string | null;
  exit_state: string | null;
  opened_at: string;
  closed_at: string | null;
  entry_signature: string | null;
  exit_signature: string | null;
};

/** Every real trade since the first, from the server — not the latest 50. */
type SinceFirstTrade = {
  first_trade_at: string;
  trades: number;
  won: number;
  lost: number;
  open: number;
  net_pnl_usd: string;
  traded_usd: string;
  average_return_pct: string | null;
  start_balance_sol: string | null;
  start_value_usd: string | null;
  return_pct: string | null;
};

type WalletStatus = {
  public_key: string | null;
  network: "devnet" | "mainnet";
  rpc: { verified: boolean; error: string | null };
  sol_balance: number | null;
  sol_price_usd: number | null;
  sol_price_fresh: boolean;
  balance_usd: number | null;
  token_balances: Array<{
    token_account: string;
    mint_address: string;
    quantity: string;
    symbol: string | null;
    name: string | null;
  }>;
  balance_error: string | null;
  withdrawal: { locked_to: string | null; configured: boolean; reason: string | null } | null;
  mode: string;
  execution_enabled: boolean;
  autotrade_enabled: boolean;
  limits: {
    entry_size_usd: string | null;
    max_open_positions: number;
    max_total_exposure_usd: string;
    max_daily_trades: number;
    max_daily_loss_usd: string;
    balance_ceiling_enabled: boolean;
    max_balance_sol: string;
    min_sol_fee_reserve: string;
    exit_max_price_impact_pct: string;
    max_slippage_bps: number;
  };
  today: {
    realised_pnl_usd: string;
    loss_limit_usd: string;
    loss_limit_hit: boolean;
    buys: number;
    buys_limit: number;
    resets_at: string;
  };
  open_positions: number;
  kill_switches: Array<{
    kind: string;
    reason: string | null;
    activated_at: string | null;
    activated_by: string | null;
  }>;
  consecutive_execution_failures: number;
  failures_before_kill_switch: number;
  last_failure_reason: string | null;
  positions: Position[];
  since_first_trade?: SinceFirstTrade | null;
};

type Strategy = {
  id: string;
  name: string;
  paper_book: string;
  idea: string;
  pool_floor_usd: number;
  hold_minutes: number;
  take_profit: boolean;
  stop_loss: boolean;
  max_signal_age_seconds: number;
  ticket_usd: string;
  min_ticket_usd: string;
};

/** A trade size Start accepts, and the smallest trade it allows. */
type TicketChoice = { ticket_usd: string; min_usd: string };

type AutotradeState = {
  enabled: boolean;
  nominated_strategy: string | null;
  /** The trade size chosen at the last Start; null means the configured one. */
  ticket_usd?: string | null;
  started_at: string | null;
  started_by: string | null;
  stopped_at: string | null;
  stopped_by: string | null;
  /** The nominated strategy, else the first, at the size it would trade. */
  strategy: Strategy;
  /** Every strategy Start can nominate. */
  strategies?: Strategy[];
  ticket_choices?: TicketChoice[];
  can_start: boolean;
  history?: Array<{
    action: string;
    actor: string | null;
    reason: string | null;
    nominated_strategy: string | null;
    ticket_usd?: string | null;
    occurred_at: string;
  }>;
};

/** What the page is set to start: an arm and a trade size. Null follows the server. */
type Pick = { id: string | null; ticket: string | null };

/**
 * The strategy Start would trade, at the size it would trade it.
 *
 * While running that is what the server says is running; otherwise it is what
 * was picked here, defaulting to the last Start. The size's floor comes from
 * the server with the size, so the page never works out a threshold itself.
 */
function chosenStrategy(a: AutotradeState | undefined, pick: Pick): Strategy | null {
  if (!a?.strategy) return null;
  if (a.enabled) return a.strategy;
  const base =
    (a.strategies ?? []).find((s) => s.id === (pick.id ?? a.strategy.id)) ?? a.strategy;
  const size = (a.ticket_choices ?? []).find(
    (c) => c.ticket_usd === (pick.ticket ?? a.strategy.ticket_usd),
  );
  return size
    ? { ...base, ticket_usd: size.ticket_usd, min_ticket_usd: size.min_usd }
    : { ...base, ticket_usd: a.strategy.ticket_usd, min_ticket_usd: a.strategy.min_ticket_usd };
}

/** A row of mutually exclusive buttons. */
function Choices<T extends string>({
  label,
  options,
  value,
  onChange,
  disabled,
}: {
  label: string;
  options: Array<{ value: T; text: string }>;
  value: T;
  onChange: (value: T) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs" role="group" aria-label={label}>
      <span className="w-full text-ink-3 sm:w-24 sm:shrink-0">{label}</span>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={`rounded border px-2 py-1.5 tabular-nums disabled:opacity-60 ${
            o.value === value
              ? "border-accent bg-accent/[0.08] text-accent"
              : "border-line text-ink-3 hover:text-ink"
          }`}
        >
          {o.text}
        </button>
      ))}
    </div>
  );
}

type ReadinessCheck = {
  key: string;
  title: string;
  owner: "CODE" | "OPERATOR" | "EVIDENCE";
  status: "PASS" | "BLOCKED" | "UNKNOWN";
  detail: string;
  remediation: string;
};

type Readiness = {
  ready_to_fund: boolean;
  ready_to_trade: boolean;
  proven: boolean;
  checks: ReadinessCheck[];
  min_trade_sol: string | null;
  full_trade_sol: string | null;
};

const usd = (value: number) =>
  `${value < 0 ? "−" : ""}$${Math.abs(value).toFixed(2)}`;

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

function Verdict({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span
      className={`rounded border px-2 py-1 text-xs ${
        ok ? "border-up/40 text-up" : "border-down/40 text-down"
      }`}
    >
      {label}: {ok ? "YES" : "NO"}
    </span>
  );
}

/**
 * The page's first answer: can this wallet be funded, and would Start trade?
 *
 * "Proven" sits beside them rather than inside "ready to trade": the system can
 * be ready while the strategy is unproven, and the operator is told both.
 */
function ReadinessPanel({ data }: { data: Readiness | undefined }) {
  const [open, setOpen] = useState(false);
  // A supplementary panel must never take the page down: a missing or
  // malformed payload renders nothing.
  if (!data || !Array.isArray(data.checks)) return null;
  const blocking = data.checks.filter((c) => c.owner !== "EVIDENCE" && c.status !== "PASS");
  const evidence = data.checks.filter((c) => c.owner === "EVIDENCE");

  return (
    <section className="mt-6 rounded-lg border border-line p-4">
      <div className="flex flex-wrap gap-2">
        <Verdict label="Ready to fund" ok={data.ready_to_fund} />
        <Verdict label="Ready to trade" ok={data.ready_to_trade} />
        <Verdict label="Strategy proven" ok={data.proven} />
      </div>

      {data.ready_to_trade ? (
        <p className="mt-3 text-sm text-ink">
          Everything the wallet needs is in place — pressing Start will trade real money.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {blocking.map((c) => (
            <li key={c.key} className="text-sm">
              <span className="text-ink">{c.title}</span>
              <span className="text-ink-3"> — {c.detail}</span>
              <p className="mt-0.5 text-xs text-ink-3">{c.remediation}</p>
            </li>
          ))}
        </ul>
      )}

      <ul className="mt-3 space-y-1">
        {evidence.map((c) => (
          <li key={c.key} className="text-xs">
            <span className={c.status === "PASS" ? "text-up" : "text-warn"}>{c.title}:</span>{" "}
            <span className="text-ink-3">{c.detail}</span>
          </li>
        ))}
      </ul>

      <button
        className="mt-3 text-xs text-accent"
        onClick={() => setOpen(!open)}
        type="button"
      >
        {open ? "Hide the checklist" : `Show all ${data.checks.length} checks`}
      </button>
      {open ? (
        <ul className="mt-2 space-y-1">
          {data.checks.map((c) => (
            <li key={c.key} className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-ink">
                {c.title} <span className="text-ink-3">— {c.detail}</span>
              </span>
              <span
                className={`shrink-0 rounded border px-1.5 ${
                  c.status === "PASS"
                    ? "border-up/40 text-up"
                    : c.status === "UNKNOWN"
                      ? "border-line text-ink-3"
                      : "border-down/40 text-down"
                }`}
              >
                {c.status}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/**
 * The one control that moves money without a trade.
 *
 * It has no recipient field, deliberately. The destination is configuration and
 * is re-proven inside the isolated signer, so this form can only ever choose an
 * AMOUNT — which is why it needs no account.
 *
 * A withdrawal is submitted once and never retried: a lost response means an
 * UNCERTAIN transfer, and pressing again is how one withdrawal becomes two.
 */
function WithdrawForm({ data }: { data: WalletStatus | undefined }) {
  const [amount, setAmount] = useState("");
  const [confirming, setConfirming] = useState(false);
  const queryClient = useQueryClient();

  const balance = data?.sol_balance ?? 0;
  const reserve = Number(data?.limits?.min_sol_fee_reserve ?? 0);
  const most = Math.max(0, balance - reserve);
  const locked = data?.withdrawal?.locked_to ?? null;
  const value = Number(amount);
  const valid = Number.isFinite(value) && value > 0 && value <= most;

  const send = useMutation({
    mutationFn: () =>
      api.post<{ signature: string; sol: string; explorer: string; note: string }>(
        "/real-wallet/withdraw",
        { sol_amount: amount, confirmation_phrase: "WITHDRAW_TO_MY_ADDRESS" },
      ),
    onSuccess: () => {
      setAmount("");
      setConfirming(false);
      void queryClient.invalidateQueries({ queryKey: ["real-wallet"] });
    },
  });

  if (!locked) {
    return (
      <p className="mt-2 text-sm text-warn">
        No destination is nominated, so nothing can be sent. An unset destination
        permits nothing rather than anything.
      </p>
    );
  }

  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          inputMode="decimal"
          value={amount}
          onChange={(e) => {
            setAmount(e.target.value);
            setConfirming(false);
          }}
          placeholder="0.00"
          className="w-32 rounded border border-line bg-transparent px-2 py-1 text-sm text-ink"
        />
        <span className="text-sm text-ink-3">SOL</span>
        <button
          type="button"
          onClick={() => {
            setAmount(most.toFixed(9).replace(/0+$/, "").replace(/\.$/, ""));
            setConfirming(false);
          }}
          className="rounded border border-line px-2 py-1 text-xs text-ink-3"
        >
          max {most.toFixed(4)}
        </button>
        {confirming ? (
          <button
            type="button"
            disabled={send.isPending}
            onClick={() => send.mutate()}
            className="rounded-md bg-warn px-4 py-2 text-sm font-semibold text-black shadow-sm disabled:opacity-50"
          >
            {send.isPending ? "Sending — do not retry…" : "Confirm — send now"}
          </button>
        ) : (
          <button
            type="button"
            disabled={!valid}
            onClick={() => setConfirming(true)}
            className="rounded-md border border-line px-3 py-1 text-sm text-ink disabled:opacity-40"
          >
            Withdraw
          </button>
        )}
      </div>

      {!valid ? (
        <p className={`mt-2 text-xs ${amount ? "text-warn" : "text-ink-3"}`}>
          Enter an amount above zero and at most {most.toFixed(6)} SOL — {reserve} SOL
          stays behind to pay for the next transaction.
        </p>
      ) : null}

      {confirming && !send.isPending && !send.data ? (
        <p className="mt-2 text-xs text-warn">
          Nothing has been sent yet. Press <b>Confirm — send now</b> to send {amount} SOL
          to {locked.slice(0, 12)}…{locked.slice(-6)}. It is submitted once and never
          retried.
        </p>
      ) : null}

      {send.data ? (
        <div className="mt-3 rounded border border-line p-3 text-sm">
          <p className="text-ink">Sent {send.data.sol} SOL.</p>
          <a
            className="mt-1 block break-all font-mono text-xs text-accent"
            href={send.data.explorer}
            target="_blank"
            rel="noreferrer"
          >
            {send.data.signature}
          </a>
          <p className="mt-2 text-xs text-ink-3">{send.data.note}</p>
        </div>
      ) : null}

      {send.error ? (
        <p className="mt-2 text-xs text-warn">
          Refused: {send.error instanceof ApiError ? send.error.message : "unavailable"}.
          Nothing was sent — but if you saw a timeout rather than this message, check
          the balance before trying again.
        </p>
      ) : null}
    </div>
  );
}

function BalanceCard({
  data,
  readiness,
}: {
  data: WalletStatus | undefined;
  readiness: Readiness | undefined;
}) {
  const [panel, setPanel] = useState<"none" | "deposit" | "withdraw">("none");
  const [copied, setCopied] = useState(false);
  const address = data?.public_key ?? null;
  const balance = data?.sol_balance;
  const reserve = Number(data?.limits?.min_sol_fee_reserve ?? 0);
  const ceiling = Number(data?.limits?.max_balance_sol ?? 0);
  const overCeiling =
    data?.limits?.balance_ceiling_enabled === true &&
    balance != null &&
    ceiling > 0 &&
    balance > ceiling;

  const copy = () => {
    if (!address) return;
    void navigator.clipboard.writeText(address);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <section className="mt-6 rounded-lg border border-line p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-label text-ink-3">
            Balance · {(data?.network ?? "—").toUpperCase()}
            {data?.rpc?.verified ? "" : " · CHAIN NOT VERIFIED"}
          </p>
          <p className="mt-2 text-4xl font-medium tabular-nums text-ink">
            {balance != null ? balance.toFixed(6) : "—"}
            <span className="ml-2 text-lg text-ink-3">SOL</span>
          </p>
          <p className="mt-1 text-lg tabular-nums text-ink-2">
            {data?.balance_usd != null ? (
              <>
                ${data.balance_usd.toFixed(2)}
                <span className="ml-2 text-xs text-ink-3">
                  at ${data.sol_price_usd?.toFixed(2)}/SOL
                  {data.sol_price_fresh ? "" : " · PRICE STALE"}
                </span>
              </>
            ) : (
              // Never a guessed rate: every limit here is in dollars.
              <span className="text-sm text-ink-3">USD unavailable — no fresh SOL price</span>
            )}
          </p>
          {address ? (
            <button
              type="button"
              onClick={copy}
              className="mt-2 break-all text-left font-mono text-xs text-ink-3 underline decoration-dotted"
            >
              {address}
              <span className="ml-2 not-italic text-accent">{copied ? "copied" : "copy"}</span>
            </button>
          ) : (
            <p className="mt-2 text-sm text-ink-3">No wallet configured.</p>
          )}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setPanel(panel === "deposit" ? "none" : "deposit")}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-black disabled:opacity-40"
            disabled={!address}
          >
            Deposit
          </button>
          <button
            type="button"
            onClick={() => setPanel(panel === "withdraw" ? "none" : "withdraw")}
            className="rounded-md border border-line px-4 py-2 text-sm font-medium text-ink disabled:opacity-40"
            disabled={!address}
          >
            Withdraw
          </button>
        </div>
      </div>

      {data?.balance_error ? (
        <p className="mt-3 text-sm text-warn">
          Balance unreadable: {data.balance_error}. An unreadable balance refuses rather
          than assuming zero.
        </p>
      ) : null}

      {overCeiling ? (
        <p className="mt-3 text-sm text-warn">
          Above the {ceiling} SOL ceiling — the wallet refuses to buy until the excess is
          withdrawn.
        </p>
      ) : null}

      {panel === "deposit" ? (
        <div className="mt-4 rounded-md border border-line bg-raised p-4">
          <p className="text-label text-ink-3">Deposit SOL</p>
          <p className="mt-2 text-sm text-ink-3">
            Send SOL on <span className="text-ink">{data?.network}</span> to the address
            above.{" "}
            {readiness?.min_trade_sol ? (
              <>
                One trade needs at least{" "}
                <span className="text-ink">{readiness.min_trade_sol} SOL</span>; a full $
                {data?.limits?.entry_size_usd ?? "—"} trade needs{" "}
                <span className="text-ink">{readiness.full_trade_sol} SOL</span>.{" "}
              </>
            ) : null}
            {reserve} SOL always stays behind to pay the fees of each sell.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={copy}
              className="rounded-md border border-line px-3 py-2 text-sm text-ink"
            >
              {copied ? "Address copied" : "Copy address"}
            </button>
            <a
              className="text-sm text-accent"
              href={`https://solscan.io/account/${address}${
                data?.network === "devnet" ? "?cluster=devnet" : ""
              }`}
              rel="noreferrer"
              target="_blank"
            >
              View on Solscan
            </a>
          </div>
        </div>
      ) : null}

      {panel === "withdraw" ? (
        <div className="mt-4 rounded-md border border-line bg-raised p-4">
          <p className="text-label text-ink-3">Withdraw SOL</p>
          <p className="mt-2 text-sm text-ink-3">
            Sends SOL to the one address below and nowhere else. This form cannot set the
            destination; the signer checks it again against its own copy.
          </p>
          <WithdrawForm data={data} />
          <div className="mt-3 rounded border border-line p-3">
            <p className="text-label text-ink-3">Locked destination</p>
            {data?.withdrawal?.configured && data.withdrawal.locked_to ? (
              <p className="mt-1 break-all font-mono text-xs text-ink">
                {data.withdrawal.locked_to}
              </p>
            ) : (
              <p className="mt-1 text-sm text-warn">
                No destination nominated
                {data?.withdrawal?.reason ? ` — ${data.withdrawal.reason}` : ""}.
              </p>
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}

/** Which strategy this wallet trades, in plain words, from its own spec. */
function StrategyCard({
  autotrade,
  strategy,
  proven,
}: {
  autotrade: AutotradeState | undefined;
  strategy: Strategy | null;
  proven: boolean | undefined;
}) {
  if (!autotrade || !strategy) return null;
  const s = strategy;
  const other =
    autotrade.enabled && autotrade.nominated_strategy && autotrade.nominated_strategy !== s.id
      ? autotrade.nominated_strategy
      : null;
  const rules: Array<[string, string]> = [
    [
      "Buys",
      `a pump.fun token the moment it graduates, only if its new pool holds at least $${s.pool_floor_usd.toLocaleString()}`,
    ],
    [
      "Sells",
      `exactly ${s.hold_minutes} minutes later — ${
        s.take_profit || s.stop_loss ? "or earlier on its exit rules" : "no take-profit, no stop-loss"
      }`,
    ],
    [
      "Size",
      `$${s.ticket_usd} a trade, or all spendable cash if less — never under $${s.min_ticket_usd}; a second trade at once needs another full $${s.ticket_usd}`,
    ],
    ["Timing", `a signal older than ${s.max_signal_age_seconds} seconds is skipped`],
  ];

  return (
    <section className="mt-6 rounded-lg border border-line p-4">
      <p className="text-label text-ink-3">
        {autotrade.enabled ? "Strategy this wallet trades" : "Strategy Start would trade"}
      </p>
      <h2 className="mt-1 text-xl font-medium text-ink">
        {s.id}{" "}
        <span className="text-sm font-normal text-ink-3">· copies paper book {s.paper_book}</span>
      </h2>
      <dl className="mt-3 space-y-1 text-sm">
        {rules.map(([term, text]) => (
          <div key={term} className="flex gap-2">
            <dt className="w-16 shrink-0 text-ink-3">{term}</dt>
            <dd className="text-ink">{text}</dd>
          </div>
        ))}
      </dl>
      {proven === false ? (
        <p className="mt-3 text-xs text-warn">
          Not proven yet — the Graduation Lab has not called it an edge.{" "}
          <Link className="text-accent underline" href="/graduation-lab">
            See its paper results
          </Link>
        </p>
      ) : null}
      {other ? (
        <p className="mt-2 text-xs text-warn">
          Trading is currently on under {other}, not {s.id}.
        </p>
      ) : null}
    </section>
  );
}

/**
 * START and STOP.
 *
 * Stop needs no account and no typing: it is the control an owner reaches for
 * in a hurry, and positions already open still sell on time. Start needs the
 * administrator account and a reason, which is recorded.
 */
function TradingControl({
  status,
  autotrade,
  ready,
  chosen,
  onPick,
}: {
  status: WalletStatus | undefined;
  autotrade: AutotradeState | undefined;
  ready: boolean | undefined;
  chosen: Strategy | null;
  onPick: (change: Partial<Pick>) => void;
}) {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [reason, setReason] = useState("");
  const strategies = autotrade?.strategies ?? [];
  const sizes = autotrade?.ticket_choices ?? [];

  const mutate = useMutation({
    mutationFn: (action: "start" | "stop") =>
      api.post<AutotradeState>(
        `/real-wallet/autotrade/${action}`,
        action === "start"
          ? {
              strategy_id: chosen?.id,
              reason: reason.trim(),
              // Only a size the server offered; otherwise it trades its configured one.
              ...(sizes.some((c) => c.ticket_usd === chosen?.ticket_usd)
                ? { ticket_usd: chosen?.ticket_usd }
                : {}),
            }
          : { reason: reason.trim() || "stopped from the wallet page" },
      ),
    onSuccess: () => {
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["real-wallet"] });
    },
  });

  const running = autotrade?.enabled === true;
  const canStart = user?.role === "admin" || autotrade?.can_start === true;
  const live =
    status?.mode === "live" && status.execution_enabled && status.autotrade_enabled;

  return (
    <section className="mt-6 rounded-lg border border-line p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <p className="text-label text-ink-3">Trading</p>
          <p className="mt-1 text-lg font-medium text-ink">
            {running
              ? `ON — ${autotrade?.nominated_strategy ?? "—"}${
                  chosen && chosen.id === autotrade?.nominated_strategy
                    ? ` · $${chosen.ticket_usd} a trade`
                    : ""
                }`
              : "OFF"}
          </p>
        </div>
        <span
          className={`rounded border px-2 py-1 text-xs ${
            running ? "border-up/40 text-up" : "border-line text-ink-3"
          }`}
        >
          {running ? "BUYING" : "NOT BUYING"}
        </span>
      </div>

      <p className="mt-2 text-sm text-ink-3">
        {running
          ? "Buys on every qualifying signal. Stop ends buying at once; anything already open still sells on time."
          : !live
            ? `Start would not trade yet: mode ${status?.mode ?? "—"}, execution ${
                status?.execution_enabled ? "on" : "off"
              }, autotrade ${status?.autotrade_enabled ? "on" : "off"}.`
            : ready === false
              ? "Start would not buy yet — see what is missing at the top of the page."
              : "Start buys with real money from the next signal."}
      </p>

      {chosen && (strategies.length > 1 || sizes.length > 1) ? (
        <div className="mt-3 flex flex-col gap-2">
          {strategies.length > 1 ? (
            <Choices
              label="Copies"
              value={chosen.id}
              disabled={running}
              onChange={(id) => onPick({ id })}
              options={strategies.map((s) => ({
                value: s.id,
                text: `${s.paper_book} · sells after ${s.hold_minutes} min`,
              }))}
            />
          ) : null}
          {sizes.length > 1 ? (
            <Choices
              label="Trade size"
              value={chosen.ticket_usd}
              disabled={running}
              onChange={(ticket) => onPick({ ticket })}
              options={sizes.map((c) => ({ value: c.ticket_usd, text: `$${c.ticket_usd}` }))}
            />
          ) : null}
          {running ? (
            <p className="text-xs text-ink-3">Stop first to change the arm or the size.</p>
          ) : null}
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2">
        <input
          className="w-full rounded border border-line bg-transparent px-2 py-2 text-sm text-ink sm:w-auto sm:min-w-0 sm:flex-1"
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason (needed to start)"
          value={reason}
        />
        {canStart ? (
          <button
            className="rounded border border-up/40 px-3 py-2 text-sm text-up disabled:opacity-40"
            disabled={
              running || !autotrade || reason.trim().length < 3 || mutate.isPending
            }
            onClick={() => mutate.mutate("start")}
            type="button"
          >
            Start {chosen?.id ?? ""}
          </button>
        ) : (
          <Link
            className="rounded border border-accent/50 px-3 py-2 text-sm text-accent"
            href="/login?next=/real-wallet"
          >
            Sign in to start
          </Link>
        )}
        <button
          className="rounded border border-down/40 px-3 py-2 text-sm text-down disabled:opacity-40"
          disabled={mutate.isPending}
          onClick={() => mutate.mutate("stop")}
          type="button"
        >
          Stop
        </button>
      </div>
      <p className="mt-2 text-xs text-ink-3">
        Stop and Withdraw work without signing in. Start needs your account.
      </p>

      {mutate.error ? (
        <p className="mt-2 text-sm text-warn">
          Refused:{" "}
          {mutate.error instanceof ApiError && mutate.error.status === 401
            ? "sign in first."
            : mutate.error instanceof ApiError
              ? mutate.error.message
              : "unavailable"}
        </p>
      ) : null}

      {autotrade?.history?.length ? (
        <ul className="mt-3 space-y-0.5 border-t border-line pt-3 font-mono text-[11px] text-ink-3">
          {autotrade.history.slice(0, 5).map((h, i) => (
            <li key={i}>
              {when(h.occurred_at)} · {h.action} · {h.nominated_strategy ?? "—"}
              {h.ticket_usd ? ` at $${h.ticket_usd}` : ""} ·{" "}
              {h.actor ?? "system"} · {h.reason ?? ""}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function TodayCard({ status }: { status: WalletStatus | undefined }) {
  if (!status?.today) return null;
  const pnl = Number(status.today.realised_pnl_usd);
  return (
    <section className="mt-6 grid gap-3 sm:grid-cols-3">
      <div className="rounded-lg border border-line p-4">
        <p className="text-label text-ink-3">Today (UTC)</p>
        <p
          className={`mt-1 text-2xl tabular-nums ${
            pnl > 0 ? "text-up" : pnl < 0 ? "text-down" : "text-ink"
          }`}
        >
          {usd(pnl)}
        </p>
        <p className={`mt-1 text-xs ${status.today.loss_limit_hit ? "text-down" : "text-ink-3"}`}>
          {status.today.loss_limit_hit
            ? `Loss limit of $${status.today.loss_limit_usd} reached — no new buys until 00:00 UTC.`
            : `Stops buying for the day at a $${status.today.loss_limit_usd} loss.`}
        </p>
      </div>
      <div className="rounded-lg border border-line p-4">
        <p className="text-label text-ink-3">Buys today</p>
        <p className="mt-1 text-2xl tabular-nums text-ink">
          {status.today.buys}
          <span className="ml-1 text-sm text-ink-3">of {status.today.buys_limit}</span>
        </p>
      </div>
      <div className="rounded-lg border border-line p-4">
        <p className="text-label text-ink-3">Open now</p>
        <p className="mt-1 text-2xl tabular-nums text-ink">
          {status.open_positions}
          <span className="ml-1 text-sm text-ink-3">of {status.limits.max_open_positions}</span>
        </p>
      </div>
    </section>
  );
}

const EXIT_STATE: Record<string, string> = {
  created: "selling",
  safety_approved: "selling",
  order_created: "selling",
  submitted: "sell sent",
  blocked: "sell refused — retrying",
  failed: "sell failed — retrying",
  reconciliation_required: "sell needs checking",
};

/** What a closed trade made, net of fees when that is known. */
function resultOf(p: Position): number | null {
  const value = p.realised_net_pnl_usd ?? p.realised_gross_pnl_usd;
  return value == null ? null : Number(value);
}

/** How long a trade was held — a live clock while it is still open. */
function Held({ from, to }: { from: string; to: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (to) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [to]);
  const end = to ? new Date(to).getTime() : now;
  const secs = Math.max(0, Math.floor((end - new Date(from).getTime()) / 1000));
  const pad = (n: number) => String(n).padStart(2, "0");
  const text =
    secs >= 86400
      ? `${Math.floor(secs / 86400)}d ${pad(Math.floor((secs % 86400) / 3600))}h`
      : secs >= 3600
        ? `${Math.floor(secs / 3600)}h ${pad(Math.floor((secs % 3600) / 60))}m`
        : `${Math.floor(secs / 60)}m ${pad(secs % 60)}s`;
  return <span className="tabular-nums">{text}</span>;
}

function TokenLink({ p }: { p: Position }) {
  return (
    <a
      className="text-ink underline decoration-dotted"
      href={`https://dexscreener.com/solana/${p.mint_address}`}
      rel="noreferrer"
      target="_blank"
      title={p.mint_address}
    >
      {p.symbol ?? p.mint_address.slice(0, 8)}
    </a>
  );
}

function TxLinks({ p }: { p: Position }) {
  const links = [
    ["buy", p.entry_signature],
    ["sell", p.exit_signature],
  ].filter((x): x is [string, string] => Boolean(x[1]));
  if (!links.length) return <>—</>;
  return (
    <span className="flex gap-2">
      {links.map(([label, sig]) => (
        <a
          key={label}
          className="text-accent underline decoration-dotted"
          href={`https://solscan.io/tx/${sig}`}
          rel="noreferrer"
          target="_blank"
        >
          {label}
        </a>
      ))}
    </span>
  );
}

/** A live d HH:MM:SS clock counting up from `from`. */
function Clock({ from }: { from: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const secs = Math.max(0, Math.floor((now - new Date(from).getTime()) / 1000));
  const pad = (n: number) => String(n).padStart(2, "0");
  const days = Math.floor(secs / 86400);
  return (
    <span className="tabular-nums">
      {days ? `${days}d ` : ""}
      {pad(Math.floor((secs % 86400) / 3600))}:{pad(Math.floor((secs % 3600) / 60))}:
      {pad(secs % 60)}
    </span>
  );
}

const pct = (value: string | null) =>
  value == null
    ? "—"
    : `${Number(value) >= 0 ? "+" : "−"}${Math.abs(Number(value)).toFixed(2)}%`;

const tone = (value: number) =>
  value > 0 ? "text-up" : value < 0 ? "text-down" : "text-ink";

/**
 * The wallet since it began trading: how long, what it made, and what that is
 * on the wallet's worth at the first buy — the lab's "since first trade", with
 * real money. Totals are the server's, over every trade.
 */
function SinceFirstTradeCard({ since }: { since: SinceFirstTrade | null | undefined }) {
  if (!since) return null;
  const pnl = Number(since.net_pnl_usd);
  return (
    <section className="mt-6 rounded-lg border border-line p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-label text-ink-3">Since the first trade</p>
        <p className="text-sm text-ink-3">
          <span className="rounded bg-ink/[0.06] px-1.5 py-px font-mono text-ink">
            <Clock from={since.first_trade_at} />
          </span>{" "}
          since {when(since.first_trade_at)}
        </p>
      </div>
      <div className="mt-3 grid gap-4 sm:grid-cols-3">
        <div>
          <p className="text-xs text-ink-3">Profit after fees</p>
          <p className={`text-2xl font-medium tabular-nums ${tone(pnl)}`}>
            {pnl > 0 ? "+" : ""}
            {usd(pnl)}
          </p>
          <p className="text-xs text-ink-3">
            {since.trades} trades · {since.won} won · {since.lost} lost
            {since.open ? ` · ${since.open} open` : ""}
          </p>
        </div>
        <div>
          <p className="text-xs text-ink-3">Return on the wallet</p>
          <p
            className={`text-2xl font-medium tabular-nums ${tone(Number(since.return_pct ?? 0))}`}
          >
            {pct(since.return_pct)}
          </p>
          <p className="text-xs text-ink-3">
            {since.start_value_usd && since.start_balance_sol
              ? `on $${Number(since.start_value_usd).toFixed(2)} (${Number(
                  since.start_balance_sol,
                ).toFixed(4)} SOL) when trading began`
              : "the wallet's starting worth was not recorded"}
          </p>
        </div>
        <div>
          <p className="text-xs text-ink-3">Average per trade</p>
          <p
            className={`text-2xl font-medium tabular-nums ${tone(
              Number(since.average_return_pct ?? 0),
            )}`}
          >
            {pct(since.average_return_pct)}
          </p>
          <p className="text-xs text-ink-3">
            on ${Number(since.traded_usd).toFixed(2)} traded
          </p>
        </div>
      </div>
    </section>
  );
}

const sol = (value: string | null) => (value ? `${Number(value).toFixed(4)} SOL` : "—");

/**
 * Every real trade, laid out like the Graduation Lab's own panel: what is open
 * now, what closed and how, and the totals. Figures are the wallet's settled
 * amounts; the server sends its latest 50.
 */
function TradesTable({ positions }: { positions: Position[] }) {
  const open = positions.filter((p) => p.status === "OPEN");
  const closed = positions.filter((p) => p.status !== "OPEN");
  const results = closed.map(resultOf).filter((r): r is number => r !== null);
  const net = results.reduce((a, b) => a + b, 0);
  const won = results.filter((r) => r > 0).length;
  const lost = results.filter((r) => r < 0).length;
  const grossOnly = closed.filter(
    (p) => p.realised_net_pnl_usd == null && p.realised_gross_pnl_usd != null,
  ).length;
  const head = "border-y border-line text-left text-xs text-ink-3";

  return (
    <section className="mt-6 rounded-lg border border-line">
      <div className="flex flex-wrap items-baseline justify-between gap-2 p-4">
        <p className="text-label text-ink-3">Real trades</p>
        {positions.length ? (
          <p className="text-sm text-ink-3">
            {closed.length} closed · {won} won · {lost} lost ·{" "}
            <span className={net > 0 ? "text-up" : net < 0 ? "text-down" : "text-ink"}>
              {usd(net)}
            </span>
            {grossOnly ? ` (${grossOnly} before fees)` : ""} · {open.length} open
            {positions.length >= 50 ? " · latest 50 shown" : ""}
          </p>
        ) : null}
      </div>
      {!positions.length ? (
        <p className="px-4 pb-4 text-sm text-ink-3">No real trades yet.</p>
      ) : null}

      {open.length ? (
        <div className="overflow-x-auto">
          <p className="px-4 pb-2 text-xs uppercase tracking-wide text-ink-3">
            Open — {open.length}
          </p>
          <table className="w-full min-w-[640px] text-sm">
            <thead className={head}>
              <tr>
                <th className="p-3 font-normal">Token</th>
                <th className="font-normal">Held</th>
                <th className="font-normal">State</th>
                <th className="font-normal">Spent</th>
                <th className="font-normal">Bought</th>
                <th className="font-normal">Arm</th>
                <th className="p-3 font-normal">Transactions</th>
              </tr>
            </thead>
            <tbody>
              {open.map((p) => (
                <tr key={p.id} className="border-b border-line-subtle last:border-0">
                  <td className="p-3">
                    <TokenLink p={p} />
                  </td>
                  <td>
                    <Held from={p.opened_at} to={null} />
                  </td>
                  <td className="text-ink-3">
                    {(p.exit_state && EXIT_STATE[p.exit_state]) || "holding"}
                  </td>
                  <td className="tabular-nums">{sol(p.spent)}</td>
                  <td className="tabular-nums text-ink-3">{when(p.opened_at)}</td>
                  <td className="text-ink-3">{p.strategy_id ?? "—"}</td>
                  <td className="p-3">
                    <TxLinks p={p} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {closed.length ? (
        <div className="overflow-x-auto">
          <p className="px-4 pb-2 pt-3 text-xs uppercase tracking-wide text-ink-3">
            Closed — {closed.length}
          </p>
          <table className="w-full min-w-[860px] text-sm">
            <thead className={head}>
              <tr>
                <th className="p-3 font-normal">Token</th>
                <th className="font-normal">Result</th>
                <th className="font-normal">Return</th>
                <th className="font-normal">Held</th>
                <th className="font-normal">How it ended</th>
                <th className="font-normal">Spent</th>
                <th className="font-normal">Got back</th>
                <th className="font-normal">Bought</th>
                <th className="font-normal">Sold</th>
                <th className="font-normal">Arm</th>
                <th className="p-3 font-normal">Transactions</th>
              </tr>
            </thead>
            <tbody>
              {closed.map((p) => {
                const result = resultOf(p);
                const cost = Number(p.cost_usd);
                const tone =
                  result == null ? "text-ink-3" : result >= 0 ? "text-up" : "text-down";
                return (
                  <tr key={p.id} className="border-b border-line-subtle last:border-0">
                    <td className="p-3">
                      <TokenLink p={p} />
                    </td>
                    <td className={`tabular-nums ${tone}`}>
                      {result == null ? "—" : usd(result)}
                      {result != null && p.realised_net_pnl_usd == null ? (
                        <span className="text-xs text-ink-3"> before fees</span>
                      ) : null}
                    </td>
                    <td className={`tabular-nums ${tone}`}>
                      {result == null || !(cost > 0)
                        ? "—"
                        : `${result >= 0 ? "+" : "−"}${Math.abs((result / cost) * 100).toFixed(2)}%`}
                    </td>
                    <td>
                      {p.closed_at ? <Held from={p.opened_at} to={p.closed_at} /> : "—"}
                    </td>
                    <td className="text-ink-3">
                      {p.exit_reason?.startsWith("time")
                        ? "sold on time"
                        : `sold · ${p.exit_reason ?? "closed"}`}
                    </td>
                    <td className="tabular-nums">{sol(p.spent)}</td>
                    <td className="tabular-nums">{sol(p.received)}</td>
                    <td className="tabular-nums text-ink-3">{when(p.opened_at)}</td>
                    <td className="tabular-nums text-ink-3">
                      {p.closed_at ? when(p.closed_at) : "—"}
                    </td>
                    <td className="text-ink-3">{p.strategy_id ?? "—"}</td>
                    <td className="p-3">
                      <TxLinks p={p} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

/**
 * One armed emergency stop, and the administrator's way to clear it.
 *
 * Clearing removes one barrier and nothing else, and the failed-send count is
 * not reset — one more failed send turns this stop straight back on. The
 * server requires a reason and a fixed confirmation phrase; the phrase is sent
 * by the button, the reason is the operator's.
 */
function EmergencyStop({
  sw,
  canClear,
}: {
  sw: WalletStatus["kill_switches"][number];
  canClear: boolean;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const clear = useMutation({
    mutationFn: () =>
      api.post(`/real-wallet/kill-switches/${encodeURIComponent(sw.kind)}/clear`, {
        confirmation_phrase: "CLEAR_REAL_WALLET_KILL_SWITCH",
        reason: reason.trim(),
      }),
    onSuccess: () => {
      setOpen(false);
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["real-wallet"] });
    },
  });

  return (
    <li>
      EMERGENCY STOP ON: <span className="font-medium">{sw.kind}</span> —{" "}
      {sw.reason ?? "no reason"}. Nothing buys or sells until it is cleared.
      {canClear ? (
        open ? (
          <div className="mt-2 flex flex-col gap-2 text-ink">
            <p className="text-xs text-ink-3">
              Clear it only once the cause is fixed. The failed-send count is not
              reset, so one more failed send turns this stop straight back on.
            </p>
            <div className="flex flex-wrap gap-2">
              <input
                className="w-full rounded border border-line bg-transparent px-2 py-2 text-sm text-ink sm:w-auto sm:min-w-0 sm:flex-1"
                onChange={(e) => setReason(e.target.value)}
                placeholder="Why it is safe to clear (8+ characters)"
                value={reason}
              />
              <button
                className="rounded border border-down/40 px-3 py-2 text-sm text-down disabled:opacity-40"
                disabled={reason.trim().length < 8 || clear.isPending}
                onClick={() => clear.mutate()}
                type="button"
              >
                Clear this stop
              </button>
              <button
                className="rounded border border-line px-3 py-2 text-sm text-ink-3"
                onClick={() => setOpen(false)}
                type="button"
              >
                Cancel
              </button>
            </div>
            {clear.error ? (
              <p className="text-sm text-warn">
                Refused:{" "}
                {clear.error instanceof ApiError && clear.error.status === 401
                  ? "sign in first."
                  : clear.error instanceof ApiError
                    ? clear.error.message
                    : "unavailable"}
              </p>
            ) : null}
          </div>
        ) : (
          <button
            className="ml-2 rounded border border-line px-2 py-1 text-xs text-ink"
            onClick={() => setOpen(true)}
            type="button"
          >
            Clear…
          </button>
        )
      ) : (
        <Link className="ml-2 text-xs text-accent underline" href="/login?next=/real-wallet">
          Sign in to clear
        </Link>
      )}
    </li>
  );
}

function SafetyCard({
  status,
  ticket,
  canClear,
}: {
  status: WalletStatus | undefined;
  /** The size the running wallet trades, when Start chose one. */
  ticket: string | null;
  /** Signed in as the administrator — the only one the server lets clear a stop. */
  canClear: boolean;
}) {
  if (!status) return null;
  const l = status.limits;
  const size = !l.entry_size_usd
    ? "NOT SET — no buys"
    : ticket && Number(ticket) !== Number(l.entry_size_usd)
      ? `$${ticket} (up to $${l.entry_size_usd} allowed)`
      : `$${l.entry_size_usd}`;
  const limits: Array<[string, string]> = [
    ["Trade size", size],
    ["Open at once", `${l.max_open_positions} (max $${l.max_total_exposure_usd})`],
    ["Buys a day", String(l.max_daily_trades)],
    ["Daily loss stop", `$${l.max_daily_loss_usd}`],
    ["Sell price impact", `up to ${l.exit_max_price_impact_pct}%`],
    ["Slippage", `${l.max_slippage_bps / 100}%`],
    ["Kept for fees", `${l.min_sol_fee_reserve} SOL`],
  ];
  return (
    <section className="mt-6 rounded-lg border border-line p-4">
      <p className="text-label text-ink-3">Safety</p>
      {status.kill_switches.length ? (
        <ul className="mt-2 space-y-1 text-sm text-down">
          {status.kill_switches.map((sw) => (
            <EmergencyStop key={sw.kind} sw={sw} canClear={canClear} />
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-ink">No emergency stop is on.</p>
      )}
      <p className="mt-1 text-xs text-ink-3">
        Failed sends in a row: {status.consecutive_execution_failures} of{" "}
        {status.failures_before_kill_switch} before the emergency stop turns itself on
        {status.last_failure_reason ? ` (last: ${status.last_failure_reason})` : ""}.
      </p>
      <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        {limits.map(([term, value]) => (
          <div key={term} className="flex justify-between gap-3">
            <dt className="text-ink-3">{term}</dt>
            <dd className="tabular-nums text-ink">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function TokensHeld({ status }: { status: WalletStatus | undefined }) {
  if (!status?.token_balances.length) return null;
  return (
    <section className="mt-6 rounded-lg border border-line p-4">
      <p className="text-label text-ink-3">Tokens in the wallet</p>
      <ul className="mt-2 space-y-1 text-sm">
        {status.token_balances.map((t) => (
          <li key={t.token_account} className="flex justify-between gap-3">
            <span className="text-ink">{t.symbol ?? t.name ?? t.mint_address.slice(0, 8)}</span>
            <span className="tabular-nums text-ink-3">{t.quantity}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function RealWalletPage() {
  const { user } = useAuth();
  const [pick, setPick] = useState<Pick>({ id: null, ticket: null });
  const status = useQuery({
    queryKey: ["real-wallet", "status"],
    queryFn: () => api.get<WalletStatus>("/real-wallet/status"),
    retry: false,
    refetchInterval: 15_000,
  });
  const autotrade = useQuery({
    // Keyed by who is signed in, so signing in re-reads it with the account.
    queryKey: ["real-wallet", "autotrade", user?.id ?? "anonymous"],
    queryFn: () => api.get<AutotradeState>("/real-wallet/autotrade"),
    refetchInterval: 15_000,
  });
  const readiness = useQuery({
    queryKey: ["real-wallet", "readiness"],
    queryFn: () => api.get<Readiness>("/real-wallet/funding-readiness"),
    refetchInterval: 60_000,
  });

  if (status.isError) {
    const failure = status.error;
    return (
      <main>
        <p className="text-label text-accent">Real wallet</p>
        <h1 className="mt-2 text-2xl font-medium text-ink">The wallet could not be read.</h1>
        <p className="mt-3 max-w-2xl text-sm text-ink-3">
          {failure instanceof ApiError && failure.code === "alpha_access_required"
            ? "Enter the site code on the home page first."
            : `The request failed${
                failure instanceof ApiError ? ` (HTTP ${failure.status})` : ""
              }. Nothing on the wallet changed; try again in a moment.`}
        </p>
      </main>
    );
  }

  if (status.isPending) {
    // Nothing is known yet — not "no wallet", not "execution off".
    return (
      <main>
        <p className="text-label text-accent">Real wallet</p>
        <p className="mt-2 text-sm text-ink-3">Reading the wallet…</p>
      </main>
    );
  }

  const data = status.data;
  const chosen = chosenStrategy(autotrade.data, pick);
  return (
    <main>
      <p className="text-label text-accent">
        Real wallet · {(data?.network ?? "—").toUpperCase()}
      </p>
      <h1 className="mt-2 text-3xl font-medium text-ink">Real wallet</h1>
      <p className="mt-2 max-w-2xl text-sm text-ink-3">
        Trades real SOL with the strategy below. Withdrawals can only go to your own
        address.
      </p>
      <ReadinessPanel data={readiness.data} />
      <BalanceCard data={data} readiness={readiness.data} />
      <StrategyCard
        autotrade={autotrade.data}
        strategy={chosen}
        proven={readiness.data?.proven}
      />
      <TradingControl
        status={data}
        autotrade={autotrade.data}
        ready={readiness.data?.ready_to_trade}
        chosen={chosen}
        onPick={(change) => setPick((p) => ({ ...p, ...change }))}
      />
      <TodayCard status={data} />
      <SinceFirstTradeCard since={data?.since_first_trade} />
      <TradesTable positions={data?.positions ?? []} />
      <SafetyCard
        status={data}
        ticket={autotrade.data?.enabled ? autotrade.data.strategy.ticket_usd : null}
        canClear={user?.role === "admin" || autotrade.data?.can_start === true}
      />
      <TokensHeld status={data} />
    </main>
  );
}
