"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";

type WalletStatus = {
  public_key: string | null;
  sol_balance: number | null;
  balance_error: string | null;
  funding_status: "unfunded" | "funded" | "unknown";
  mode: "disabled" | "dry_run" | "armed" | "live";
  execution_enabled: boolean;
  autotrade_enabled: boolean;
  signer_ready: boolean;
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

function StatusCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-panel border border-line p-4">
      <p className="text-label text-ink-faint">{label}</p>
      <p className="mt-2 text-lg font-medium text-ink">{value}</p>
    </div>
  );
}

export default function RealWalletPage() {
  const query = useQuery({
    queryKey: ["real-wallet-status"],
    queryFn: () => api.get<WalletStatus>("/real-wallet/status"),
    retry: false,
    refetchInterval: 30_000,
  });
  if (query.isError) {
    return (
      <main>
        <p className="text-label text-plasma">Restricted</p>
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
  return (
    <main>
      <p className="text-label text-plasma">Operator only</p>
      <h1 className="mt-2 text-3xl font-medium text-ink">MEMESCOPE execution wallet</h1>
      <p className="mt-2 max-w-2xl text-sm text-ink-faint">
        Dedicated low-balance wallet. This page is read-only: no signing, funding, swaps, or
        autotrade controls exist here.
      </p>
      <section className="mt-6 rounded-panel border border-line p-4">
        <p className="text-label text-ink-faint">Public address</p>
        {address ? (
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <code className="break-all text-sm text-ink">{address}</code>
            <button className="text-sm text-plasma" onClick={copyAddress} type="button">
              Copy address
            </button>
            <a
              className="text-sm text-plasma"
              href={`https://solscan.io/account/${address}`}
              rel="noreferrer"
              target="_blank"
            >
              View on Solscan
            </a>
          </div>
        ) : (
          <p className="mt-2 text-sm text-ink-faint">
            Not configured. Generate it locally first.
          </p>
        )}
      </section>
      <section className="mt-6 overflow-x-auto rounded-panel border border-line">
        <div className="p-4">
          <p className="text-label text-ink-faint">Dry-run decisions</p>
          <p className="mt-1 text-sm text-ink-faint">
            {data?.dry_run.feature_enabled ? "Recording enabled" : "Recording disabled"}. No
            order is signed or submitted.
          </p>
        </div>
        <table className="w-full text-left text-sm">
          <thead className="border-y border-line text-ink-faint">
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
                className="border-b border-line/60 last:border-0"
              >
                <td className="p-3">
                  <span className="text-ink">{row.symbol ?? "—"}</span>
                  <code className="ml-2 text-xs text-ink-faint">
                    {row.mint_address.slice(0, 8)}
                  </code>
                </td>
                <td>{row.radar_rank}</td>
                <td>{row.safety ?? "—"}</td>
                <td>
                  {row.buy_impact_pct ?? "—"} / {row.sell_impact_pct ?? "—"}
                </td>
                <td className={row.status === "WOULD_BUY" ? "text-safe" : "text-warning"}>
                  {row.status}
                </td>
                <td className="p-3 text-xs text-ink-faint">
                  {row.reason_codes.join(", ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
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
        <StatusCard label="Signer" value={data?.signer_ready ? "READY" : "NOT READY"} />
        <StatusCard
          label="SOL fee reserve"
          value={`${data?.limits.min_sol_fee_reserve ?? "—"} SOL`}
        />
      </div>
      {/* Pre-mainnet readiness. Four blocks that each say whether a *capability*
          exists, above one line that says whether anything could actually be
          submitted. Keeping those separate is the point: "architecturally
          ready" and "live enabled" are different claims, and conflating them is
          how a dashboard ends up implying a system is armed when it is not. */}
      <section className="mt-6 rounded-panel border border-line p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-label text-ink-faint">Pre-mainnet readiness</p>
          <span
            className={
              readiness?.transport.submission_permitted
                ? "rounded-chip border border-danger/30 bg-danger/[0.08] px-2 py-0.5 text-label uppercase text-danger"
                : "rounded-chip border border-line bg-elevated px-2 py-0.5 text-label uppercase text-ink-faint"
            }
          >
            {readiness?.transport.submission_permitted
              ? "SUBMISSION PERMITTED"
              : "SUBMISSION BLOCKED"}
          </span>
        </div>
        <p className="mt-1 text-sm text-ink-faint">
          Architecturally ready is not live enabled. There is no enable control on this
          page, and none anywhere in the product.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatusCard
            label="Config contract"
            value={readiness?.config_contract.execution_settings_shared ? "SHARED" : "DRIFT"}
          />
          <StatusCard
            label="Transport envelope"
            value={(readiness?.transport.envelope ?? "—").toUpperCase()}
          />
          <StatusCard
            label="Order evidence"
            value={readiness?.order_validation.evidence_recheck_installed ? "RE-CHECKED" : "OFF"}
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
                className="rounded-chip border border-line px-2 py-0.5 text-xs text-ink-faint"
              >
                {reason}
              </li>
            ))}
          </ul>
        ) : null}
        <p className="mt-3 text-xs text-ink-faint">
          Release approved: {readiness?.transport.release_approved ? "yes" : "no"} · Production
          transport:{" "}
          {readiness?.transport.production_transport_installed ? "installed" : "not installed"} ·
          Allowed hosts: {readiness?.transport.allowed_hosts.join(", ") ?? "—"}
        </p>
        <p className="mt-1 text-xs text-ink-faint">
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
      <section className="mt-6 rounded-panel border border-line p-4">
        <p className="text-label text-ink-faint">Live readiness</p>
        <p className="mt-1 text-sm text-ink-faint">
          Submission transport: {data?.live_submission_transport ?? "not installed"}. New
          entries remain fail-closed.
        </p>
        <p className="mt-2 text-sm text-ink-faint">
          Open real positions: {data?.live_readiness.open_real_positions ?? 0}. Unresolved
          intents: {data?.live_readiness.unresolved_intents.length ?? 0}. Active kill
          switches: {data?.live_readiness.kill_switches.length ?? 0}.
        </p>
      </section>
      <section className="mt-6 overflow-x-auto rounded-panel border border-line">
        <div className="p-4">
          <p className="text-label text-ink-faint">Confirmed lifecycle ledger</p>
          <p className="mt-1 text-sm text-ink-faint">
            Test-only settlement evidence. Consecutive execution failures:{" "}
            {data?.confirmed_lifecycle.consecutive_execution_failures ?? 0}
            {data?.confirmed_lifecycle.last_failure_reason
              ? ` (${data.confirmed_lifecycle.last_failure_reason})`
              : ""}
            .
          </p>
        </div>
        <table className="w-full text-left text-sm">
          <thead className="border-y border-line text-ink-faint">
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
              <tr key={position.id} className="border-b border-line/60 last:border-0">
                <td className="p-3">
                  <code className="text-xs text-ink">
                    {position.mint_address.slice(0, 12)}
                  </code>
                </td>
                <td
                  className={position.status === "CLOSED" ? "text-ink-faint" : "text-safe"}
                >
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
      <section className="mt-6 rounded-panel border border-line p-4">
        <p className="text-label text-ink-faint">Hard limits</p>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <dt className="text-ink-faint">Max trade</dt>
            <dd className="text-ink">${data?.limits.max_trade_usd ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-faint">Max positions</dt>
            <dd className="text-ink">{data?.limits.max_open_positions ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-faint">Max exposure</dt>
            <dd className="text-ink">${data?.limits.max_total_exposure_usd ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-faint">Daily notional</dt>
            <dd className="text-ink">${data?.limits.max_daily_notional_usd ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-faint">Daily loss</dt>
            <dd className="text-ink">${data?.limits.max_daily_loss_usd ?? "—"}</dd>
          </div>
        </dl>
      </section>
    </main>
  );
}
