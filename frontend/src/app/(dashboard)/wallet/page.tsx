import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Paper wallet — MEMESCOPE",
};

/**
 * Placeholder for the paper wallet.
 *
 * The route exists now so navigation is honest: the V1 information
 * architecture has four destinations and a nav link that 404s is worse than
 * one that says "not yet". The wallet itself lands in Week 4 — balance,
 * open/closed positions, and the benchmark against buying every signal.
 */
export default function WalletPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-2xl font-semibold text-ink">Paper wallet</h1>
      <p className="mt-4 max-w-prose text-ink-dim">
        Not built yet. When it lands you will start with $1,000 of virtual
        balance, every signal will open a position under one published
        mechanical rule, and the result will be shown against buying every
        signal and against simply holding SOL.
      </p>
      <p className="mt-4 max-w-prose text-ink-faint">
        No real funds are ever involved.
      </p>
    </div>
  );
}
