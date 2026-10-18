"use client";

import { useMemo, useState } from "react";

import { cn } from "@/lib/utils";

import { ago, clock, pct, trend, usd } from "./format";
import { type LastVisit, useRevealOnce, type useWatchlist } from "./hooks";
import { IconArrow, IconChevron, IconRefresh, IconSearch } from "./icons";
import { CoinRow } from "./markets";
import type { Coin, MapPoint, Story } from "./types";
import { TOPIC_LABEL } from "./types";
import { DOT_STEP, DOT_TOP_LAT, LAND_RUNS } from "./world-dots";

type Watch = ReturnType<typeof useWatchlist>;
const REGION_NAME: Record<string, string> = {
  US: "United States",
  GB: "UK",
  EU: "EU",
  DE: "Germany",
  FR: "France",
  CH: "Switzerland",
  CN: "China",
  HK: "Hong Kong",
  JP: "Japan",
  KR: "Korea",
  SG: "Singapore",
  IN: "India",
  AE: "UAE",
  RU: "Russia",
  UA: "Ukraine",
  TR: "Türkiye",
  BR: "Brazil",
  AR: "Argentina",
  SV: "El Salvador",
  MX: "Mexico",
  CA: "Canada",
  AU: "Australia",
  NG: "Nigeria",
  ZA: "South Africa",
  KE: "Kenya",
  TH: "Thailand",
  VN: "Vietnam",
  PH: "Philippines",
  ID: "Indonesia",
  PK: "Pakistan",
  KZ: "Kazakhstan",
  IL: "Israel",
  TW: "Taiwan",
  BT: "Bhutan",
};

