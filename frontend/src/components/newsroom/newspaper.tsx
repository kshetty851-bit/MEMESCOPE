"use client";

/* Live crypto broadsheet: compact lead, sourced briefs and measured lab findings. */

import { useEffect, useMemo, useState } from "react";

import { cn } from "@/lib/utils";

import { body, figures, headline, nameplate } from "./fonts";
import { ago, clock, pct, trend, usd } from "./format";
import { useLastVisit, useNewsroom, useNow, useWatchlist } from "./hooks";
import { IconArrow, IconPause, IconPlay } from "./icons";
import {
  Events,
  Heatmap,
  MarketPulse,
  MemeRadar,
  OnchainWatch,
  SecurityDesk,
} from "./markets";
import type { Coin, Newsroom, Story } from "./types";
import { Newswire, SinceVisit, WorldMap } from "./wire";

const SOURCE_LABEL: Record<string, string> = {
  market: "CoinGecko prices",
  narratives: "CoinGecko sectors",
  fear_greed: "Fear & Greed index",
  hacks: "DeFiLlama hacks",
  bitcoin_network: "mempool.space",
  memes: "DexScreener boosts",
  memescope: "MEMESCOPE lab data",
};

/** Launch of MEMESCOPE's public edition: the issue number counts days from here. */
const FIRST_EDITION = Date.UTC(2026, 9, 17);

export function Newspaper() {
  const nr = useNewsroom();
  const now = useNow(30_000);
  const data: Newsroom | undefined = nr.data;
  const coins = data?.market?.coins ?? [];
  const btc = coins.find((c) => c.symbol === "BTC")?.price ?? null;
  const lastVisit = useLastVisit(btc);
  const watch = useWatchlist();
  const ready = !!data && !data.warming_up;
  const [js, setJs] = useState(false);
  useEffect(() => setJs(true), []);

  return (
    <div
      className={cn(
        "np",
        js && "np-js",
        nameplate.variable,
        headline.variable,
        body.variable,
        figures.variable,
      )}
    >
      <div className="np-grain" aria-hidden />
      <Masthead data={data} now={now} failed={nr.isError} />
      <Ticker coins={coins} />
      {!ready ? (
        <Press state={nr.isError ? "error" : data?.warming_up ? "warming" : "loading"} />
      ) : (
        <main className="np-page">
          <SinceVisit last={lastVisit} stories={nr.stories} btc={btc} now={now} />
          <section className="np-front np-enter" style={{ ["--d" as string]: "160ms" }}>
            <div>
              <Lead story={data.lead ?? null} now={now} />
              <LatestHeadlines
                stories={nr.stories.filter((s) => s.id !== data.lead?.id).slice(0, 3)}
              />
            </div>
            <Briefing data={data} now={now} />
          </section>
          <Newswire
            stories={nr.stories}
            pending={nr.pending}
            onApply={nr.apply}
            now={now}
            lastVisit={lastVisit}
            coins={coins}
            watch={watch}
          />
          <LabFindings ours={data.ours ?? null} />
          <div className="np-split">
            <MemeRadar memes={data.memes ?? null} ours={data.ours ?? null} />
            <OnchainWatch
              ours={data.ours ?? null}
              unavailable={data.unavailable ?? []}
              now={now}
            />
          </div>
          <MarketPulse
            market={data.market ?? null}
            fearGreed={data.fear_greed ?? null}
            watch={watch}
          />
          <Heatmap narratives={data.narratives ?? null} stories={nr.stories} />
          <SecurityDesk hacks={data.hacks ?? null} stories={nr.stories} now={now} />
          <details className="np-secondary">
            <summary>Explore geography and upcoming events</summary>
            <WorldMap points={data.map ?? []} now={now} />
            <Events
              btc={data.bitcoin_network ?? null}
              ours={data.ours ?? null}
              unavailable={data.unavailable ?? []}
            />
          </details>
        </main>
      )}
      <Colophon data={data} now={now} />
    </div>
  );
}

