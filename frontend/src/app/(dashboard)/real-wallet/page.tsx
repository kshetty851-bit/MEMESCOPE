"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "@/lib/api-client";

type WalletStatus = {
  public_key: string | null;
  address_valid: boolean;
  network: "devnet" | "mainnet";
  rpc: {
    network: "devnet" | "mainnet";
    verified: boolean;
    observed_genesis_hash: string | null;
    error: string | null;
  };
  sol_balance: number | null;
  sol_price_usd: number | null;
  sol_price_fresh: boolean;
  balance_usd: number | null;
  token_balances: Array<{
    token_account: string;
    mint_address: string;
    raw_amount: string;
    quantity: string;
    decimals: number;
    program_id: string;
    symbol: string | null;
    name: string | null;
    image_url: string | null;
  }>;
  balance_error: string | null;
  withdrawal: {
    locked_to: string | null;
    configured: boolean;
    reason: string | null;
  } | null;
  funding_status: "unfunded" | "funded" | "unknown";
  mode: "disabled" | "dry_run" | "armed" | "live";
  execution_enabled: boolean;
  autotrade_enabled: boolean;
  signer_status: string;
  live_submission_transport: string;
  safety_gate: string;
  lock_state: "LOCKED" | "SUBMISSION_PERMITTED";
  security_gate: {
    shared_with_paper: boolean;
    evaluator: string;
    mandatory_checks: string[];
    max_evidence_age_seconds: number;
  };
  program_allowlist: string[];
  limits: {
    entry_size_usd: string | null;
    entry_size_configured: boolean;
    max_trade_usd: string;
    max_open_positions: number;
    max_total_exposure_usd: string;
    max_daily_notional_usd: string;
    max_daily_trades: number;
    max_daily_loss_usd: string;
    max_balance_sol: string;
    max_balance_lamports: number;
    min_sol_fee_reserve: string;
  };
  dry_run: {
    feature_enabled: boolean;
    decisions: Array<{
      mint_address: string;
      symbol: string | null;
      radar_rank: number;
      status: string;
      safety: string | null;
      reason_codes: string[];
      buy_impact_pct: string | null;
      sell_impact_pct: string | null;
      round_trip_loss_pct: string | null;
      liquidity_usd: string | null;
    }>;
  };
  /**
   * Pre-mainnet readiness, in four independent blocks.
   *
   * Every one of them can say "architecturally ready" while the wallet remains
   * unable to submit anything — that separation is the point. `submission_permitted`
   * is the only field that describes what could actually happen, and it is
   * computed server-side from the one transport policy.
   */
  readiness: {
    config_contract: {
      execution_settings_shared: boolean;
      mode: string;
      execution_enabled: boolean;
      autotrade_enabled: boolean;
      safety_policy_version: string;
    };
    transport: {
      envelope: string;
      release_approved: boolean;
      production_transport_installed: boolean;
      submission_permitted: boolean;
      reasons: string[];
      allowed_hosts: string[];
      configured_host: string | null;
    };
    order_validation: { evidence_recheck_installed: boolean; checks: string[] };
    fee_accounting: {
      sol_price_provider: string;
      sol_price_source: string | null;
      sol_price_usd: string | null;
      sol_price_observed_at: string | null;
      sol_price_age_seconds: string | null;
      sol_price_fresh: boolean;
      max_age_seconds: number;
      min_sol_fee_reserve: string;
      priority_fee_sol: string;
      exit_fee_reserve_multiplier: number;
      fee_accounting_ready: boolean;
      unavailable_reason: string | null;
    };
  };
  live_readiness: {
    open_real_positions: number;
    unresolved_intents: Array<{ id: string; mint_address: string; state: string }>;
    kill_switches: Array<{
      kind: string;
      reason: string | null;
      activated_at: string | null;
      activated_by: string | null;
    }>;
    kill_switch_history: Array<{
      kind: string;
      action: string;
      actor: string | null;
      reason: string;
      at: string;
    }>;
  };
  confirmed_lifecycle: {
    consecutive_execution_failures: number;
    last_failure_reason: string | null;
    positions: Array<{
      id: string;
      mint_address: string;
      status: string;
      quantity: string;
      entry_actual_input_amount: string | null;
      entry_actual_output_amount: string | null;
      exit_actual_input_amount: string | null;
      exit_actual_output_amount: string | null;
      realised_gross_pnl_usd: string | null;
      realised_net_pnl_usd: string | null;
      opened_at: string;
      closed_at: string | null;
    }>;
  };
};

type DevnetIntent = {
  id: string;
  state: string;
  action_type: string;
  wallet_public_key: string;
  destination_public_key: string | null;
  input_mint: string;
  output_mint: string | null;
  input_amount_raw: string;
  quote_id: string | null;
  quote_expires_at: string | null;
  simulation_status: string | null;
  approval_status: string | null;
  approval_expires_at: string | null;
  signing_status: string | null;
  transaction_signature: string | null;
  submission_status: string | null;
  submission_retry_count: number;
  confirmation_status: string | null;
  confirmation_slot: number | null;
  failure_reason: string | null;
  reconciliation: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

type DevnetQuote = {
  id: string;
  input_amount_raw: string;
  expected_output_raw: string;
  minimum_output_raw: string;
  slippage_bps: number;
  price_impact_pct: string | null;
  estimated_fee_lamports: number | null;
  provider: string;
  route: Record<string, unknown> | null;
  quoted_at: string;
  expires_at: string;
};

type DevnetIntentDetail = {
  intent: DevnetIntent;
  quote: DevnetQuote | null;
  simulation: {
    status: string | null;
    logs: string[];
    units_consumed: number | null;
    context_slot: number | null;
    blockhash: string | null;
    simulated_at: string | null;
  };
  events: Array<{
    id: string;
    type: string;
    detail: Record<string, unknown>;
    created_at: string;
  }>;
};

function StatusCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line p-4">
      <p className="text-label text-ink-3">{label}</p>
      <p className="mt-2 text-lg font-medium text-ink">{value}</p>
    </div>
  );
}

/**
 * The balance, first thing on the page, with the two things an owner wants to do.
 *
 * Deposit is a real action here because receiving needs nothing but an address on
 * a proven chain — that is exactly what `ready_to_fund` means. Withdrawing is not,
 * and the panel says why instead of offering a button that cannot work: moving SOL
 * out is a signed mainnet submission, the same path a trade takes, and that path is
 * refused by `MAINNET_EXECUTION_DISABLED` and the release constant. Wiring a second
 * way out of this wallet that skipped those barriers would defeat them.
 *
 * The keypair is an ordinary Solana keypair, so the operator can always move funds
 * with their own wallet software. That route is stated plainly rather than hidden
 * behind a disabled control.
 */
