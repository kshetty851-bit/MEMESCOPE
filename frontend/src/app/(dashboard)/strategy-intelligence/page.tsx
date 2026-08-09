"use client";

import { useMemo } from "react";

import { TokenIdentity } from "@/components/brand/token-identity";
import { Label, Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useStrategyIntelligence } from "@/hooks/use-paper";
import { pct, tone, usd } from "@/lib/paper";
import { cn } from "@/lib/utils";
import type { ShadowWallet } from "@/types/paper";

/**
 * Live Strategy Intelligence
 *
 * This is not a strategy selector. V1 remains production. V2-V5 are shadow
 * wallets that receive the same Radar opportunities and record their own future
 * live evidence. The page renders backend facts only; thresholds and promotion
 * rules do not live in the client.
 */

function Stat({
  label,
  value,
  hint,
  valueTone,
}: {
  label: string;
  value: string | null;
  hint?: string;
  valueTone?: "positive" | "negative" | "neutral";
}) {
  return (
    <div className="rounded-card border border-line bg-surface/40 px-4 py-3">
      <p className="text-label uppercase tracking-wide text-ink-faint">{label}</p>
      <p
        className={cn(
          "mt-1 text-lg font-semibold tabular-nums",
          value === null && "text-ink-faint",
          valueTone === "positive" && "text-safe",
          valueTone === "negative" && "text-danger",
          !valueTone && value !== null && "text-ink",
        )}
      >
        {value ?? "—"}
      </p>
      {hint ? <p className="mt-1 text-xs text-ink-faint">{hint}</p> : null}
    </div>
  );
}

function reasonLabel(code: string) {
  return code.replaceAll("_", " ");
}

