"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { ago, countdown, dayTime, pct, trend, usd } from "./format";
import { useNow, useRevealOnce, type useWatchlist } from "./hooks";
import { IconShield, IconStar } from "./icons";
import type { BtcNet, Coin, Hack, Market, Meme, Narrative, Ours, Story } from "./types";

type Watch = ReturnType<typeof useWatchlist>;

/** A value that briefly lights when it changes (not on first paint). */
export function Live({
  value,
  children,
  className,
}: {
  value: unknown;
  children: React.ReactNode;
  className?: string;
}) {
  const first = useRef(true);
  const [flash, setFlash] = useState(false);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    setFlash(true);
    const t = setTimeout(() => setFlash(false), 1200);
    return () => clearTimeout(t);
  }, [value]);
  return (
    <span className={cn("np-mono np-livev", flash && "is-flash", className)}>
      {children}
    </span>
  );
}

export function Spark({ points, up }: { points: number[]; up: boolean }) {
  if (points.length < 2) return null;
  const min = Math.min(...points),
    max = Math.max(...points),
    w = 96,
    h = 26;
  const d = points
    .map(
      (p, i) =>
        `${(i / (points.length - 1)) * w},${h - ((p - min) / (max - min || 1)) * h}`,
    )
    .join(" ");
  return (
    <svg
      className={cn("np-spark", up ? "t-up" : "t-down")}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      aria-hidden
    >
      <polyline points={d} />
    </svg>
  );
}

function Section({
  id,
  title,
  aside,
  children,
  className,
}: {
  id: string;
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRevealOnce<HTMLElement>();
  return (
    <section
      ref={ref}
      id={id}
      aria-labelledby={`${id}-h`}
      className={cn("np-sec np-reveal", className)}
    >
      <header className="np-sec__top">
        <h2 id={`${id}-h`} className="np-sec__head">
          {title}
        </h2>
        {aside ? <div className="np-sec__aside">{aside}</div> : null}
      </header>
      {children}
    </section>
  );
}

function Missing({ what }: { what: string }) {
  return <p className="np-missing">{what}</p>;
}

export function MarketPulse({
  market,
  fearGreed,
  watch,
}: {
  market: Market | null;
  fearGreed: { value: number; label: string; yesterday: number | null } | null;
  watch: Watch;
}) {
  const [tab, setTab] = useState<"gainers" | "losers" | "volume">("gainers");
  if (!market)
    return (
      <Section id="pulse" title="Market Pulse">
        <Missing what="Market data is not answering right now. It returns on the next refresh." />
      </Section>
    );
  const coins = market.coins;
  const btc = coins.find((c) => c.symbol === "BTC"),
    eth = coins.find((c) => c.symbol === "ETH");
  const big = coins.filter((c) => (c.mcap ?? 0) > 1e9 && c.ch24h != null);
  const movers =
    tab === "volume"
      ? [...coins].sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0)).slice(0, 6)
      : [...big]
          .sort((a, b) => (tab === "gainers" ? 1 : -1) * ((b.ch24h ?? 0) - (a.ch24h ?? 0)))
          .slice(0, 6);
  return (
    <Section
      id="pulse"
      title="Market Pulse"
      aside={<span className="np-fine">CoinGecko · 24 h · liquidations not connected</span>}
    >
      <div className="np-pulse">
        {[btc, eth].map((c) =>
          c ? (
            <div key={c.id} className="np-quote">
              <div className="np-quote__name">{c.name}</div>
              <Live value={c.price} className="np-quote__px">
                {usd(c.price, 0)}
              </Live>
              <div className="np-mono">
                <span className={`t-${trend(c.ch24h)}`}>{pct(c.ch24h)}</span>{" "}
                <span className="np-dim">24h</span>{" "}
                <span className="np-quote__7d">
                  <span className={`t-${trend(c.ch7d)}`}>{pct(c.ch7d)}</span>{" "}
                  <span className="np-dim">7d</span>
                </span>
              </div>
              <Spark points={c.spark} up={(c.ch7d ?? 0) >= 0} />
            </div>
          ) : null,
        )}
        <dl className="np-figs">
          <div>
            <dt>Total market cap</dt>
            <dd>
              <Live value={market.total_mcap}>{usd(market.total_mcap)}</Live>{" "}
              <span className={cn("np-mono", `t-${trend(market.mcap_change_24h)}`)}>
                {pct(market.mcap_change_24h)}
              </span>
            </dd>
          </div>
          <div>
            <dt>24 h volume, top 100</dt>
            <dd>
              <Live value={market.top100_volume}>{usd(market.top100_volume)}</Live>
            </dd>
          </div>
          <div>
            <dt>Bitcoin dominance</dt>
            <dd className="np-mono">{pct(market.btc_dominance).replace("+", "")}</dd>
          </div>
          <div>
            <dt>Ether dominance</dt>
            <dd className="np-mono">{pct(market.eth_dominance).replace("+", "")}</dd>
          </div>
          {fearGreed ? (
            <div>
              <dt>Fear &amp; Greed</dt>
              <dd>
                <span className="np-mono">{fearGreed.value}</span> {fearGreed.label}
                {fearGreed.yesterday != null ? (
                  <span className="np-dim np-mono"> · was {fearGreed.yesterday}</span>
                ) : null}
              </dd>
            </div>
          ) : null}
        </dl>
      </div>
      <div className="np-movers">
        <div className="np-tabs" role="tablist" aria-label="Movers">
          {(["gainers", "losers", "volume"] as const).map((t) => (
            <button
              key={t}
              role="tab"
              type="button"
              aria-selected={tab === t}
              className={cn("np-tab", tab === t && "is-on")}
              onClick={() => setTab(t)}
            >
              {t === "gainers"
                ? "Top gainers"
                : t === "losers"
                  ? "Top losers"
                  : "Most traded"}
            </button>
          ))}
          <span
            className="np-tabs__ink"
            style={{ ["--i" as string]: ["gainers", "losers", "volume"].indexOf(tab) }}
            aria-hidden
          />
        </div>
        <ol className="np-movers__list" key={tab}>
          {movers.map((c) => (
            <CoinRow key={c.id} c={c} watch={watch} />
          ))}
        </ol>
        <p className="np-fine">
          Large caps only (over $1B) for gainers and losers. A move is described here, not
          explained.
        </p>
      </div>
    </Section>
  );
}