export function Newswire({
  stories,
  pending,
  onApply,
  now,
  lastVisit,
  coins,
  watch,
}: {
  stories: Story[];
  pending: number;
  onApply: () => void;
  now: number;
  lastVisit: LastVisit | null;
  coins: Coin[];
  watch: Watch;
}) {
  const ref = useRevealOnce<HTMLElement>();
  const [view, setView] = useState("all");
  const [topic, setTopic] = useState<string | null>(null);
  const [region, setRegion] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(12);
  const topics = useMemo(
    () => Object.keys(TOPIC_LABEL).filter((t) => stories.some((s) => s.topics.includes(t))),
    [stories],
  );
  const regions = useMemo(() => {
    const n: Record<string, number> = {};
    for (const s of stories) for (const r of s.regions) n[r] = (n[r] ?? 0) + 1;
    return Object.entries(n)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([r]) => r);
  }, [stories]);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return stories.filter(
      (s) =>
        (view === "all" ||
          (view === "watchlist"
            ? coins.some((c) => watch.has(c.id) && matchesCoin(s, c))
            : s.topics.includes(view))) &&
        (!topic || s.topics.includes(topic)) &&
        (!region || s.regions.includes(region)) &&
        (!needle ||
          `${s.title} ${s.summary} ${s.publishers.join(" ")}`
            .toLowerCase()
            .includes(needle)),
    );
  }, [stories, topic, region, q, view, coins, watch]);
  const coinHits =
    q.trim().length >= 2
      ? coins
          .filter((c) =>
            `${c.symbol} ${c.name}`.toLowerCase().includes(q.trim().toLowerCase()),
          )
          .slice(0, 4)
      : [];

  return (
    <section
      ref={ref}
      id="wire"
      aria-labelledby="wire-h"
      className="np-sec np-reveal np-wirewrap"
    >
      <div className="np-wire">
        <header className="np-sec__top">
          <h2 id="wire-h" className="np-sec__head">
            Live Newswire
          </h2>
          <label className="np-search">
            <IconSearch className="np-ico" />
            <span className="sr-only">Search headlines and coins</span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search headlines, coins, outlets"
              type="search"
            />
          </label>
        </header>
        <div className="np-filters" role="group" aria-label="News view">
          {[
            ["all", "All crypto"],
            ["solana", "Solana"],
            ["memecoins", "Memecoins"],
            ["watchlist", "My watchlist"],
          ].map(([id, label]) => (
            <Chip
              key={id}
              on={view === id}
              onClick={() => {
                setView(id!);
                setTopic(null);
                setRegion(null);
                setLimit(12);
              }}
            >
              {label}
            </Chip>
          ))}
        </div>
        <details className="np-filter-details">
          <summary>More filters{topic || region ? " · active" : ""}</summary>
          <div className="np-filters" role="group" aria-label="Filter by topic">
            <Chip on={!topic} onClick={() => setTopic(null)}>
              All topics
            </Chip>
            {topics.map((t) => (
              <Chip
                key={t}
                on={topic === t}
                onClick={() => setTopic(topic === t ? null : t)}
              >
                {TOPIC_LABEL[t]}
              </Chip>
            ))}
          </div>
          {regions.length ? (
            <div
              className="np-filters np-filters--region"
              role="group"
              aria-label="Filter by region"
            >
              <Chip on={!region} onClick={() => setRegion(null)}>
                Everywhere
              </Chip>
              {regions.map((r) => (
                <Chip
                  key={r}
                  on={region === r}
                  onClick={() => setRegion(region === r ? null : r)}
                >
                  {REGION_NAME[r] ?? r}
                </Chip>
              ))}
            </div>
          ) : null}
        </details>
        <p className="np-fine" role="status">
          {shown.length} matching stories
          {view === "watchlist" ? " · matched by coin name or ticker in coverage" : ""}
        </p>
        {pending > 0 ? (
          <button type="button" className="np-updates" onClick={onApply}>
            <IconRefresh className="np-ico" /> {pending} new{" "}
            {pending === 1 ? "story" : "stories"} — show
          </button>
        ) : null}
        {coinHits.length ? (
          <ol className="np-movers__list np-coinhits">
            {coinHits.map((c) => (
              <CoinRow key={c.id} c={c} watch={watch} />
            ))}
          </ol>
        ) : null}
        <ol className="np-wire__list" key={`${topic}-${region}`}>
          {shown.slice(0, limit).map((s) => (
            <WireItem
              key={s.id}
              s={s}
              now={now}
              isNew={!!lastVisit && Date.parse(s.first_at) > Date.parse(lastVisit.at)}
            />
          ))}
        </ol>
        {!shown.length ? (
          <p className="np-missing">Nothing matches that filter right now.</p>
        ) : null}
        {shown.length > limit ? (
          <button
            type="button"
            className="np-linkbtn np-more"
            onClick={() => setLimit((l) => l + 12)}
          >
            More from the wire ({shown.length - limit})
          </button>
        ) : null}
      </div>
      <aside className="np-rail">
        <div className="np-rail__box">
          <h3>Security reporting</h3>
          <p className="np-fine">
            Latest in the available wire. Reporting does not establish incident status.
          </p>
          <ul className="np-security-brief">
            {stories
              .filter((s) => s.topics.includes("security"))
              .slice(0, 3)
              .map((s) => (
                <li key={s.id}>
                  <a href={s.url} target="_blank" rel="noopener noreferrer">
                    {s.title}
                  </a>
                </li>
              ))}
          </ul>
          <a href="#security" className="np-linkbtn">
            Reporting &amp; historical log
          </a>
        </div>
        <Watchlist coins={coins} watch={watch} stories={stories} />
      </aside>
    </section>
  );
}