function WalletCard({ wallet }: { wallet: ShadowWallet }) {
  const returnTone = tone(wallet.net_return);
  return (
    <Panel className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-label uppercase tracking-wide text-plasma">{wallet.code}</p>
          <h2 className="mt-1 text-xl font-semibold text-ink">{wallet.name}</h2>
          <p className="mt-1 max-w-2xl text-sm text-ink-dim">{wallet.summary}</p>
        </div>
        <div className="rounded-full border border-line px-3 py-1 text-xs text-ink-faint">
          {wallet.closed_positions}/100 completed
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Equity" value={usd(wallet.current_equity)} />
        <Stat label="Cash" value={usd(wallet.cash)} />
        <Stat label="Net return" value={usd(wallet.net_return)} valueTone={returnTone} />
        <Stat label="Profit factor" value={wallet.profit_factor} />
        <Stat label="Expectancy" value={usd(wallet.expectancy)} valueTone={tone(wallet.expectancy)} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Win rate" value={pct(wallet.win_rate_pct)} hint={`${wallet.open_positions} open · ${wallet.closed_positions} closed`} />
        <Stat label="Max drawdown" value={pct(wallet.max_drawdown_pct)} />
        <Stat label="Capital use" value={pct(wallet.capital_utilization_pct)} />
        <Stat
          label="Acceptance"
          value={pct(wallet.acceptance_rate_pct)}
          hint={`${wallet.accepted_opportunities} accepted · ${wallet.rejected_opportunities} rejected`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold text-ink">Opportunity profile</h3>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
            <dt className="text-ink-faint">Avg Radar</dt>
            <dd className="text-right tabular-nums text-ink">{wallet.average_radar_score ?? "—"}</dd>
            <dt className="text-ink-faint">Avg market cap</dt>
            <dd className="text-right tabular-nums text-ink">{usd(wallet.average_market_cap) ?? "—"}</dd>
            <dt className="text-ink-faint">Avg liquidity</dt>
            <dd className="text-right tabular-nums text-ink">{usd(wallet.average_liquidity_usd) ?? "—"}</dd>
            <dt className="text-ink-faint">Avg impact</dt>
            <dd className="text-right tabular-nums text-ink">{pct(wallet.average_entry_impact_pct) ?? "—"}</dd>
            <dt className="text-ink-faint">Avg token age</dt>
            <dd className="text-right tabular-nums text-ink">
              {wallet.average_token_age_hours ? `${wallet.average_token_age_hours}h` : "—"}
            </dd>
            <dt className="text-ink-faint">Avg hold</dt>
            <dd className="text-right tabular-nums text-ink">
              {wallet.average_hold_hours ? `${wallet.average_hold_hours}h` : "—"}
            </dd>
          </dl>
          {wallet.best_trade || wallet.worst_trade ? (
            <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
              {wallet.best_trade ? (
                <div className="rounded-card bg-abyss/40 p-2">
                  <p className="text-ink-faint">Best trade</p>
                  <p className="font-semibold text-safe">{pct(wallet.best_trade.return_pct)} ({usd(wallet.best_trade.pnl_usd)})</p>
                </div>
              ) : null}
              {wallet.worst_trade ? (
                <div className="rounded-card bg-abyss/40 p-2">
                  <p className="text-ink-faint">Worst trade</p>
                  <p className="font-semibold text-danger">{pct(wallet.worst_trade.return_pct)} ({usd(wallet.worst_trade.pnl_usd)})</p>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        <div>
          <h3 className="text-sm font-semibold text-ink">Top rejection reasons</h3>
          <ul className="mt-3 flex flex-col gap-2">
            {Object.entries(wallet.top_rejection_reasons).length ? (
              Object.entries(wallet.top_rejection_reasons).map(([code, count]) => (
                <li
                  key={code}
                  className="flex items-center justify-between gap-3 rounded-card bg-abyss/40 px-3 py-2 text-sm"
                >
                  <span className="capitalize text-ink-dim">{reasonLabel(code)}</span>
                  <span className="tabular-nums text-ink">{count}</span>
                </li>
              ))
            ) : (
              <li className="text-sm text-ink-faint">No rejection data yet.</li>
            )}
          </ul>
        </div>
      </div>

      <div className="rounded-card border border-line bg-abyss/35 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-semibold text-ink">Promotion score {wallet.promotion_score}</p>
          <p
            className={cn(
              "text-xs",
              wallet.promotion_eligible ? "text-safe" : "text-ink-faint",
            )}
          >
            {wallet.promotion_eligible ? "Eligible for review" : "Collecting evidence"}
          </p>
        </div>
        {wallet.promotion_blockers.length ? (
          <p className="mt-2 text-xs text-ink-faint">
            Blockers: {wallet.promotion_blockers.map(reasonLabel).join(", ")}
          </p>
        ) : null}
      </div>
    </Panel>
  );
}

export default function StrategyIntelligencePage() {
  const query = useStrategyIntelligence();
  const ranked = useMemo(
    () =>
      [...(query.data?.wallets ?? [])].sort(
        (a, b) => Number(b.promotion_score) - Number(a.promotion_score),
      ),
    [query.data],
  );

  if (query.isError) {
    return (
      <ErrorState
        body="Strategy Intelligence is not responding. The shadow tables are append-only; this view can be retried without changing evidence."
        onRetry={() => void query.refetch()}
      />
    );
  }

  if (query.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-28 rounded-card" />
        <Skeleton className="h-72 rounded-card" />
        <Skeleton className="h-72 rounded-card" />
      </div>
    );
  }

  if (!query.data.enabled) {
    return (
      <div className="flex flex-col gap-6">
        <header>
          <Label>Strategy Intelligence</Label>
          <h1 className="mt-2 text-title font-semibold text-ink">Shadow mode is not running here</h1>
        </header>
        <Panel density="compact">
          <p className="text-sm text-ink-dim">
            Paper Wallet is disabled in this environment, so V2-V5 shadow wallets are
            not collecting decisions. This is a configuration state, not a strategy
            result.
          </p>
        </Panel>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Label>Strategy Intelligence</Label>
          <h1 className="mt-2 text-title font-semibold text-ink">
            Live shadow wallets, measured beside V1
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-ink-dim">
            V1 remains the production wallet. These candidate wallets receive the
            same Radar opportunities, accept or reject them with fixed rules, and
            build a separate future live record before any promotion decision.
          </p>
        </div>
        <p className="text-xs text-ink-faint">
          Updated {new Date(query.data.observed_at).toLocaleString()}
        </p>
      </header>

      <Panel density="compact" className="border-line-bright bg-elevated/40">
        <p className="text-sm text-ink">
          Promotion requires {query.data.promotion_rules.minimum_completed_trades}+ completed
          live trades, positive net return, positive expectancy, and profit factor
          above {query.data.promotion_rules.minimum_profit_factor}.
        </p>
      </Panel>

      <div className="grid gap-4">
        {ranked.map((wallet) => (
          <WalletCard key={wallet.code} wallet={wallet} />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <h2 className="text-lg font-semibold text-ink">Missed opportunities</h2>
          <p className="mt-1 text-sm text-ink-faint">
            Tokens rejected by one shadow wallet but accepted by another. Winner/loss
            labelling appears once accepted trades have closed.
          </p>
          <ul className="mt-4 flex flex-col gap-2">
            {query.data.missed_opportunities.slice(0, 8).map((item) => (
              <li key={`${item.wallet_code}-${item.mint_address}`} className="flex flex-col gap-1 rounded-card bg-abyss/40 p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <span className="font-medium text-ink">{item.wallet_code}</span>{" "}
                    <span className="text-ink-faint">rejected</span>{" "}
                    <TokenIdentity
                      mint={item.mint_address}
                      imageUrl={item.image_url}
                      size="xs"
                      compact
                      className="ml-1 inline-flex align-middle"
                    />
                  </div>
                  {item.outcome === "missed_winner" ? (
                    <span className="rounded bg-danger/20 px-2 py-0.5 text-xs text-danger">Missed Winner {item.pnl_usd ? `(${usd(item.pnl_usd)})` : ""}</span>
                  ) : item.outcome === "good_rejection" ? (
                    <span className="rounded bg-safe/20 px-2 py-0.5 text-xs text-safe">Good Rejection {item.pnl_usd ? `(${usd(item.pnl_usd)})` : ""}</span>
                  ) : null}
                </div>
                <p className="text-xs capitalize text-ink-faint">
                  {item.reason_codes.map(reasonLabel).join(", ")} · accepted by{" "}
                  {item.accepted_elsewhere.join(", ")}
                </p>
              </li>
            ))}
            {!query.data.missed_opportunities.length ? (
              <li className="text-sm text-ink-faint">No cross-wallet misses yet.</li>
            ) : null}
          </ul>
        </Panel>

        <Panel>
          <h2 className="text-lg font-semibold text-ink">Filter performance</h2>
          <p className="mt-1 text-sm text-ink-faint">
            Rejection-rule accounting. Saved/missed P/L requires closed comparison trades,
            so empty values are left blank rather than guessed.
          </p>
          <ul className="mt-4 flex flex-col gap-2">
            {query.data.filter_performance.slice(0, 10).map((item) => (
              <li
                key={item.reason_code}
                className="flex items-center justify-between gap-3 rounded-card bg-abyss/40 px-3 py-2 text-sm"
              >
                <div>
                  <span className="capitalize text-ink-dim">{reasonLabel(item.reason_code)}</span>
                  {item.net_pl_saved ? (
                    <p className="text-xs text-safe">Saved: {usd(item.net_pl_saved)} ({item.losing_trades_prevented} losses prevented)</p>
                  ) : null}
                  {item.net_pl_missed ? (
                    <p className="text-xs text-danger">Missed: {usd(item.net_pl_missed)} ({item.winning_trades_prevented} wins missed)</p>
                  ) : null}
                </div>
                <span className="tabular-nums text-ink">{item.times_triggered}</span>
              </li>
            ))}
            {!query.data.filter_performance.length ? (
              <li className="text-sm text-ink-faint">No filter decisions yet.</li>
            ) : null}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