export function CoinRow({ c, watch }: { c: Coin; watch: Watch }) {
  const on = watch.has(c.id);
  return (
    <li className="np-coin">
      <button
        type="button"
        className={cn("np-star", on && "is-on")}
        onClick={() => watch.toggle(c.id)}
        aria-pressed={on}
        aria-label={on ? `Remove ${c.name} from watchlist` : `Add ${c.name} to watchlist`}
      >
        <IconStar className="np-ico" filled={on} />
      </button>
      <span className="np-coin__sym">{c.symbol}</span>
      <span className="np-coin__name">{c.name}</span>
      <Live value={c.price}>{usd(c.price, c.price && c.price < 1 ? 4 : 2)}</Live>
      <span className={cn("np-mono np-coin__ch", `t-${trend(c.ch24h)}`)}>
        {pct(c.ch24h)}
      </span>
    </li>
  );
}

export function Heatmap({
  narratives,
  stories,
}: {
  narratives: Narrative[] | null;
  stories: Story[];
}) {
  if (!narratives?.length)
    return (
      <Section id="heat" title="Narrative Heatmap">
        <Missing what="Sector data is not answering right now." />
      </Section>
    );
  const max = Math.max(...narratives.map((n) => Math.abs(n.change_24h)), 0.5);
  const minCap = Math.min(...narratives.map((n) => n.mcap));
  const day = Date.now() - 86_400_000;
  const mentions = (name: string) => {
    const w = name
      .toLowerCase()
      .split(/[\s()/-]+/)
      .filter((x) => x.length > 3);
    return stories.filter(
      (s) =>
        Date.parse(s.last_at) > day && w.some((x) => s.title.toLowerCase().includes(x)),
    ).length;
  };
  return (
    <Section
      id="heat"
      title="Narrative Heatmap"
      aside={
        <span className="np-fine">
          Colour: sector market-cap change, 24 h (CoinGecko). Number: headlines naming it
          today.
        </span>
      }
    >
      <ul className="np-heat">
        {narratives.slice(0, 20).map((n) => {
          const k = Math.sign(n.change_24h) * Math.sqrt(Math.abs(n.change_24h) / max);
          return (
            <li
              key={n.id}
              className={cn(
                "np-heat__cell",
                k >= 0 ? "is-up" : "is-down",
                Math.abs(k) > 0.55 && k > 0 && "is-strong",
              )}
              style={{
                ["--k" as string]: Math.abs(k).toFixed(3),
                ["--w" as string]: Math.min(8, Math.sqrt(n.mcap / minCap)).toFixed(2),
              }}
            >
              <span className="np-heat__name">{n.name}</span>
              <span className="np-mono">{pct(n.change_24h)}</span>
              <span
                className="np-heat__ment np-mono"
                title="Headlines today naming this sector"
              >
                {mentions(n.name) || ""}
              </span>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function riskOf(m: Meme): { level: "high" | "elevated" | "watch"; why: string[] } {
  const why: string[] = [];
  const ageH = m.created ? (Date.now() - m.created) / 3_600_000 : null;
  if (ageH != null && ageH < 24)
    why.push(`pool ${ageH < 1 ? "under an hour" : `${Math.round(ageH)} h`} old`);
  if ((m.liquidity ?? 0) < 50_000) why.push(`thin liquidity (${usd(m.liquidity)})`);
  if (m.fdv && m.liquidity && m.fdv / m.liquidity > 40)
    why.push("valuation far above its pool");
  if (m.boost) why.push("paid promotion (DexScreener boost)");
  return { level: why.length >= 3 ? "high" : why.length === 2 ? "elevated" : "watch", why };
}

export function MemeRadar({ memes, ours }: { memes: Meme[] | null; ours: Ours | null }) {
  return (
    <Section
      id="memes"
      title="Meme Radar"
      aside={
        <span className="np-fine">
          Paid promotion · DexScreener most-boosted, not organic popularity
        </span>
      }
    >
      {ours ? (
        <p className="np-ours">
          <span className="np-badge">Our lab</span>
          <span className="np-mono">{ours.graduations_24h}</span> pump.fun coins graduated
          in 24 h (<span className="np-mono">{ours.graduations_1h}</span> in the last hour).
          {ours.rug_rate_24h != null ? (
            <>
              {" "}
              <span className="np-mono">{ours.rug_rate_24h}%</span> of the{" "}
              {ours.rug_measured_24h} we measured lost 80%+ within their first hour.
            </>
          ) : null}
        </p>
      ) : null}
      {!memes?.length ? (
        <Missing what="DexScreener is not answering right now." />
      ) : (
        <ol className="np-memes">
          {memes.slice(0, 8).map((m) => {
            const r = riskOf(m);
            return (
              <li key={`${m.chain}:${m.address}`} className="np-meme">
                <a
                  href={m.url ?? "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="np-meme__name"
                >
                  {m.symbol ?? "?"}
                  <span>{m.name}</span>
                </a>
                <span className="np-mono np-dim">{m.chain}</span>
                <span className="np-mono">
                  {usd(m.volume24h)} <span className="np-dim">vol</span>
                </span>
                <span className="np-mono">
                  {usd(m.liquidity)} <span className="np-dim">liq</span>
                </span>
                <span className={cn("np-mono", `t-${trend(m.change24h)}`)}>
                  {pct(m.change24h)}
                </span>
                <span
                  className={cn("np-risk", `r-${r.level}`)}
                  title={r.why.join("; ") || "no flags"}
                >
                  {r.level === "watch"
                    ? "Limited flags"
                    : r.level === "elevated"
                      ? "Elevated risk"
                      : "High risk"}
                </span>
                {r.why.length ? (
                  <span className="np-meme__why">{r.why.join(" · ")}</span>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </Section>
  );
}

export function OnchainWatch({
  ours,
  unavailable,
  now,
}: {
  ours: Ours | null;
  unavailable: { section: string; why: string }[];
  now: number;
}) {
  const off = unavailable.filter((u) => /whale|flows|liquidation/i.test(u.section));
  return (
    <Section
      id="chain"
      title="On-chain Watch"
      aside={<span className="np-fine">What MEMESCOPE measured itself</span>}
    >
      {ours?.recent_drains.length ? (
        <ol className="np-drains">
          {ours.recent_drains.slice(0, 6).map((d) => (
            <li key={d.mint}>
              <span className="np-mono" title={`${ago(d.graduated_at, now)}`}>
                {new Date(d.graduated_at).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
              <span>
                <strong>{d.symbol || `${d.mint.slice(0, 4)}…${d.mint.slice(-4)}`}</strong>
                {d.name && d.name !== d.symbol ? (
                  <span className="np-dim"> {d.name}</span>
                ) : null}
              </span>
              <a
                href={`https://solscan.io/token/${d.mint}`}
                target="_blank"
                rel="noopener noreferrer"
                className="np-mono"
              >
                token
              </a>
            </li>
          ))}
        </ol>
      ) : (
        <Missing what="No first-hour drains recorded in the last 12 hours." />
      )}
      <p className="np-fine">
        Times are when each coin graduated on pump.fun; each then fell below a fifth of its
        opening price within its first hour. A drain is a measured price collapse, not proof
        of fraud.
      </p>
      {off.length ? (
        <details className="np-secondary">
          <summary>Data coverage &amp; unavailable feeds</summary>
          {off.map((u) => (
            <p key={u.section} className="np-fine">
              <strong>{u.section}:</strong> {u.why}
            </p>
          ))}
        </details>
      ) : null}
    </Section>
  );
}

export function SecurityDesk({
  hacks,
  stories,
  now,
}: {
  hacks: Hack[] | null;
  stories: Story[];
  now: number;
}) {
  const wire = stories
    .filter(
      (s) => s.topics.includes("security") && now - Date.parse(s.last_at) < 3 * 86_400_000,
    )
    .slice(0, 4);
  return (
    <Section
      id="security"
      title="Security Alerts"
      className="np-sec--alert"
      aside={<span className="np-fine">DeFiLlama hack log + security reporting</span>}
    >
      <div className="np-security">
        <div>
          <h3>Historical incident log</h3>
          <ol className="np-hacks">
            {(hacks ?? []).slice(0, 6).map((h) => (
              <li key={`${h.name}${h.date}`}>
                <IconShield className="np-ico" />
                <div>
                  <strong>{h.name}</strong>
                  <span className="np-mono">
                    {h.amount_usd ? usd(h.amount_usd) : "amount not reported"}
                  </span>
                  <span className="np-dim">
                    {[h.technique, h.chains.join(", ")].filter(Boolean).join(" · ")}
                  </span>
                </div>
                <span className="np-mono np-dim">{dayTime(h.date).split(",")[0]}</span>
              </li>
            ))}
            {!hacks?.length ? (
              <Missing what="The hack log is not answering right now." />
            ) : null}
          </ol>
        </div>
        <div className="np-secwire">
          <h3>Recent reporting</h3>
          {wire.length ? (
            wire.map((s) => (
              <a
                key={s.id}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="np-secwire__item"
              >
                <span>{s.title}</span>
                <span className="np-byline">
                  <span>{s.publishers.join(" · ")}</span>
                  <span className="np-mono">{ago(s.last_at, now)}</span>
                  {s.kind !== "report" ? (
                    <span className={cn("np-kind", `k-${s.kind}`)}>
                      {s.kind === "confirmed"
                        ? `Reported by ${s.sources} outlets`
                        : s.kind === "developing"
                          ? "Developing"
                          : "Commentary"}
                    </span>
                  ) : null}
                </span>
              </a>
            ))
          ) : (
            <Missing what="No security reporting in the last three days." />
          )}
        </div>
      </div>
    </Section>
  );
}

function Countdown({ at }: { at: string }) {
  const now = useNow(1000);
  return <span className="np-mono np-count">{countdown(at, now)}</span>;
}

export function Events({
  btc,
  ours,
  unavailable,
}: {
  btc: BtcNet | null;
  ours: Ours | null;
  unavailable: { section: string; why: string }[];
}) {
  const items: { at: string; title: string; note: string; tag: string }[] = [];
  if (btc) {
    items.push({
      at: btc.difficulty_at,
      tag: "Bitcoin",
      title: "Difficulty adjustment",
      note: `${btc.difficulty_change_pct > 0 ? "+" : ""}${btc.difficulty_change_pct.toFixed(1)}% estimated · ${btc.difficulty_blocks_left} blocks to go (mempool.space)`,
    });
    items.push({
      at: btc.halving_estimate,
      tag: "Bitcoin",
      title: "Next halving",
      note: `Block ${btc.halving_height.toLocaleString()} · ${btc.halving_blocks_left.toLocaleString()} blocks away; date estimated at 10 minutes a block`,
    });
  }
  if (ours?.karthik_lab?.judge_at)
    items.push({
      at: ours.karthik_lab.judge_at,
      tag: "MEMESCOPE",
      title: "Lab verdict",
      note: "Our paper pump.fun strategy is judged against the bar set before it started",
    });
  items.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const off = unavailable.find((u) => /unlock|upgrade|governance/i.test(u.section));
  return (
    <Section
      id="events"
      title="Upcoming Events"
      aside={<span className="np-fine">Your local time</span>}
    >
      <ol className="np-events">
        {items.map((e) => (
          <li key={e.title}>
            <span className="np-events__tag">{e.tag}</span>
            <div>
              <strong>{e.title}</strong>
              <span className="np-dim">{e.note}</span>
            </div>
            <div className="np-events__when">
              <span className="np-mono np-dim">{dayTime(e.at)}</span>
              <Countdown at={e.at} />
            </div>
          </li>
        ))}
      </ol>
      {off ? (
        <p className="np-missing">
          <strong>{off.section}:</strong> {off.why}
        </p>
      ) : null}
    </Section>
  );
}