function Masthead({
  data,
  now,
  failed,
}: {
  data?: Newsroom;
  now: number;
  failed: boolean;
}) {
  const [today, setToday] = useState(["", ""]);
  useEffect(() => {
    const d = new Date();
    setToday([
      d.toLocaleDateString([], {
        weekday: "long",
        day: "numeric",
        month: "long",
        year: "numeric",
      }),
      d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }),
    ]);
  }, []);
  const issue = Math.max(1, Math.floor((now - FIRST_EDITION) / 86_400_000) + 1);
  const updated = data?.generated_at;
  const stale = updated ? now - Date.parse(updated) > 10 * 60_000 : false;
  return (
    <header className="np-mast">
      <div className="np-mast__rail">
        <span className="np-mono np-date--long">{today[0] || " "}</span>
        <span className="np-mono np-date--short">{today[1] || " "}</span>
        <span className="np-mono np-mast__issue">No. {issue}</span>
        <span className={cn("np-live", (failed || stale) && "is-stale")}>
          <i aria-hidden key={updated ?? "none"} />
          <span className="np-mono">
            {failed
              ? "Connection lost — showing last edition"
              : updated
                ? `${stale ? "Stale since" : "Live ·"} ${clock(updated)}`
                : "Connecting"}
          </span>
        </span>
      </div>
      <h1 className="np-flag">
        <span className="np-flag__ink">Memescope</span>
      </h1>
      <p className="np-motto">
        All the crypto that moved today — sourced, timed, and checked against our own
        on-chain lab.
      </p>
    </header>
  );
}

function Ticker({ coins }: { coins: Coin[] }) {
  const [paused, setPaused] = useState(false);
  // Stablecoins and wrapped or staked copies don't move: they'd only pad the strip.
  const row = coins
    .filter(
      (c) =>
        !/usd|eur|dai$|^wbtc|^weth|steth|^cb|heloc|buidl/i.test(c.symbol) &&
        !/wrapped|staked|bridged|stable|tokenized/i.test(c.name),
    )
    .slice(0, 24);
  if (!row.length) return <div className="np-ticker is-empty" />;
  const strip = (aria: boolean) => (
    <ul className="np-ticker__row" aria-hidden={!aria || undefined}>
      {row.map((c) => (
        <li key={c.id}>
          <span className="np-ticker__sym">{c.symbol}</span>
          <span className="np-mono">{usd(c.price, c.price && c.price < 1 ? 4 : 2)}</span>
          <span className={cn("np-mono", `t-${trend(c.ch24h)}`)}>{pct(c.ch24h)}</span>
        </li>
      ))}
    </ul>
  );
  return (
    <div
      className={cn("np-ticker", paused && "is-paused")}
      role="region"
      aria-label="Prices, 24-hour change"
    >
      <button
        type="button"
        className="np-ticker__ctl"
        onClick={() => setPaused((p) => !p)}
        aria-label={paused ? "Play the ticker" : "Pause the ticker"}
      >
        {paused ? <IconPlay className="np-ico" /> : <IconPause className="np-ico" />}
      </button>
      <div className="np-ticker__clip">
        <div className="np-ticker__track">
          {strip(true)}
          {strip(false)}
        </div>
      </div>
    </div>
  );
}

function Press({ state }: { state: "loading" | "warming" | "error" }) {
  return (
    <main className="np-page np-press" aria-busy={state !== "error"}>
      <p className="np-press__line">
        {state === "error"
          ? "The wires are down. We'll keep trying every minute."
          : state === "warming"
            ? "First edition is at the press — the newsroom collects every source within two minutes."
            : "Setting the type…"}
      </p>
      <div className="np-press__ghost" aria-hidden>
        <span />
        <span />
        <span />
      </div>
    </main>
  );
}

function KindTag({ kind, sources }: { kind: Story["kind"]; sources: number }) {
  const label = {
    confirmed: `Reported by ${sources} outlets`,
    report: "Single report",
    developing: "Developing",
    commentary: "Commentary",
  }[kind];
  return <span className={cn("np-kind", `k-${kind}`)}>{label}</span>;
}