/**
 * The one control in MEMESCOPE that moves money without a trade.
 *
 * It has no recipient field, deliberately. The destination is configuration and
 * is re-proven inside the isolated signer, so this form can only ever choose an
 * AMOUNT — which is why it is safe to put on a screen at all.
 *
 * A withdrawal is submitted once and never retried: a lost response means an
 * UNCERTAIN transfer, and pressing again is how one withdrawal becomes two. The
 * button therefore disables itself for the whole request and the result says so
 * explicitly rather than inviting a retry.
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
      void queryClient.invalidateQueries({ queryKey: ["real-wallet-status"] });
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
          Enter an amount above zero and at most {most.toFixed(6)} SOL — the fee
          reserve of {reserve} SOL has to stay behind to pay for the next
          transaction, including a later withdrawal.
        </p>
      ) : null}

      {confirming && !send.isPending && !send.data ? (
        <p className="mt-2 text-xs text-warn">
          Nothing has been sent yet. Press <b>Confirm — send now</b> to send {amount}{" "}
          SOL to {locked.slice(0, 12)}…{locked.slice(-6)}. It is submitted once and
          never retried.
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
          the wallet balance before trying again.
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
  readiness: FundingReadiness | undefined;
}) {
  const [panel, setPanel] = useState<"none" | "deposit" | "withdraw">("none");
  const [copied, setCopied] = useState(false);
  const address = data?.public_key ?? null;
  const balance = data?.sol_balance;
  const ceiling = Number(data?.limits?.max_balance_sol ?? 0);
  const reserve = Number(data?.limits?.min_sol_fee_reserve ?? 0);
  const overCeiling = balance != null && ceiling > 0 && balance > ceiling;
  const headroom = ceiling > 0 && balance != null ? ceiling - balance : null;

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
            Execution wallet balance · {(data?.network ?? "—").toUpperCase()}
            {data?.rpc?.verified ? " · genesis verified" : " · UNVERIFIED CHAIN"}
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
              // Never a guessed rate: every limit on this page is in dollars, so
              // a made-up conversion would be a made-up limit.
              <span className="text-sm text-ink-3">
                USD unavailable — no fresh SOL price
              </span>
            )}
          </p>
          {address ? (
            <button
              type="button"
              onClick={copy}
              className="mt-2 break-all text-left font-mono text-xs text-ink-3 underline decoration-dotted"
            >
              {address}
              <span className="ml-2 not-italic text-accent">
                {copied ? "copied" : "copy"}
              </span>
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
        <p className="mt-3 rounded-md border border-warn/40 bg-warn/[0.08] p-3 text-sm text-warn">
          Above the {ceiling} SOL canary ceiling. The policy REFUSES a wallet over the
          ceiling, so overfunding blocks trading rather than enabling it. Withdraw the
          excess.
        </p>
      ) : null}

      {panel === "deposit" ? (
        <div className="mt-4 rounded-md border border-line bg-raised p-4">
          <p className="text-label text-ink-3">Deposit SOL</p>
          <p className="mt-2 text-sm text-ink-3">
            Send SOL on <span className="text-ink">{data?.network}</span> to the address
            above. Receiving needs only the address and a proven chain, which is what
            {readiness?.ready_to_fund ? " is confirmed" : " is not yet confirmed"} —{" "}
            <span className="text-ink">
              ready_to_fund: {String(readiness?.ready_to_fund ?? "unknown")}
            </span>
            .
          </p>
          <p className="mt-2 text-sm text-ink-3">
            Keep the total under{" "}
            <span className="text-ink">
              {ceiling} SOL
              {data?.sol_price_usd
                ? ` (~$${(ceiling * data.sol_price_usd).toFixed(0)})`
                : ""}
            </span>
            {headroom != null && headroom > 0 ? (
              <>
                {" "}
                — room for <span className="text-ink">{headroom.toFixed(4)} SOL</span> more
              </>
            ) : null}
            . At least <span className="text-ink">{reserve} SOL</span> is held back for
            fees.
          </p>
          <p className="mt-2 text-xs text-ink-3">
            Receive URI: {address ? `solana:${address}` : "—"}. A QR image is
            intentionally not rendered through a third-party service, so the address is
            never disclosed to one.
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
            Sends SOL to the one address below and nowhere else. The destination is
            not something this form can set — it comes from configuration, is checked
            in the service, and is checked again inside the signer against that
            process&apos;s own copy. The worst a compromised caller achieves is
            sending you your own money.
          </p>
          <WithdrawForm data={data} />
          <div className="mt-3 rounded border border-line p-3">
            <p className="text-label text-ink-3">Locked destination</p>
            {data?.withdrawal?.configured && data.withdrawal.locked_to ? (
              <>
                <p className="mt-1 break-all font-mono text-xs text-ink">
                  {data.withdrawal.locked_to}
                </p>
                <p className="mt-2 text-sm text-ink-3">
                  The only address this wallet may ever send to. Deposits stay open —
                  anyone can send to the public address above — but the way out is
                  bounded. Changing it is a deliberate configuration change, not
                  something any screen can do.
                </p>
              </>
            ) : (
              <p className="mt-1 text-sm text-warn">
                No destination nominated
                {data?.withdrawal?.reason ? ` — ${data.withdrawal.reason}` : ""}. An
                unset destination permits nothing rather than anything.
              </p>
            )}
          </div>
          <p className="mt-2 text-sm text-ink-3">
            Balance available after the fee reserve:{" "}
            <span className="text-ink">
              {balance != null ? Math.max(0, balance - reserve).toFixed(6) : "—"} SOL
              {balance != null && data?.sol_price_usd
                ? ` (~$${(Math.max(0, balance - reserve) * data.sol_price_usd).toFixed(2)})`
                : ""}
            </span>
            .
          </p>
        </div>
      ) : null}
    </section>
  );
}

type FundingCheck = {
  key: string;
  title: string;
  owner: "CODE" | "OPERATOR" | "EVIDENCE";
  status: "PASS" | "BLOCKED" | "UNKNOWN";
  detail: string;
  remediation: string;
};

type FundingReadiness = {
  ready_to_fund: boolean;
  ready_to_trade: boolean;
  blocked_total: number;
  blocked_by_owner: Record<string, string[]>;
  checks: FundingCheck[];
};

/**
 * What stands between here and a funded canary.
 *
 * Served by the API, which owns the decision; this renders it. Each blocker
 * names its owner because the three kinds resolve completely differently — a
 * reviewed diff, a human action, or evidence that does not exist yet — and a
 * flat list of twenty-one refusals hides that distinction.
 */
