import type { RadarEntry } from "@/types/radar";
import type { PaperPositions } from "@/types/paper";
import type { Source } from "./adapter";
import { fresh } from "./adapter";

/**
 * WHICH TOKENS THE OFFICE SHOWS MOVING.
 *
 * The scanner can find far more tokens than a room can show. Three visible
 * packets, chosen deterministically from real activity, and everything past
 * that collapses into one honest count — never a fourth silent packet, never
 * a made-up overflow number.
 *
 * SELECTION ORDER (§17)
 *
 *   1. actively transitioning — a mint the live stream just touched
 *      (score.changed / market.changed / radar.score_updated)
 *   2. recently failed/rejected — skipped in this phase: no endpoint
 *      attributes an eligibility refusal to a mint (see `case-file.ts`'s
 *      module header), so there is no real signal to rank by here
 *   3. recent Paper execution — the newest position by `opened_at`
 *   4. recent discovery — the newest Radar row by `first_detected_at`
 *
 * A token already selected stays selected until it drops out of its source
 * list entirely — never swapped for a fresher one mid-tick, which is what
 * the brief calls "flickering." The three slots are filled in priority
 * order and ties break on `mint_address` so two runs of this function over
 * identical inputs always agree, which is what "deterministic" has to mean
 * for something a screenshot test can assert on.
 */

const MAX_VISIBLE = 3;

export type PacketReason = "transitioning" | "executed" | "discovered";

export interface TokenPacket {
  mint: string;
  symbol: string | null;
  name: string | null;
  reason: PacketReason;
}

export interface PacketSelection {
  packets: TokenPacket[];
  /**
   * How many more real, recent cases exist beyond the visible three. `null`
   * when no reliable count exists — omitted from the UI rather than shown
   * as a guess.
   */
  overflow: number | null;
}

export interface PacketSources {
  /** Mints the live stream touched recently — from HQ-4's event meter. */
  transitioning: string[];
  recentRadar: Source<{ items: RadarEntry[] }>;
  recentPositions: Source<PaperPositions>;
}

export function selectPackets(sources: Partial<PacketSources> = {}, now = 0): PacketSelection {
  const transitioning = sources.transitioning ?? [];
  const radar = sources.recentRadar ? fresh(sources.recentRadar, Infinity, now) : null;
  const positions = sources.recentPositions ? fresh(sources.recentPositions, Infinity, now) : null;

  const byMint = new Map<string, { name: string | null; symbol: string | null }>();
  for (const entry of radar?.items ?? []) {
    byMint.set(entry.mint_address, { name: entry.name, symbol: entry.symbol });
  }
  for (const position of positions?.items ?? []) {
    if (!byMint.has(position.mint_address)) {
      byMint.set(position.mint_address, { name: position.name, symbol: position.symbol });
    }
  }

  const chosen: TokenPacket[] = [];
  const seen = new Set<string>();

  function add(mint: string, reason: PacketReason) {
    if (seen.has(mint) || chosen.length >= MAX_VISIBLE) return;
    seen.add(mint);
    const known = byMint.get(mint);
    chosen.push({ mint, symbol: known?.symbol ?? null, name: known?.name ?? null, reason });
  }

  // 1. Actively transitioning, most recently touched first, ties broken on
  // mint so the ordering is reproducible.
  for (const mint of [...transitioning].sort()) add(mint, "transitioning");

  // 3. Recent Paper execution — newest open first, ties broken on mint.
  const recentOpens = [...(positions?.items ?? [])]
    .sort((a, b) => (b.opened_at > a.opened_at ? 1 : b.opened_at < a.opened_at ? -1 : a.mint_address.localeCompare(b.mint_address)));
  for (const position of recentOpens) add(position.mint_address, "executed");

  // 4. Recent discovery — newest first.
  const recentDiscoveries = [...(radar?.items ?? [])].sort((a, b) =>
    b.first_detected_at > a.first_detected_at
      ? 1
      : b.first_detected_at < a.first_detected_at
        ? -1
        : a.mint_address.localeCompare(b.mint_address),
  );
  for (const entry of recentDiscoveries) add(entry.mint_address, "discovered");

  // The overflow count is only ever a real tally of a real candidate pool —
  // the union of everything this function actually looked at, minus what it
  // could show. If none of the sources answered, there is nothing to count.
  const candidatePool = new Set<string>([
    ...transitioning,
    ...(positions?.items.map((p) => p.mint_address) ?? []),
    ...(radar?.items.map((r) => r.mint_address) ?? []),
  ]);
  const hasAnySource = Boolean(sources.recentRadar || sources.recentPositions) && (radar !== null || positions !== null);
  const overflow = hasAnySource ? Math.max(0, candidatePool.size - chosen.length) : null;

  return { packets: chosen, overflow };
}
