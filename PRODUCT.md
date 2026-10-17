# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Signed-in members** (Karthik, Rafiq and alpha testers): the newspaper is their home page after sign-in (/home), beside every lab and wallet in the left rail (Karthik, 2026-10-17: "i want this page inside login as an homepage").
- **Public visitors** see the space-themed landing at "/" with the access-code entry.

## Product Purpose

MEMESCOPE tests pump.fun graduation trading strategies on paper, against fair controls, before any real money follows them; a real wallet then trades the rules that held up. The home page after sign-in is a continuously updating crypto newspaper: what happened, why it matters, what to watch next. Success is a page people reopen through the day.

## Positioning

The newspaper mixes global crypto coverage with numbers only MEMESCOPE has: its own live pump.fun graduation feed, rug rates, BOOST activity and lab results measured from real data, published with their failures as well as their wins.

## Operating Context

- Frontend: Next.js on Vercel (www.memescope.site); backend: FastAPI + Postgres + Celery on an OVH server (api.memescope.site), behind Caddy.
- The public landing at "/" stays the space theme (frog-astronaut mascot, alpha access-code entry, moon intro, "Built through failure" journey, live checkpoint); sign-in leads to the newspaper at /home.
- All times are shown in the visitor's local time on the newspaper; the team's own tools use Dubai time (UTC+4).

## Capabilities and Constraints

- **Free data sources only** (confirmed 2026-10-17): public news RSS feeds (CoinDesk, Cointelegraph, Decrypt, The Block and similar), CoinGecko public API, DeFiLlama hacks, DexScreener, and MEMESCOPE's own database. Sections with no free reliable source (token-unlock calendars, whale-transfer alerts, liquidations) show an honest "not connected yet" state, never invented data.
- Provider rate limits: CoinGecko public, DexScreener and GeckoTerminal punish bursts; every feed is fetched server-side, cached, and served from our own API.
- Never invent prices, headlines, sources, metrics or events. Label developing reports versus confirmed ones, and possible explanations versus proven causes.
- The repository is public: no credentials in code.

## Brand Commitments

- Name: MEMESCOPE (always the wordmark, never a legacy display name).
- Mascot: the frog astronaut (frontend/public/mascot), used for the app icon.
- Voice: plain words, honest about losses and uncertainty; no hype claims.

## Evidence on Hand

- Live pump.fun graduation data: grad_migrations, grad_tokens, grad_postgrad_samples, grad_paper_positions, grad_open_buys.
- Lab results and the journey log already published on the current landing.
- No testimonials, users counts, partnerships or press exist; never fabricate them.

## Product Principles

1. Honest before impressive: show sources, times and uncertainty; empty is better than invented.
2. One glance, then depth: every section previews in a line or two and expands on demand.
3. Our own numbers are the edge: lab data sits beside world news, clearly labelled as ours.
4. Stable reading: new items wait behind an "updates" control instead of moving content.

## Accessibility & Inclusion

Respect reduced-motion preferences, full keyboard navigation, readable contrast on a dark background.