function Lead({ story, now }: { story: Story | null; now: number }) {
  const [open, setOpen] = useState(false);
  if (!story)
    return (
      <article className="np-lead">
        <h2 className="np-lead__head">No lead story yet</h2>
      </article>
    );
  return (
    <article className="np-lead">
      <h2 className="np-lead__head">
        <a href={story.url} target="_blank" rel="noopener noreferrer">
          {story.title}
        </a>
      </h2>
      <p className="np-byline">
        <span>{story.publishers.join(" · ")}</span>
        <span className="np-mono">{ago(story.last_at, now)}</span>
        <KindTag kind={story.kind} sources={story.sources} />
      </p>
      <div className="np-lead__body">
        {story.image ? (
          <figure className="np-lead__fig">
            {/* eslint-disable-next-line @next/next/no-img-element -- publisher's own feed image, remote */}
            <img src={story.image} alt="" loading="eager" referrerPolicy="no-referrer" />
            <figcaption className="np-mono">Image: {story.source}</figcaption>
          </figure>
        ) : null}
        <div>
          {story.summary ? <p className="np-lead__dek">{story.summary}</p> : null}
          <p className="np-src">
            <a href={story.url} target="_blank" rel="noopener noreferrer">
              Read at {story.source}
              <IconArrow className="np-ico" />
            </a>
          </p>
          {story.timeline.length > 1 ? (
            <div className="np-timeline">
              <button
                type="button"
                className="np-linkbtn"
                aria-expanded={open}
                onClick={() => setOpen((o) => !o)}
              >
                {open ? "Hide" : "Follow"} the story — {story.timeline.length} reports since{" "}
                {clock(story.first_at)}
              </button>
              <div className={cn("np-fold", open && "is-open")} inert={!open}>
                <ol className="np-timeline__list">
                  {story.timeline
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
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function Briefing({ data, now }: { data: Newsroom; now: number }) {
  const b = data.briefing;
  if (!b) return null;
  return (
    <aside className="np-brief" aria-labelledby="np-brief-h">
      <h2 id="np-brief-h" className="np-brief__head">
        Crypto in 60 seconds
      </h2>
      <div className="np-brief__cols">
        {(
          [
            ["What happened", b.what],
            ["Market context", b.why],
            ["What to watch", b.watch],
          ] as const
        ).map(([h, lines]) =>
          lines.length ? (
            <div key={h} className="np-brief__part">
              <h3>{h}</h3>
              <ul>
                {lines.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </div>
          ) : null,
        )}
      </div>
      <p className="np-fine">
        {b.note} Updated {data.generated_at ? ago(data.generated_at, now) : "—"}.
      </p>
    </aside>
  );
}

function Colophon({ data, now }: { data?: Newsroom; now: number }) {
  const rows = useMemo(
    () => Object.entries(data?.status ?? {}).sort(([a], [b]) => a.localeCompare(b)),
    [data?.status],
  );
  return (
    <footer className="np-colophon">
      <div>
        <h2 className="np-colophon__flag">Memescope</h2>
        <p>
          An automated newspaper. Headlines and summaries belong to their publishers and
          link to the original. Market data: CoinGecko, alternative.me, mempool.space,
          DexScreener, DeFiLlama. Lab data: measured by MEMESCOPE from pump.fun graduations.
          Nothing here is financial advice.
        </p>
      </div>
      <div>
        <h3>Wire status</h3>
        <ul className="np-status">
          {rows.map(([name, s]) => (
            <li key={name} className={s.ok ? "is-ok" : "is-down"}>
              <i aria-hidden />
              <span>{SOURCE_LABEL[name] ?? name}</span>
              <span className="np-mono">
                {s.ok
                  ? s.last_ok
                    ? ago(s.last_ok, now)
                    : "ok"
                  : `down${s.last_ok ? ` · last ${ago(s.last_ok, now)}` : ""}`}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </footer>
  );
}

function LatestHeadlines({ stories }: { stories: Story[] }) {
  return (
    <nav className="np-latest" aria-label="More top stories">
      <h3>Also in the news</h3>
      <ol>
        {stories.map((s) => (
          <li key={s.id}>
            <a href={s.url} target="_blank" rel="noopener noreferrer">
              {s.title}
            </a>
            <span className="np-fine">{s.source}</span>
          </li>
        ))}
      </ol>
    </nav>
  );
}

function LabFindings({ ours }: { ours: Newsroom["ours"] }) {
  return (
    <section className="np-labfindings" aria-labelledby="lab-findings-h">
      <div>
        <span className="np-badge">Measured by Memescope</span>
        <h2 id="lab-findings-h">From our lab</h2>
      </div>
      {ours ? (
        <p>
          <strong>{ours.graduations_24h}</strong> pump.fun graduations in 24 hours;{" "}
          <strong>{ours.graduations_1h}</strong> in the last hour.
          {ours.rug_rate_24h != null ? (
            <>
              {" "}
              Of <strong>{ours.rug_measured_24h}</strong> measured coins,{" "}
              <strong>{ours.rug_rate_24h}%</strong> lost 80% or more within their first
              hour.
            </>
          ) : (
            " First-hour outcomes are not available yet."
          )}
        </p>
      ) : (
        <p>Lab observations are currently unavailable.</p>
      )}
      <a className="np-linkbtn" href="#chain">
        Explore measured collapses <IconArrow className="np-ico" />
      </a>
    </section>
  );
}
