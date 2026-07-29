# Alpha invitation pack

Everything to send the first cohort. Fill the four placeholders — `<URL>`,
`<SUPPORT>`, `<CHANNEL>`, `<NAME>` — and send.

Companion to [`ALPHA_CHECKLIST.md`](../ALPHA_CHECKLIST.md), which covers running
the alpha once people are in.

---

## 1. Invitation email

> **Subject:** MEMESCOPE — early access
>
> Hi `<NAME>`,
>
> I have been building MEMESCOPE and would like you to be one of the first
> people to use it.
>
> It watches Solana for newly launched tokens, gathers market data on each one,
> and scores them with a transparent model — no black box. It also tells you how
> much it actually knows about each token, which turns out to be the more useful
> half.
>
> **`<URL>`**
>
> It is genuinely early. Four of the nine signals the model declares are not
> collected yet, so confidence reads low across the whole feed. That is
> deliberate and visible on screen rather than hidden — but it means scores are
> thinner than they will be.
>
> What I would most like to know:
>
> - Do the scores make sense to you?
> - Can you tell what the product does **not** know?
> - What would you have done next, if it let you?
>
> There is a Feedback button on every page. It takes ten seconds and it is the
> entire point of this phase — bug reports, confusion, and "this is useless
> because…" are all equally welcome.
>
> One thing to be clear about: MEMESCOPE is an intelligence tool, not financial
> advice. Nothing in it is a recommendation to buy or sell. Meme coins routinely
> go to zero.
>
> Any problems, reply to this email or reach me at `<SUPPORT>`.
>
> Thank you for taking a look.

---

## 2. Known limitations — send with the invitation

Do not let testers discover these and file them as bugs. Their attention is the
scarce resource; spend it on findings you do not already have.

**Scoring**

- **Four of nine signals have no data source yet** — contract safety, holder
  distribution, smart money, narrative. They are declared, weighted, and counted
  against coverage rather than quietly dropped.
- **Confidence reads low across the feed** (typically 30–45%). Working as
  designed, not a fault.
- **No token can be certified Elite.** The gate needs more evidence than the
  current model can produce. Gold stays dark on purpose.
- **Liquidity is missing for most brand-new tokens** — the data provider does not
  report it for bonding-curve pools.
- Scores read *current state*. They are not predictions.

**Product**

- Read-only: no watchlist, alerts, portfolio or wallet connection. Nothing is
  ever signed.
- Designed for a wide screen; mobile works but is not the intended experience.

**Operational**

- Data may be reset during the alpha.
- Brief downtime during deploys.
- Browsers: current Chrome, Safari 16.2+, Firefox 113+.

---

## 3. Feedback instructions

> **Use the Feedback button — bottom right of every page.**
>
> Pick a category (Bug, Suggestion, Feature request, General), describe what you
> saw and what you expected instead, and send. The page you were on and the exact
> build are attached automatically, so you never need to tell me where you were.
>
> Especially useful:
>
> - A number that looked wrong, with the token name.
> - A word or label you had to guess the meaning of.
> - A moment you wanted to do something and could not find how.
> - Anything that made you distrust what you were reading.
>
> "I did not understand what I was looking at" is a first-class bug report here.

---

## 4. Support contact

| | |
|---|---|
| Primary | `<SUPPORT>` |
| Group channel | `<CHANNEL>` |
| Response target | Same day, weekdays |

Set expectations honestly. A small alpha does not need a support rota, but it
does need a reply — a tester who reports something and hears nothing does not
report a second time.

---

## 5. Week-one plan

1. **Day 0** — invite in small batches (5, then 10, then the rest). A problem
   found by the first five is a problem the other twenty never see.
2. **Day 1–2** — read every report the day it lands and acknowledge it, even
   without a fix.
3. **Day 3–5** — a 15-minute call with each tester who used it more than once.
   The form catches specifics; the call catches "I did not know what that meant",
   which is the finding that matters most and the one nobody writes down.
4. **Day 7** — decide against the success criteria in
   [`ALPHA_CHECKLIST.md`](../ALPHA_CHECKLIST.md).

---

## 6. Before sending — non-negotiable

- [ ] `<URL>` loads over HTTPS from a device outside the deployment network
- [ ] **A feedback destination is configured.** Without
      `NEXT_PUBLIC_FEEDBACK_ENDPOINT` or `NEXT_PUBLIC_FEEDBACK_URL`, reports are
      shown to the tester for copying and **nothing reaches you** — the alpha
      collects no data and there is no signal that it is failing to.
- [ ] `./scripts/health-check.sh` passes 12/12 against the public URL
- [ ] A database backup exists and has been test-restored
- [ ] `<SUPPORT>` is an address you actually read