function Chip({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={cn("np-chip", on && "is-on")}
      aria-pressed={on}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function WireItem({ s, now, isNew }: { s: Story; now: number; isNew: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <li className={cn("np-item", isNew && "is-new", s.sources >= 2 && "is-major")}>
      <span className="np-item__time np-mono">{clock(s.last_at)}</span>
      <div className="np-item__main">
        <h3 className="np-item__head">
          <a href={s.url} target="_blank" rel="noopener noreferrer">
            {s.title}
          </a>
        </h3>

        <p className="np-byline">
          <span>{s.publishers.join(" · ")}</span>
          <span className="np-mono">{ago(s.last_at, now)}</span>
          {s.kind === "confirmed" ? (
            <span className="np-kind k-confirmed">{s.sources} outlets</span>
          ) : s.kind === "developing" ? (
            <span className="np-kind k-developing">Developing</span>
          ) : s.kind === "commentary" ? (
            <span className="np-kind k-commentary">Commentary</span>
          ) : null}
          {s.topics.slice(0, 2).map((t) => (
            <span key={t} className="np-topic">
              {TOPIC_LABEL[t]}
            </span>
          ))}
          {isNew ? <span className="np-kind k-new">New</span> : null}
        </p>
        <button
          type="button"
          className="np-linkbtn"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          <IconChevron className={cn("np-ico np-chev", open && "is-open")} />{" "}
          {open ? "Close brief" : "Story brief & sources"}
        </button>
        {open ? (
          <div className="np-storybrief">
            <h4>What was reported</h4>
            <p>
              {s.summary ||
                "No publisher summary is available. Read the original report for details."}
            </p>
            <p className="np-fine">
              Publisher summary · {s.sources} {s.sources === 1 ? "outlet" : "outlets"}.
              Coverage count is not independent verification.
            </p>
            <a
              className="np-linkbtn"
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Read at {s.source} <IconArrow className="np-ico" />
            </a>
            {s.timeline.length > 1 ? (
              <>
                <h4>How coverage developed</h4>
                <ol className="np-timeline__list">
                  {s.timeline
                    .slice()
                    .reverse()
                    .map((t) => (
                      <li key={t.url}>
                        <span className="np-mono">{clock(t.at)}</span>
                        <a href={t.url} target="_blank" rel="noopener noreferrer">
                          {t.title}
                        </a>
                        <em>{t.source}</em>
                      </li>
                    ))}
                </ol>
              </>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  );
}

export function SinceVisit({
  last,
  stories,
  btc,
  now,
}: {
  last: LastVisit | null;
  stories: Story[];
  btc: number | null;
  now: number;
}) {
  if (!last) {
    return (
      <div className="np-return">
        <h3>Since your last visit</h3>
        <p className="np-dim">
          Welcome. Next time you come back, this shows what changed while you were away —
          kept only in this browser.
        </p>
      </div>
    );
  }
  const since = Date.parse(last.at);
  const fresh = stories.filter((s) => Date.parse(s.first_at) > since);
  const security = stories
    .filter((s) => Date.parse(s.last_at) > since)
    .filter((s) => s.topics.includes("security")).length;
  const move = last.btc && btc ? ((btc - last.btc) / last.btc) * 100 : null;
  const top = fresh.slice().sort((a, b) => b.sources - a.sources)[0];
  return (
    <div className="np-return">
      <h3>Since your last visit</h3>
      <p className="np-dim np-mono">{ago(last.at, now)} · within available coverage</p>
      <ul className="np-since">
        <li>
          <span className="np-mono">{fresh.length}</span> new stories
        </li>
        {move != null ? (
          <li>
            Bitcoin <span className={cn("np-mono", `t-${trend(move)}`)}>{pct(move)}</span>{" "}
            <span className="np-dim">
              ({usd(last.btc, 0)} → {usd(btc, 0)})
            </span>
          </li>
        ) : null}
        <li>
          <span className="np-mono">{security}</span> security{" "}
          {security === 1 ? "story" : "stories"} new or updated
        </li>
      </ul>
      {top ? (
        <p className="np-since__top">
          Most covered since:{" "}
          <a href={top.url} target="_blank" rel="noopener noreferrer">
            {top.title}
          </a>
        </p>
      ) : null}
    </div>
  );
}

function matchesCoin(story: Story, coin: Coin) {
  const words = `${story.title} ${story.summary}`.toLowerCase().split(/[^a-z0-9]+/);
  return (
    words.includes(coin.symbol.toLowerCase()) ||
    ` ${words.join(" ")} `.includes(` ${coin.name.toLowerCase()} `)
  );
}

function Watchlist({
  coins,
  watch,
  stories,
}: {
  coins: Coin[];
  watch: Watch;
  stories: Story[];
}) {
  const mine = coins.filter((c) => watch.has(c.id));
  return (
    <div className="np-rail__box">
      <h3>Your watchlist</h3>
      {!mine.length ? (
        <p className="np-dim">
          Star a coin in Market Pulse or in search to follow its price and headlines here.
        </p>
      ) : (
        <ol className="np-movers__list">
          {mine.map((c) => {
            const n = stories.filter((s) => matchesCoin(s, c)).length;
            return (
              <div key={c.id} className="np-watchrow">
                <CoinRow c={c} watch={watch} />
                {n ? (
                  <span className="np-fine">
                    {n} matching headline{n > 1 ? "s" : ""} in coverage
                  </span>
                ) : null}
              </div>
            );
          })}
        </ol>
      )}
    </div>
  );
}

const W = 360 / DOT_STEP,
  H = 140 / DOT_STEP;
const px = (lon: number) => (lon + 180) / DOT_STEP;
const py = (lat: number) => (DOT_TOP_LAT - lat) / DOT_STEP;

export function WorldMap({ points, now }: { points: MapPoint[]; now: number }) {
  const ref = useRevealOnce<HTMLElement>();
  const [sel, setSel] = useState<string | null>(null);
  const dots = useMemo(() => {
    const out: string[] = [];
    for (const line of LAND_RUNS) {
      const row = line[0] ?? 0;
      for (let i = 1; i + 1 < line.length; i += 2) {
        const start = line[i] ?? 0,
          len = line[i + 1] ?? 0;
        for (let c = start; c < start + len; c++) out.push(`M${c + 0.5},${row + 0.5}h0`);
      }
    }
    return out.join("");
  }, []);
  const max = Math.max(1, ...points.map((p) => p.count));
  const active = points.find((p) => p.code === sel) ?? points[0];
  return (
    <section ref={ref} id="world" aria-labelledby="world-h" className="np-sec np-reveal">
      <header className="np-sec__top">
        <h2 id="world-h" className="np-sec__head">
          Around the World
        </h2>
        <span className="np-fine">
          Places named in the last 48 hours of coverage. Marker size: number of stories.
        </span>
      </header>
      <div className="np-world">
        <svg
          className="np-map"
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label="World map of where crypto news is happening"
        >
          <path d={dots} className="np-map__land" />
          {points.map((p) => {
            const r = 0.9 + 2.2 * Math.sqrt(p.count / max);
            const recent = p.stories.some((s) => now - Date.parse(s.at) < 3 * 3_600_000);
            return (
              <g
                key={p.code}
                className={cn("np-pin", sel === p.code && "is-on", recent && "is-recent")}
                transform={`translate(${px(p.lon)} ${py(p.lat)})`}
                tabIndex={0}
                role="button"
                aria-label={`${p.name}: ${p.count} stories`}
                onClick={() => setSel(p.code)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSel(p.code);
                  }
                }}
              >
                {recent ? <circle r={r} className="np-pin__pulse" /> : null}
                <circle r={r} className="np-pin__dot" />
              </g>
            );
          })}
        </svg>
        <div className="np-world__panel" aria-live="polite">
          {active ? (
            <>
              <h3>
                {active.name}{" "}
                <span className="np-mono np-dim">
                  {active.count} {active.count === 1 ? "story" : "stories"}
                </span>
              </h3>
              <ol>
                {active.stories.map((s) => (
                  <li key={s.id}>
                    <a href={s.url} target="_blank" rel="noopener noreferrer">
                      {s.title}
                      <IconArrow className="np-ico" />
                    </a>
                    <span className="np-mono np-dim">
                      {s.source} · {ago(s.at, now)}
                    </span>
                  </li>
                ))}
              </ol>
              <div className="np-world__list">
                {points.slice(0, 8).map((p) => (
                  <button
                    key={p.code}
                    type="button"
                    className={cn("np-chip", active.code === p.code && "is-on")}
                    onClick={() => setSel(p.code)}
                  >
                    {p.name} <span className="np-mono">{p.count}</span>
                  </button>
                ))}
              </div>
            </>
          ) : (
            <p className="np-missing">No places named in today&rsquo;s coverage yet.</p>
          )}
        </div>
      </div>
    </section>
  );
}