function FundingReadinessPanel({ data }: { data: FundingReadiness | undefined }) {
  const [open, setOpen] = useState<string | null>(null);
  // A supplementary panel must never be able to take down a safety page: an
  // absent or malformed payload renders nothing rather than throwing.
  if (!data || !Array.isArray(data.checks) || data.checks.length === 0) return null;

  const badge = (s: FundingCheck["status"]) =>
    s === "PASS"
      ? "border-up/40 text-up"
      : s === "UNKNOWN"
        ? "border-line text-ink-3"
        : "border-down/40 text-down";

  const owners: FundingCheck["owner"][] = ["OPERATOR", "CODE", "EVIDENCE"];
  const blurb: Record<string, string> = {
    OPERATOR: "Your hands — a key, a funded wallet, a configuration decision.",
    CODE: "A reviewed diff. An operator with environment access alone cannot do this.",
    EVIDENCE: "A result the tournament has not produced. No engineering closes it.",
  };

  return (
    <section className="mt-6 rounded-lg border border-line p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <p className="text-label text-ink-3">Funding readiness</p>
          <p className="mt-1 text-sm text-ink">
            {data.ready_to_fund
              ? "The rail is configured — this wallet can be funded."
              : "Not ready to fund yet."}{" "}
            <span className="text-ink-3">
              {data.blocked_total} of {data.checks.length} preconditions outstanding.
            </span>
          </p>
        </div>
        <div className="flex gap-2 text-xs">
          <span
            className={`rounded border px-2 py-1 ${
              data.ready_to_fund ? "border-up/40 text-up" : "border-down/40 text-down"
            }`}
          >
            READY TO FUND: {data.ready_to_fund ? "YES" : "NO"}
          </span>
          <span
            className={`rounded border px-2 py-1 ${
              data.ready_to_trade ? "border-up/40 text-up" : "border-down/40 text-down"
            }`}
          >
            READY TO TRADE: {data.ready_to_trade ? "YES" : "NO"}
          </span>
        </div>
      </div>

      {owners.map((owner) => {
        const rows = data.checks.filter((c) => c.owner === owner);
        if (rows.length === 0) return null;
        const done = rows.filter((c) => c.status === "PASS").length;
        return (
          <div key={owner} className="mt-4">
            <p className="text-label text-ink-3">
              {owner} · {done}/{rows.length} clear
            </p>
            <p className="mt-0.5 text-xs text-ink-3">{blurb[owner]}</p>
            <ul className="mt-2 space-y-1">
              {rows.map((c) => (
                <li key={c.key} className="rounded border border-line-subtle p-2">
                  <button
                    className="flex w-full items-baseline justify-between gap-3 text-left"
                    onClick={() => setOpen(open === c.key ? null : c.key)}
                    type="button"
                  >
                    <span className="text-sm text-ink">{c.title}</span>
                    <span
                      className={`shrink-0 rounded border px-1.5 text-[10px] ${badge(
                        c.status,
                      )}`}
                    >
                      {c.status}
                    </span>
                  </button>
                  <p className="mt-1 font-mono text-[11px] text-ink-3">{c.detail}</p>
                  {open === c.key ? (
                    <p className="mt-1 text-xs leading-relaxed text-ink-3">
                      {c.remediation}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        );
      })}

      <p className="mt-4 border-t border-line pt-3 text-xs leading-relaxed text-ink-3">
        To fund this wallet you generate the keypair yourself, on your own machine —{" "}
        <code className="text-ink">
          python -m app.real_wallet.generate_wallet --output /secure/path/memescope.json
        </code>{" "}
        — set <code className="text-ink">REAL_WALLET_PUBLIC_KEY</code> and{" "}
        <code className="text-ink">REAL_WALLET_EXECUTION_SECRET_FILE</code>, then send SOL
        to the address shown below. The command never contacts Solana and never sends
        funds, and no key material ever reaches this dashboard or the API.
      </p>
    </section>
  );
}

type AutotradeState = {
  enabled: boolean;
  nominated_strategy: string | null;
  started_at: string | null;
  started_by: string | null;
  start_reason: string | null;
  stopped_at: string | null;
  stopped_by: string | null;
  stop_reason: string | null;
  authorises_execution: boolean;
  history?: Array<{
    action: string;
    actor: string | null;
    reason: string | null;
    nominated_strategy: string | null;
    occurred_at: string;
  }>;
};

/**
 * The operator start/stop control.
 *
 * Deliberately asymmetric, and the asymmetry is stated on the surface rather
 * than buried in a tooltip. STOP is unconditional: it needs no other condition
 * to be true and can never be refused. START records an intent and authorises
 * nothing — every barrier is evaluated independently, so on today's deployment
 * turning it on leaves submission exactly as impossible as it was.
 *
 * The server owns both decisions. This renders them.
 */
function AutotradeControl() {
  const queryClient = useQueryClient();
  const [strategy, setStrategy] = useState("V6-06");
  const [reason, setReason] = useState("");

  const state = useQuery<AutotradeState>({
    queryKey: ["real-wallet", "autotrade"],
    queryFn: () => api.get<AutotradeState>("/real-wallet/autotrade"),
    refetchInterval: 30_000,
  });

  const mutate = useMutation({
    mutationFn: (vars: { action: "start" | "stop" }) =>
      api.post<AutotradeState>(
        `/real-wallet/autotrade/${vars.action}`,
        vars.action === "start" ? { strategy_id: strategy, reason } : { reason },
      ),
    onSuccess: () => {
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["real-wallet"] });
    },
  });

  const data = state.data;
  const running = data?.enabled === true;
  const canAct = reason.trim().length >= 3 && !mutate.isPending;

  return (
    <section className="mt-6 rounded-lg border border-line p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <p className="text-label text-ink-3">Autonomous trading</p>
          <p className="mt-1 text-sm text-ink">
            {running ? (
              <>
                STARTED — nominated strategy{" "}
                <span className="font-mono">{data?.nominated_strategy}</span>
              </>
            ) : (
              "STOPPED"
            )}
          </p>
        </div>
        <span
          className={`rounded border px-2 py-1 text-xs ${
            running ? "border-up/40 text-up" : "border-line text-ink-3"
          }`}
        >
          {running ? "INTENT: ON" : "INTENT: OFF"}
        </span>
      </div>

      <p className="mt-2 rounded border border-warn/40 bg-warn/[0.06] p-2 text-xs leading-relaxed text-warn">
        Starting authorises nothing. Mode, the three enable flags, the release
        constant, the mainnet clause, the submission guard, SEC-2 freshness, network
        verification and the canary limits are each evaluated independently. On this
        deployment submission is still impossible. Stopping, by contrast, is
        unconditional and takes effect immediately.
      </p>

      <div className="mt-3 grid gap-2 sm:grid-cols-[160px_1fr_auto_auto]">
        <select
          className="rounded border border-line bg-transparent px-2 py-2 text-sm text-ink"
          disabled={running}
          onChange={(e) => setStrategy(e.target.value)}
          value={strategy}
        >
          {Array.from({ length: 20 }, (_, i) => `V6-${String(i + 1).padStart(2, "0")}`)
            .filter((id) => id !== "V6-01")
            .map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
        </select>
        <input
          className="rounded border border-line bg-transparent px-2 py-2 text-sm text-ink"
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason (recorded and attributed, min 3 chars)"
          value={reason}
        />
        <button
          className="rounded border border-up/40 px-3 py-2 text-sm text-up disabled:opacity-40"
          disabled={!canAct || running}
          onClick={() => mutate.mutate({ action: "start" })}
          type="button"
        >
          Start
        </button>
        <button
          className="rounded border border-down/40 px-3 py-2 text-sm text-down disabled:opacity-40"
          disabled={!canAct}
          onClick={() => mutate.mutate({ action: "stop" })}
          type="button"
        >
          Stop
        </button>
      </div>

      {data?.history?.length ? (
        <ul className="mt-3 space-y-0.5 border-t border-line pt-3 font-mono text-[11px] text-ink-3">
          {data.history.slice(0, 6).map((h, i) => (
            <li key={i}>
              {h.occurred_at.slice(0, 16).replace("T", " ")} · {h.action} ·{" "}
              {h.nominated_strategy ?? "—"} · {h.actor ?? "system"} · {h.reason ?? ""}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/**
 * The seatbelt.
 *
 * A deliberate speed bump in front of the only surface in the product that
 * could ever move real money. It is **not** an access control and is not
 * presented as one — the server's admin role is the access control, and this
 * cannot be a second one: anything the browser can check, the browser can be
 * told to skip.
 *
 * What it is worth is the pause. This page has a start/stop control and a
 * funding address on it; arriving here by a stray click and arriving here on
 * purpose should not feel identical. Acknowledged once per browser session.
 */
function Seatbelt({ onEnter }: { onEnter: () => void }) {
  return (
    <main>
      <p className="text-label text-accent">Execution wallet</p>
      <h1 className="mt-2 text-3xl font-medium text-ink">Fasten your seatbelt</h1>
      <section className="mt-6 max-w-2xl rounded-lg border border-warn/40 bg-warn/[0.08] p-4">
        <p className="text-label text-warn">ACCESS APPROVED — READ THIS FIRST</p>
        <ul className="mt-3 space-y-2 text-sm text-ink-3">
          <li>
            <span className="text-ink">This is the only page that could ever touch real money.</span>{" "}
            Everything else in MEMESCOPE — all twenty V6 wallets, the Arena, the
            Track Record — is simulated and cannot spend anything.
          </li>
          <li>
            <span className="text-ink">Today it still cannot.</span> Mainnet submission
            is refused by two independent code constants, and no strategy has earned
            real money. Nothing on this page can change that. The signer now exists and
            holds the pinned key — which changes who could sign, not whether anything
            may be submitted.
          </li>
          <li>
            <span className="text-ink">The funding address here is real.</span> SOL sent
            to it is gone from wherever it came from. Keep the balance under the
            canary ceiling — a wallet above it is refused, not rewarded.
          </li>
          <li>
            <span className="text-ink">Stop always works.</span> The start/stop control
            below can be stopped unconditionally, from any state, at any time.
          </li>
        </ul>
        <button
          className="mt-4 rounded border border-warn/60 px-4 py-2 text-sm text-warn hover:bg-warn/10"
          onClick={onEnter}
          type="button"
        >
          I understand — enter the execution wallet
        </button>
      </section>
      <p className="mt-4 max-w-2xl text-xs text-ink-3">
        This acknowledgement is a pause, not a permission. Access is granted by your
        account&rsquo;s administrator role on the server; this screen only makes sure
        you meant to be here.
      </p>
    </main>
  );
}

export default function RealWalletPage() {
  const queryClient = useQueryClient();
  // Acknowledged once per browser session; a pause, never a permission.
  const [buckled, setBuckled] = useState(
    () =>
      typeof window !== "undefined" &&
      window.sessionStorage.getItem("memescope.seatbelt") === "1",
  );
  const [destination, setDestination] = useState("");
  const [lamports, setLamports] = useState("100000");
  const [selectedIntentId, setSelectedIntentId] = useState<string | null>(null);
  const [approvalChecked, setApprovalChecked] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["real-wallet-status"],
    queryFn: () => api.get<WalletStatus>("/real-wallet/status"),
    retry: false,
    refetchInterval: 30_000,
  });
  const readinessQuery = useQuery<FundingReadiness>({
    queryKey: ["real-wallet", "funding-readiness"],
    queryFn: () => api.get<FundingReadiness>("/real-wallet/funding-readiness"),
    refetchInterval: 60_000,
  });
  const intentsQuery = useQuery({
    queryKey: ["real-wallet-devnet-intents"],
    queryFn: () => api.get<DevnetIntent[]>("/real-wallet/devnet/intents"),
    retry: false,
    refetchInterval: 10_000,
  });
  const detailQuery = useQuery({
    queryKey: ["real-wallet-devnet-intent", selectedIntentId],
    queryFn: () =>
      api.get<DevnetIntentDetail>(`/real-wallet/devnet/intents/${selectedIntentId}`),
    enabled: selectedIntentId !== null,
    retry: false,
  });
  const refreshDevnet = async () => {
    await queryClient.invalidateQueries({ queryKey: ["real-wallet-devnet-intents"] });
    if (selectedIntentId) {
      await queryClient.invalidateQueries({
        queryKey: ["real-wallet-devnet-intent", selectedIntentId],
      });
    }
  };
  const createIntent = useMutation({
    mutationFn: async () => {
      const quote = await api.post<DevnetQuote>(
        "/real-wallet/devnet/quotes/native-transfer",
        {
          destination_public_key: destination.trim(),
          lamports: Number(lamports),
        },
      );
      return api.post<DevnetIntent>("/real-wallet/devnet/intents", {
        quote_id: quote.id,
        idempotency_key: crypto.randomUUID(),
      });
    },
    onSuccess: async (intent) => {
      setActionError(null);
      setSelectedIntentId(intent.id);
      await refreshDevnet();
    },
    onError: () =>
      setActionError(
        "Quote or intent creation was rejected. Check the devnet destination and tiny amount.",
      ),
  });
  const action = useMutation({
    mutationFn: async ({
      intentId,
      actionName,
    }: {
      intentId: string;
      actionName: string;
    }) => {
      const body =
        actionName === "approve"
          ? { confirmation_phrase: "APPROVE_DEVNET_TRANSFER" }
          : undefined;
      return api.post<DevnetIntent>(
        `/real-wallet/devnet/intents/${intentId}/${actionName}`,
        body,
      );
    },
    onSuccess: async () => {
      setActionError(null);
      setApprovalChecked(false);
      await refreshDevnet();
    },
    onError: () =>
      setActionError(
        "The requested manual step was rejected or the isolated signer is unavailable.",
      ),
  });
  const intents = Array.isArray(intentsQuery.data) ? intentsQuery.data : [];
  const detail = detailQuery.data;
  const selected =
    detail?.intent ?? intents.find((intent) => intent.id === selectedIntentId) ?? null;
  const quote = detail?.quote;
  if (query.isError) {
    // "Restricted" used to be shown for ANY failure, which sent an owner whose
    // session had merely expired hunting for a permissions problem that did not
    // exist. 401 and 403 are different questions and get different answers.
    const failure = query.error;
    const status = failure instanceof ApiError ? failure.status : null;
    const signedOut = status === 401;
    return (
      <main>
        <p className="text-label text-accent">
          {signedOut ? "Signed out" : status === 403 ? "Restricted" : "Unavailable"}
        </p>
        <h1 className="mt-2 text-2xl font-medium text-ink">
          {signedOut
            ? "Your session has expired — sign in again to reach the execution wallet."
            : status === 403
              ? "Execution wallet status is available only to an account-level administrator."
              : "The execution wallet status could not be read."}
        </h1>
        <p className="mt-3 max-w-2xl text-sm text-ink-3">
          {signedOut ? (
            <>
              The access code on the homepage unlocks the dashboard, but it is a
              site-wide cookie rather than an account &mdash; and this page needs an
              account. Sign in with the one holding the administrator role.
            </>
          ) : status === 403 ? (
            <>
              You are signed in, but this account does not hold the administrator
              role. That role is granted on the server; no control on this page can
              grant it.
            </>
          ) : (
            <>
              The request failed before any answer about permissions was reached
              {status ? ` (HTTP ${status})` : ""}. This is not a statement that you
              lack access.
            </>
          )}
        </p>
        {signedOut ? (
          <a
            href="/login"
            className="mt-4 inline-block rounded border border-accent/50 px-4 py-2 text-sm text-accent hover:bg-accent/10"
          >
            Go to sign in
          </a>
        ) : null}
      </main>
    );
  }
  const data = query.data;
  const readiness = data?.readiness;
  // The address, its copy control and the Solscan link all live in BalanceCard now.
  if (!buckled) {
    return (
      <Seatbelt
        onEnter={() => {
          window.sessionStorage.setItem("memescope.seatbelt", "1");
          setBuckled(true);
        }}
      />
    );
  }

  return (
    <main>
      <p className="text-label text-accent">
        Operator only · {(data?.network ?? "—").toUpperCase()}
      </p>
      <h1 className="mt-2 text-3xl font-medium text-ink">MEMESCOPE execution wallet</h1>
      <p className="mt-2 max-w-2xl text-sm text-ink-3">
        Dedicated low-balance wallet. Deposits are open and withdrawal to the nominated
        address works. Trading is the part that stays gated: it needs a fresh quote,
        a successful simulation, the isolated signer, and the autotrade switch.
      </p>
      <BalanceCard data={data} readiness={readinessQuery.data} />
      <section className="mt-6 rounded-lg border border-warn/40 bg-warn/[0.08] p-4">
        <p className="text-label text-warn">
          {data?.lock_state === "LOCKED"
            ? "LOCKED · NO REAL SUBMISSION IS POSSIBLE"
            : "SUBMISSION PERMITTED — VERIFY THIS IS INTENDED"}
        </p>
        <p className="mt-1 text-sm text-ink-3">
          Mode {data?.mode ?? "—"} · execution{" "}
          {data?.execution_enabled ? "ENABLED" : "DISABLED"} · autotrade{" "}
          {data?.autotrade_enabled ? "ENABLED" : "DISABLED"} · network{" "}
          {data?.network ?? "—"}. Every transfer requires a fresh quote, successful
          simulation, explicit manual approval, and an isolated signer. Paper Wallet and
          Generation 2 cannot reach this workflow.
        </p>
        <p className="mt-2 text-sm text-ink-3">
          This page is read-only with respect to every safety barrier. No control here can
          change the mode, enable execution, widen a limit, or clear a barrier other than
          an armed kill switch, which is a separate authenticated and attributed action.
        </p>
      </section>
      <FundingReadinessPanel data={readinessQuery.data} />
      <AutotradeControl />
      <section className="mt-6 rounded-lg border border-line p-4">
        <p className="text-label text-ink-3">Manual devnet verification</p>
        <p className="mt-1 text-sm text-ink-3">
          Creates a quote and DRAFT intent only. Simulation, approval, signing, submission,
          and confirmation each remain separate operator actions.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_180px_auto]">
          <label className="text-sm text-ink-3">
            Recipient public address
            <input
              className="mt-1 w-full rounded border border-line bg-raised px-3 py-2 text-ink"
              onChange={(event) => setDestination(event.target.value)}
              placeholder="Devnet recipient"
              value={destination}
            />
          </label>
          <label className="text-sm text-ink-3">
            Lamports (max 1,000,000)
            <input
              className="mt-1 w-full rounded border border-line bg-raised px-3 py-2 text-ink"
              inputMode="numeric"
              min="1"
              onChange={(event) => setLamports(event.target.value)}
              type="number"
              value={lamports}
            />
          </label>
          <button
            className="self-end rounded bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            disabled={
              createIntent.isPending || !destination.trim() || Number(lamports) <= 0
            }
            onClick={() => createIntent.mutate()}
            type="button"
          >
            {createIntent.isPending ? "Creating…" : "Create quote & intent"}
          </button>
        </div>
        {actionError ? <p className="mt-3 text-sm text-down">{actionError}</p> : null}
      </section>
      <section className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="overflow-hidden rounded-lg border border-line">
          <div className="border-b border-line p-4">
            <p className="text-label text-ink-3">Manual devnet intent ledger</p>
            <p className="mt-1 text-sm text-ink-3">
              Quote → simulate → approve → sign → submit → confirm → reconcile.
            </p>
          </div>
          <div className="divide-y divide-line-subtle">
            {intents.length ? (
              intents.map((intent) => (
                <button
                  className={`block w-full p-4 text-left text-sm ${selectedIntentId === intent.id ? "bg-raised" : ""}`}
                  key={intent.id}
                  onClick={() => setSelectedIntentId(intent.id)}
                  type="button"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium text-ink">{intent.state}</span>
                    <span className="text-xs text-ink-3">
                      {new Date(intent.created_at).toLocaleString()}
                    </span>
                  </div>
                  <code className="mt-1 block truncate text-xs text-ink-3">
                    {intent.destination_public_key ?? "—"}
                  </code>
                  <p className="mt-1 text-ink-3">
                    {intent.input_amount_raw} lamports ·{" "}
                    {intent.simulation_status ?? "not simulated"}
                  </p>
                </button>
              ))
            ) : (
              <p className="p-4 text-sm text-ink-3">No manual devnet intents yet.</p>
            )}
          </div>
        </div>
        <div className="rounded-lg border border-line p-4">
          <p className="text-label text-ink-3">Selected intent</p>
          {selected ? (
            <>
              <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-ink-3">State</dt>
                  <dd className="text-ink">{selected.state}</dd>
                </div>
                <div>
                  <dt className="text-ink-3">Approval</dt>
                  <dd className="text-ink">{selected.approval_status ?? "not approved"}</dd>
                </div>
                <div>
                  <dt className="text-ink-3">Wallet</dt>
                  <dd className="break-all text-ink">{selected.wallet_public_key}</dd>
                </div>
                <div>
                  <dt className="text-ink-3">Recipient</dt>
                  <dd className="break-all text-ink">
                    {selected.destination_public_key ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-ink-3">Amount</dt>
                  <dd className="text-ink">{selected.input_amount_raw} lamports</dd>
                </div>
                <div>
                  <dt className="text-ink-3">Quote expiry</dt>
                  <dd className="text-ink">
                    {selected.quote_expires_at
                      ? new Date(selected.quote_expires_at).toLocaleString()
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-ink-3">Simulation</dt>
                  <dd className="text-ink">
                    {selected.simulation_status ?? "not run"}
                    {detail?.simulation.units_consumed
                      ? ` · ${detail.simulation.units_consumed} CU`
                      : ""}
                  </dd>
                </div>
                <div>
                  <dt className="text-ink-3">Signature / confirmation</dt>
                  <dd className="break-all text-ink">
                    {selected.transaction_signature ?? "—"}
                    {selected.confirmation_status
                      ? ` · ${selected.confirmation_status}`
                      : ""}
                  </dd>
                </div>
              </dl>
              {quote ? (
                <p className="mt-4 rounded border border-line-subtle bg-raised p-3 text-sm text-ink-3">
                  Quote: expected {quote.expected_output_raw} lamports · minimum{" "}
                  {quote.minimum_output_raw} · slippage {quote.slippage_bps} bps · price
                  impact {quote.price_impact_pct ?? "0"}% · estimated fee{" "}
                  {quote.estimated_fee_lamports ?? "—"} lamports · {quote.provider}.
                </p>
              ) : null}
              <div className="mt-4 flex flex-wrap gap-2">
                {selected.state === "QUOTED" ? (
                  <button
                    className="rounded border border-line px-3 py-2 text-sm text-ink"
                    disabled={action.isPending}
                    onClick={() =>
                      action.mutate({ intentId: selected.id, actionName: "simulate" })
                    }
                    type="button"
                  >
                    Simulate
                  </button>
                ) : null}
                {selected.state === "AWAITING_APPROVAL" ? (
                  <>
                    <label className="flex items-center gap-2 text-sm text-ink-3">
                      <input
                        checked={approvalChecked}
                        onChange={(event) => setApprovalChecked(event.target.checked)}
                        type="checkbox"
                      />{" "}
                      I reviewed the simulation and authorize this DEVNET transfer.
                    </label>
                    <button
                      className="rounded bg-warn px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
                      disabled={!approvalChecked || action.isPending}
                      onClick={() =>
                        action.mutate({ intentId: selected.id, actionName: "approve" })
                      }
                      type="button"
                    >
                      Explicitly approve
                    </button>
                  </>
                ) : null}
                {selected.state === "APPROVED" ? (
                  <button
                    className="rounded border border-line px-3 py-2 text-sm text-ink disabled:opacity-50"
                    disabled={action.isPending}
                    onClick={() =>
                      action.mutate({ intentId: selected.id, actionName: "sign" })
                    }
                    type="button"
                  >
                    Ask isolated signer
                  </button>
                ) : null}
                {selected.state === "SIGNED" ? (
                  <button
                    className="rounded border border-line px-3 py-2 text-sm text-ink disabled:opacity-50"
                    disabled={action.isPending}
                    onClick={() =>
                      action.mutate({ intentId: selected.id, actionName: "submit" })
                    }
                    type="button"
                  >
                    Submit to devnet
                  </button>
                ) : null}
                {selected.state === "SUBMITTED" ? (
                  <button
                    className="rounded border border-line px-3 py-2 text-sm text-ink disabled:opacity-50"
                    disabled={action.isPending}
                    onClick={() =>
                      action.mutate({ intentId: selected.id, actionName: "confirm" })
                    }
                    type="button"
                  >
                    Confirm & reconcile
                  </button>
                ) : null}
                {["DRAFT", "QUOTED", "AWAITING_APPROVAL"].includes(selected.state) ? (
                  <button
                    className="rounded border border-down/40 px-3 py-2 text-sm text-down disabled:opacity-50"
                    disabled={action.isPending}
                    onClick={() =>
                      action.mutate({ intentId: selected.id, actionName: "cancel" })
                    }
                    type="button"
                  >
                    Cancel
                  </button>
                ) : null}
              </div>
              {selected.reconciliation ? (
                <pre className="mt-4 overflow-x-auto rounded bg-raised p-3 text-xs text-ink-3">
                  {JSON.stringify(selected.reconciliation, null, 2)}
                </pre>
              ) : null}
              {detail?.simulation.logs.length ? (
                <pre className="mt-4 max-h-40 overflow-auto rounded bg-raised p-3 text-xs text-ink-3">
                  {detail.simulation.logs.join("\n")}
                </pre>
              ) : null}
            </>
          ) : (
            <p className="mt-2 text-sm text-ink-3">
              Select an intent to inspect its quote, simulation, approval, signature, and
              reconciliation evidence.
            </p>
          )}
        </div>
      </section>
      <section className="mt-6 overflow-x-auto rounded-lg border border-line">
        <div className="p-4">
          <p className="text-label text-ink-3">Dry-run decisions</p>
          <p className="mt-1 text-sm text-ink-3">
            {data?.dry_run.feature_enabled ? "Recording enabled" : "Recording disabled"}. No
            order is signed or submitted.
          </p>
        </div>
        <table className="w-full text-left text-sm">
          <thead className="border-y border-line text-ink-3">
            <tr>
              <th className="p-3">Token</th>
              <th>Rank</th>
              <th>Safety</th>
              <th>Impact</th>
              <th>Decision</th>
              <th className="p-3">Reason</th>
            </tr>
          </thead>
          <tbody>
            {data?.dry_run.decisions.map((row) => (
              <tr
                key={`${row.mint_address}-${row.radar_rank}`}
                className="border-b border-line-subtle last:border-0"
              >
                <td className="p-3">
                  <span className="text-ink">{row.symbol ?? "—"}</span>
                  <code className="ml-2 text-xs text-ink-3">
                    {row.mint_address.slice(0, 8)}
                  </code>
                </td>
                <td>{row.radar_rank}</td>
                <td>{row.safety ?? "—"}</td>
                <td>
                  {row.buy_impact_pct ?? "—"} / {row.sell_impact_pct ?? "—"}
                </td>
                <td className={row.status === "WOULD_BUY" ? "text-up" : "text-warn"}>
                  {row.status}
                </td>
                <td className="p-3 text-xs text-ink-3">
                  {row.reason_codes.join(", ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatusCard label="Network" value={(data?.network ?? "devnet").toUpperCase()} />
        <StatusCard label="SOL balance" value={data?.sol_balance?.toFixed(6) ?? "—"} />
        <StatusCard
          label="Funding"
          value={(data?.funding_status ?? "unknown").toUpperCase()}
        />
        <StatusCard label="Trading mode" value={(data?.mode ?? "disabled").toUpperCase()} />
        <StatusCard label="Safety gate" value={data?.safety_gate ?? "—"} />
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <StatusCard
          label="Execution"
          value={data?.execution_enabled ? "ENABLED" : "DISABLED"}
        />
        <StatusCard
          label="Autotrade"
          value={data?.autotrade_enabled ? "ENABLED" : "DISABLED"}
        />
        <StatusCard label="Custody boundary" value="API HAS NO SIGNER" />
        <StatusCard label="RPC" value={data?.rpc.verified ? "VERIFIED" : "UNVERIFIED"} />
        <StatusCard
          label="SOL fee reserve"
          value={`${data?.limits.min_sol_fee_reserve ?? "—"} SOL`}
        />
      </div>
      <section className="mt-6 overflow-x-auto rounded-lg border border-line">
        <div className="p-4">
          <p className="text-label text-ink-3">On-chain SPL balances</p>
          <p className="mt-1 text-sm text-ink-3">
            Standard SPL and Token-2022 accounts, read from the verified wallet RPC. Token
            labels are shown only when MEMESCOPE already has metadata for the mint.
          </p>
        </div>
        <table className="w-full text-left text-sm">
          <thead className="border-y border-line text-ink-3">
            <tr>
              <th className="p-3">Token</th>
              <th>Quantity</th>
              <th>Decimals</th>
              <th className="p-3">Mint</th>
            </tr>
          </thead>
          <tbody>
            {data?.token_balances.length ? (
              data.token_balances.map((token) => (
                <tr
                  key={token.token_account}
                  className="border-b border-line-subtle last:border-0"
                >
                  <td className="p-3 text-ink">
                    {token.symbol ?? token.name ?? "Unknown SPL"}
                  </td>
                  <td>{token.quantity}</td>
                  <td>{token.decimals}</td>
                  <td className="p-3">
                    <code className="text-xs text-ink-3">{token.mint_address}</code>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="p-3 text-ink-3" colSpan={4}>
                  No token accounts available.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
      {/* Pre-mainnet readiness. Four blocks that each say whether a *capability*
          exists, above one line that says whether anything could actually be
          submitted. Keeping those separate is the point: "architecturally
          ready" and "live enabled" are different claims, and conflating them is
          how a dashboard ends up implying a system is armed when it is not. */}
      <section className="mt-6 rounded-lg border border-line p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-label text-ink-3">Pre-mainnet readiness</p>
          <span
            className={
              readiness?.transport.submission_permitted
                ? "rounded-sm border border-down/30 bg-down/[0.08] px-2 py-0.5 text-label uppercase text-down"
                : "rounded-sm border border-line bg-raised px-2 py-0.5 text-label uppercase text-ink-3"
            }
          >
            {readiness?.transport.submission_permitted
              ? "SUBMISSION PERMITTED"
              : "SUBMISSION BLOCKED"}
          </span>
        </div>
        <p className="mt-1 text-sm text-ink-3">
          Architecturally ready is not live enabled. There is no enable control on this
          page, and none anywhere in the product.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatusCard
            label="Config contract"
            value={
              readiness?.config_contract.execution_settings_shared ? "SHARED" : "DRIFT"
            }
          />
          <StatusCard
            label="Transport envelope"
            value={(readiness?.transport.envelope ?? "—").toUpperCase()}
          />
          <StatusCard
            label="Order evidence"
            value={
              readiness?.order_validation.evidence_recheck_installed ? "RE-CHECKED" : "OFF"
            }
          />
          <StatusCard
            label="Fee accounting"
            value={readiness?.fee_accounting.fee_accounting_ready ? "READY" : "NOT READY"}
          />
        </div>
        {/* Why submission is blocked, from the one server-side policy. Listing
            the reasons rather than a single flag means a reader can see which
            control is doing the work. */}
        {readiness?.transport.reasons.length ? (
          <ul className="mt-3 flex flex-wrap gap-2">
            {readiness.transport.reasons.map((reason) => (
              <li
                key={reason}
                className="rounded-sm border border-line px-2 py-0.5 text-xs text-ink-3"
              >
                {reason}
              </li>
            ))}
          </ul>
        ) : null}
        <p className="mt-3 text-xs text-ink-3">
          Release approved: {readiness?.transport.release_approved ? "yes" : "no"} ·
          Production transport:{" "}
          {readiness?.transport.production_transport_installed
            ? "installed"
            : "not installed"}{" "}
          · Allowed hosts: {readiness?.transport.allowed_hosts.join(", ") ?? "—"}
        </p>
        <p className="mt-1 text-xs text-ink-3">
          SOL/USD:{" "}
          {readiness?.fee_accounting.sol_price_usd
            ? `$${readiness.fee_accounting.sol_price_usd} via ${readiness.fee_accounting.sol_price_source} (${readiness.fee_accounting.sol_price_age_seconds}s old, ${readiness.fee_accounting.sol_price_fresh ? "fresh" : "stale"})`
            : "unavailable"}{" "}
          · Reserve: {readiness?.fee_accounting.min_sol_fee_reserve ?? "—"} SOL +{" "}
          {readiness?.fee_accounting.exit_fee_reserve_multiplier ?? "—"}× transaction cost
          {readiness?.fee_accounting.unavailable_reason
            ? ` · ${readiness.fee_accounting.unavailable_reason}`
            : ""}
        </p>
      </section>
      <section className="mt-6 rounded-lg border border-line p-4">
        <p className="text-label text-ink-3">Live readiness</p>
        <p className="mt-1 text-sm text-ink-3">
          Submission transport: {data?.live_submission_transport ?? "not installed"}. New
          entries remain fail-closed.
        </p>
        <p className="mt-2 text-sm text-ink-3">
          Open real positions: {data?.live_readiness.open_real_positions ?? 0}. Unresolved
          intents: {data?.live_readiness.unresolved_intents.length ?? 0}. Active kill
          switches: {data?.live_readiness.kill_switches.length ?? 0}.
        </p>
        {data?.live_readiness.kill_switches.length ? (
          <ul className="mt-3 space-y-1 text-sm text-down">
            {data.live_readiness.kill_switches.map((sw) => (
              <li key={sw.kind}>
                <span className="font-medium">{sw.kind}</span> — {sw.reason ?? "no reason"}
                {sw.activated_by ? ` · armed by ${sw.activated_by}` : " · armed by system"}
                {sw.activated_at ? ` · ${sw.activated_at}` : ""}
              </li>
            ))}
          </ul>
        ) : null}
        {data?.live_readiness.kill_switch_history.length ? (
          <details className="mt-3 text-sm text-ink-3">
            <summary className="cursor-pointer">Kill-switch history</summary>
            <ul className="mt-2 space-y-1">
              {data.live_readiness.kill_switch_history.map((event, index) => (
                <li key={`${event.kind}-${event.at}-${index}`}>
                  {event.at} · {event.kind} {event.action} by{" "}
                  {event.actor ?? "system"} — {event.reason}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>
      <section className="mt-6 rounded-lg border border-line p-4">
        <p className="text-label text-ink-3">Token security gate</p>
        <p className="mt-1 text-sm text-ink-3">
          {data?.security_gate.shared_with_paper
            ? "Real entries use the same SEC-2 evaluator and the same entry policy as Paper. There is no Real-Wallet-only security path."
            : "Security gate provenance unavailable."}
        </p>
        <p className="mt-2 text-sm text-ink-3">
          Mandatory checks: {data?.security_gate.mandatory_checks.join(", ") ?? "—"}.
          Evidence older than {data?.security_gate.max_evidence_age_seconds ?? "—"}s
          cannot authorise a buy. UNKNOWN and unavailable both refuse.
        </p>
      </section>
      <section className="mt-6 rounded-lg border border-line p-4">
        <p className="text-label text-ink-3">Program allowlist</p>
        <p className="mt-1 text-sm text-ink-3">
          Every top-level program in a signed transaction must appear here and must
          resolve from the transaction&apos;s own static keys. A program supplied through
          an address lookup table is refused because it cannot be audited offline.
        </p>
        <ul className="mt-2 space-y-1">
          {data?.program_allowlist.map((program) => (
            <li key={program}>
              <code className="text-xs text-ink">{program}</code>
            </li>
          ))}
        </ul>
      </section>
      <section className="mt-6 overflow-x-auto rounded-lg border border-line">
        <div className="p-4">
          <p className="text-label text-ink-3">Confirmed lifecycle ledger</p>
          <p className="mt-1 text-sm text-ink-3">
            Test-only settlement evidence. Consecutive execution failures:{" "}
            {data?.confirmed_lifecycle.consecutive_execution_failures ?? 0}
            {data?.confirmed_lifecycle.last_failure_reason
              ? ` (${data.confirmed_lifecycle.last_failure_reason})`
              : ""}
            .
          </p>
        </div>
        <table className="w-full text-left text-sm">
          <thead className="border-y border-line text-ink-3">
            <tr>
              <th className="p-3">Token</th>
              <th>State</th>
              <th>Confirmed quantity</th>
              <th>Entry / exit USDC</th>
              <th className="p-3">Realised P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {data?.confirmed_lifecycle.positions.map((position) => (
              <tr key={position.id} className="border-b border-line-subtle last:border-0">
                <td className="p-3">
                  <code className="text-xs text-ink">
                    {position.mint_address.slice(0, 12)}
                  </code>
                </td>
                <td className={position.status === "CLOSED" ? "text-ink-3" : "text-up"}>
                  {position.status}
                </td>
                <td>{position.quantity}</td>
                <td>
                  {position.entry_actual_input_amount ?? "—"} /{" "}
                  {position.exit_actual_output_amount ?? "—"}
                </td>
                <td className="p-3">
                  {position.realised_net_pnl_usd === null
                    ? "—"
                    : `$${position.realised_net_pnl_usd}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="mt-6 rounded-lg border border-line p-4">
        <p className="text-label text-ink-3">Canary limits</p>
        <p className="mt-1 text-sm text-ink-3">
          Server-owned. No control on this page can change or exceed any of them.
        </p>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <dt className="text-ink-3">Entry size</dt>
            <dd className={data?.limits.entry_size_configured ? "text-ink" : "text-down"}>
              {data?.limits.entry_size_configured
                ? `$${data.limits.entry_size_usd}`
                : "NOT CONFIGURED — entries refuse"}
            </dd>
          </div>
          <div>
            <dt className="text-ink-3">Max trade</dt>
            <dd className="text-ink">${data?.limits.max_trade_usd ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-3">Max positions</dt>
            <dd className="text-ink">{data?.limits.max_open_positions ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-3">Max exposure</dt>
            <dd className="text-ink">${data?.limits.max_total_exposure_usd ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-3">Daily notional</dt>
            <dd className="text-ink">${data?.limits.max_daily_notional_usd ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-3">Daily trades</dt>
            <dd className="text-ink">{data?.limits.max_daily_trades ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-3">Daily loss</dt>
            <dd className="text-ink">${data?.limits.max_daily_loss_usd ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-3">Max wallet balance</dt>
            <dd className="text-ink">
              {data?.limits.max_balance_sol ?? "—"} SOL
              {data ? ` (${data.limits.max_balance_lamports} lamports)` : ""}
            </dd>
          </div>
        </dl>
      </section>
    </main>
  );
}
