"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";

type WalletStatus = {
  public_key: string | null;
  sol_balance: number | null;
  balance_error: string | null;
  funding_status: "unfunded" | "funded" | "unknown";
  mode: "disabled" | "dry_run";
  execution_enabled: boolean;
  autotrade_enabled: boolean;
  safety_gate: string;
  limits: {
    max_trade_usd: string;
    max_open_positions: number;
    max_total_exposure_usd: string;
    max_daily_notional_usd: string;
    max_daily_loss_usd: string;
    min_sol_fee_reserve: string;
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
          <p className="mt-2 text-sm text-ink-faint">Not configured. Generate it locally first.</p>
        )}
      </section>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatusCard label="SOL balance" value={data?.sol_balance?.toFixed(6) ?? "—"} />
        <StatusCard label="Funding" value={(data?.funding_status ?? "unknown").toUpperCase()} />
        <StatusCard label="Trading mode" value={(data?.mode ?? "disabled").toUpperCase()} />
        <StatusCard label="Safety gate" value={data?.safety_gate ?? "—"} />
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <StatusCard label="Execution" value={data?.execution_enabled ? "ENABLED" : "DISABLED"} />
        <StatusCard label="Autotrade" value={data?.autotrade_enabled ? "ENABLED" : "DISABLED"} />
        <StatusCard label="SOL fee reserve" value={`${data?.limits.min_sol_fee_reserve ?? "—"} SOL`} />
      </div>
      <section className="mt-6 rounded-panel border border-line p-4">
        <p className="text-label text-ink-faint">Hard limits</p>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
          <div><dt className="text-ink-faint">Max trade</dt><dd className="text-ink">${data?.limits.max_trade_usd ?? "—"}</dd></div>
          <div><dt className="text-ink-faint">Max positions</dt><dd className="text-ink">{data?.limits.max_open_positions ?? "—"}</dd></div>
          <div><dt className="text-ink-faint">Max exposure</dt><dd className="text-ink">${data?.limits.max_total_exposure_usd ?? "—"}</dd></div>
          <div><dt className="text-ink-faint">Daily notional</dt><dd className="text-ink">${data?.limits.max_daily_notional_usd ?? "—"}</dd></div>
          <div><dt className="text-ink-faint">Daily loss</dt><dd className="text-ink">${data?.limits.max_daily_loss_usd ?? "—"}</dd></div>
        </dl>
      </section>
    </main>
  );
}
