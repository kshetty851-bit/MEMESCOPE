# MEMESCOPE — Private Alpha Checklist

Operating document for the first invited cohort (10–25 users). The technical
specification lives in [`MEMESCOPE_MASTER_CONTEXT.md`](MEMESCOPE_MASTER_CONTEXT.md);
this file covers running the alpha.

---

## Known limitations

Tell testers these up front. Every one is visible in the product, and a tester
who discovers a limitation themselves and thinks it is a bug spends their
goodwill on a report you already knew about.

**Scoring**

- **Four of nine signals have no data source.** Contract safety, holder
  distribution, smart money and narrative are declared, weighted, and counted
  against coverage. Available weight totals 0.65.
- **Confidence reads low across the whole feed** — typically 30–45%. That is the
  coverage mechanism working, not a fault.
- **No token can be certified Elite.** The gate needs evidence ≥ 70 and the
  ceiling is 65. Gold stays dark until contract data exists (Day 6).
- **Liquidity is missing for pump.fun bonding-curve pools**, which is most new
  tokens. DexScreener does not report it.
- **Grade bands (30/50/65/80) are an engineering default**, not a product
  decision. Worth asking testers whether the labels match their intuition.
- Scores are **not predictions**. The model reads current state.

**Product**

- No watchlist, no favourites, no alerts, no portfolio. Read-only.
- No wallet connection. Nothing is ever signed.
- Offset pagination on the ranking can shift a row between pages while a client
  walks them.
- Mobile is supported but the instrument is designed for a wide screen.

**Operational**

- Data may be reset during the alpha.
- Deploys cause a few seconds of downtime.
- Backups are on the same host as the database.
- Browser floor: Chrome 111 · Safari 16.2 · Firefox 113.

---

## Pre-launch testing checklist

Run against the deployed environment, not localhost. `./scripts/health-check.sh`
covers the mechanical half; this covers what a person sees.

### Infrastructure

- [ ] `./scripts/health-check.sh` passes 12/12 against the public URL
- [ ] HTTPS certificate valid; `http://` redirects to `https://`
- [ ] `/docs` and `/openapi.json` return **404**
- [ ] Security headers present (HSTS, CSP, `X-Frame-Options`, `nosniff`)
- [ ] Rate limiting buckets per client — two devices do not share an allowance
- [ ] A backup exists in `/backups/daily` and `pg_restore --list` reads it
- [ ] Sentry receiving events (if a DSN is configured)
- [ ] `BUILD_SHA` in the alpha bar matches the deployed commit

### First-run experience

- [ ] Landing page loads and explains the product without scrolling
- [ ] Alpha bar shows version, build SHA and a working feedback route
- [ ] "How to read this dashboard" appears on first visit, dismisses, stays gone
- [ ] About page reachable from the nav and answers "why trust this score"
- [ ] Nothing on screen uses a term the About page does not define

### Every surface

- [ ] **Command Center** — Sentinel brief, Core, live discoveries, division rail
- [ ] **Scanner** — feed populates, cards readable
- [ ] **Division** — seven agents, unavailable ones say so
- [ ] **Token detail** — Sentinel read, component waterfall reconciles to the score
- [ ] **Observatory Log** — category filters work, entries carry agent and severity
- [ ] **System** — diagnostics render
- [ ] **About** — grade table and coverage explanation correct

### States

- [ ] Loading shows skeletons, not blank panels
- [ ] Empty feed says the chain is quiet, **not** an endless skeleton
- [ ] Backend down shows an error with a retry, **not** an endless skeleton
- [ ] An unscored token explains which state it is in
- [ ] Reduced-motion honoured (`prefers-reduced-motion`), Command mode stills motion

### Quality

- [ ] Zero console errors on every page
- [ ] Zero backend tracebacks during a session
- [ ] Dashboard issues exactly **5 API requests**, no duplicates
- [ ] Keyboard reaches every control; focus is always visible

---

## How to collect feedback

**In-product.** The floating **Feedback** button is on every page of the
instrument, with four categories: Bug · Suggestion · Feature request · General.
Each report carries the page path, build SHA, environment and user agent — so a
report is reproducible without a follow-up conversation.

**Configure a destination before inviting anyone.** In `.env.production`:

| Variable | Effect |
|---|---|
| `NEXT_PUBLIC_FEEDBACK_ENDPOINT` | POSTs the report as JSON. Preferred — the tester never leaves the page. |
| `NEXT_PUBLIC_FEEDBACK_URL` | Opens an external form. Fallback. |
| *neither* | The report is shown back for copying. **Nothing is lost, but nothing is collected.** |

`lib/feedback.ts` is the only file that knows where reports go. Connecting a
real backend or a third-party service is one function.

**Out of product.** Run a shared channel for the cohort and ask for a short
call with each tester in week one. The report form catches specifics; the call
catches "I did not understand what I was looking at", which is the finding that
matters most at this stage and the one nobody writes down.

**What to ask for.** Bug reports are the easy half and testers volunteer them.
Deliberately ask for the other half:

- What did you expect this number to mean?
- What would you have done next, if the product let you?
- What stopped you coming back the second day?

---

## Success criteria

The alpha is about whether the product is understood and trusted, not usage
volume. Twenty people cannot produce a meaningful engagement metric.

**Must be true to continue**

- No tester is misled about what a score means. Nobody reports treating a grade
  as a prediction or a recommendation.
- No data-integrity report survives investigation — Sentinel's prose never
  contradicts a number on screen, and a waterfall always reconciles.
- Zero unhandled backend exceptions across the cohort's sessions.
- Every tester finds the feedback button without being told where it is.

**Signals of product-market fit**

- Testers return unprompted on a second and third day.
- Someone asks for a specific token to be explained — they trusted the read
  enough to want more of it.
- Feature requests cluster. Scattered requests mean the core is not yet valuable
  enough to have an obvious next step.
- At least one tester says the confidence figure changed a decision. That is the
  product's actual thesis, and it is the one thing worth proving here.

**Signals to stop and reconsider**

- Testers cannot say what MEMESCOPE is for after using it.
- Low confidence reads as "broken" rather than "honest" — that would mean the
  coverage mechanism is failing at its explanatory job, not its arithmetic.
- Nobody comes back after the first session.

---

## Invitation note

Send something close to this. It sets the frame the product is designed for.

> MEMESCOPE watches Solana for new token launches and scores them with a
> transparent model — no black box, and it tells you how much it actually knows
> about each one. It is early: four of nine signals aren't collected yet, so
> confidence reads low across the board. That is deliberate and visible.
>
> I would like to know whether the scores make sense to you, and whether you can
> tell what the product does not know. The feedback button is on every page.
>
> It is an intelligence tool, not advice. Nothing here is a recommendation.
