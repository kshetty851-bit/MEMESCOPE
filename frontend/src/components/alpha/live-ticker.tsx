"use client";

/**
 * The homepage's live strip (Karthik, 2026-10-22: "make the page feel alive"):
 * the latest graduations and what the checkers did with each, scrolling under
 * the header. Who stopped a coin, never why: the reasons carry the rules'
 * numbers, which stay off the signed-out page.
 */

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api-client";
import { cleanName } from "@/lib/clean-name";
import { ROBOTS, coinKey, liveIndex, type LiveBelt, type LiveCoin } from "@/lib/hq/checkpoint";

export type CoinReaction = "cheer" | "shake";

function ago(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)}m ago` : `${Math.round(s / 3600)}h ago`;
}

function what(c: LiveCoin): { text: string; tone: string } {
  if (c.status === "bought") return { text: "passed all 30 checks", tone: "text-up" };
  if (c.status === "checking") return { text: "being checked", tone: "text-accent" };
  const who = ROBOTS[liveIndex(c)];
  return { text: who ? `stopped by ${who.first}` : "stopped", tone: "text-down" };
}

export function LiveTicker({ onReact }: { onReact?: (r: CoinReaction) => void }) {
  const [coins, setCoins] = useState<LiveCoin[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const seen = useRef<Set<string> | null>(null);

  useEffect(() => {
    let live = true;
    const read = () =>
      api.get<LiveBelt>("/real-wallet/checkpoint/live", { skipAuthRetry: true })
        .then((b) => {
          if (!live) return;
          const list = (b.coins ?? []).filter((c) => c.status !== "checking").slice(0, 10);
          // The frog reacts to the newest coin it has not seen yet; the first
          // read only learns what is already there.
          if (seen.current) {
            const fresh = list.find((c) => !seen.current!.has(coinKey(c)));
            if (fresh) onReact?.(fresh.status === "bought" ? "cheer" : "shake");
          }
          seen.current = new Set(list.map(coinKey));
          setCoins(list);
          setNow(Date.now());
        })
        .catch(() => {});
    read();
    const timer = window.setInterval(read, 15_000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [onReact]);

  if (coins.length === 0) return null;
  const items = (copy: string) => coins.map((c) => {
    const w = what(c);
    return (
      <span key={`${copy}${coinKey(c)}`} className="live-ticker__item" aria-hidden={copy === "b" || undefined}>
        <b className="text-ink">{cleanName(c.symbol) ?? "unnamed"}</b>
        <span className="text-ink-3">graduated ·</span>
        <span className={w.tone}>{w.text}</span>
        <span className="text-ink-3">· {ago(c.graduated_at, now)}</span>
      </span>
    );
  });
  return (
    <div className="live-ticker" aria-label="Latest graduations">
      <span className="live-ticker__tag"><span aria-hidden className="live-ticker__dot" />Live</span>
      <div className="live-ticker__window">
        {/* Two copies, so the strip loops without a seam. */}
        <div className="live-ticker__track">{items("a")}{items("b")}</div>
      </div>
    </div>
  );
}
