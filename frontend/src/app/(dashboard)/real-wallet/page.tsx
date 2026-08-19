"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/lib/api-client";

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
  funding_status: "unfunded" | "funded" | "unknown";
  mode: "disabled" | "dry_run" | "armed" | "live";
  execution_enabled: boolean;
  autotrade_enabled: boolean;
  signer_status: string;
  live_submission_transport: string;
  safety_gate: string;
  limits: {
    max_trade_usd: string;
    max_open_positions: number;
    max_total_exposure_usd: string;
    max_daily_notional_usd: string;
    max_daily_loss_usd: string;
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
    kill_switches: Array<{ kind: string; reason: string | null }>;
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

export default function RealWalletPage() {
  const queryClient = useQueryClient();
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
    return (
      <main>
        <p className="text-label text-accent">Restricted</p>
        <h1 className="mt-2 text-2xl font-medium text-ink">
          Execution wallet status is available only to an account-level administrator.
        </h1>
      </main>
    );
  }
  const data = query.data;
  const readiness = data?.readiness;
  const address = data?.public_key;
  const copyAddress = () => address && void navigator.clipboard.writeText(address);
  const explorerUrl = address
    ? `https://solscan.io/account/${address}${data?.network === "devnet" ? "?cluster=devnet" : ""}`
    : undefined;
  return (
    <main>
      <p className="text-label text-accent">Operator only · DEVNET ONLY</p>
      <h1 className="mt-2 text-3xl font-medium text-ink">MEMESCOPE execution wallet</h1>
      <p className="mt-2 max-w-2xl text-sm text-ink-3">
        Dedicated low-balance wallet. Phase 2 supports one explicit, manual native-SOL
        devnet transfer flow for custody verification; it is not a trading surface.
      </p>
      <section className="mt-6 rounded-lg border border-warning/40 bg-warning/[0.08] p-4">
        <p className="text-label text-warning">
          DEVNET ONLY · MAINNET BLOCKED · AUTOTRADE DISABLED
        </p>
        <p className="mt-1 text-sm text-ink-3">
          Every transfer requires a fresh quote, successful simulation, explicit manual
          approval, and an isolated signer. Paper Wallet and Generation 2 cannot reach this
          workflow.
        </p>
      </section>
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
                      className="rounded bg-warning px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
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
      <section className="mt-6 rounded-lg border border-line p-4">
        <p className="text-label text-ink-3">Public address</p>
        {address ? (
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <code className="break-all text-sm text-ink">{address}</code>
            <button className="text-sm text-accent" onClick={copyAddress} type="button">
              Copy address
            </button>
            <a
              className="text-sm text-accent"
              href={explorerUrl}
              rel="noreferrer"
              target="_blank"
            >
              View on Solscan
            </a>
          </div>
        ) : (
          <p className="mt-2 text-sm text-ink-3">
            Not configured. Generate it locally first.
          </p>
        )}
        <p className="mt-3 text-xs text-ink-3">
          Receive URI: {address ? `solana:${address}` : "—"}. A QR image is intentionally
          not rendered through a third-party service, so the address is never disclosed to
          one.
        </p>
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
                <td className={row.status === "WOULD_BUY" ? "text-up" : "text-warning"}>
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
        <p className="text-label text-ink-3">Hard limits</p>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
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
            <dt className="text-ink-3">Daily loss</dt>
            <dd className="text-ink">${data?.limits.max_daily_loss_usd ?? "—"}</dd>
          </div>
        </dl>
      </section>
    </main>
  );
}
