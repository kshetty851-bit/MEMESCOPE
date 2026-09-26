# Moon intro — report (branch feat/moon-intro, not pushed)

Replaces the homepage's "ACCESS APPROVED" + 5-4-3-2-1 rocket launch with a ~10.8s cockpit ride:
seatbelt → cockpit assembly → ignition → warp → moon approach (asteroid near-miss) → landing →
LANDING CONSOLE + dolly-through, then the same `enter()` as before (`router.push("/karthik-lab")`).

## Commits
| | |
|---|---|
| 4460cd6 | recon + shared `timeline.ts` contract |
| 3b87e16 | Worker C — synthesized soundboard (WebAudio, no files) |
| 8ff6c8c | Worker A — cockpit frame + HUD (SVG/CSS, no timers, no per-frame React renders) |
| df6e093 | Worker B — space canvas engine (Canvas 2D, baked moon, candle streaks, dust) |
| 4bc3945 | Worker D — master clock + swap into the alpha gate (lazy, warmed on idle) |
| 3e42683 | old launch removed (overlay, timeline, launch-only scene parts, ~600 lines CSS) |
| dc63f70 | QA fix — the short cut skips the asteroid near-miss |

## Measured (production build, local Chrome 153 headless, 1440×900)
- **Bundle:** intro is a lazy chunk — 25.8 KB raw / **10.1 KB gzipped JS + 3.2 KB gzipped CSS** (budget 60 KB).
  Not in the homepage's first load; fetched on idle (`requestIdleCallback`, 4s timeout / 2s Safari fallback).
- **Frame cost** (rAF uncapped via `--disable-frame-rate-limit`, so intervals show work, not vsync):
  warp avg **1.33 ms**/frame (max 7.1), approach avg **1.43 ms** (max 7.0) — budget 16.7 ms.
  JS inside the intro's rAF: warp 0.03 ms avg (p95 0.1), approach 0.17 ms avg (p95 0.7).
- **Timeline accuracy:** screenshots taken by the intro's own clock landed on every intended phase
  (0.5 seatbelt · 2.0 cockpit · 3.0 ignition · 4.5 warp · 6.6 approach/near-miss · 8.0 approach/lock ·
  9.5 landing · 10.3 reveal).
- **Handoff:** dashboard navigation requested **11.1 s** after Enter (10.8 s ride + ~0.4–0.8 s to mount).
- **Skip** (Esc at 3 s): navigation requested **466 ms** later (target ≤ 700 ms).
- **Reduced motion:** mode `reduced`, static cockpit → door, **1.9 s** from Enter.
- **Same session again:** mode `short`, **2.9 s** from Enter; no asteroid/crack/alarm.
- **390×844 phone:** no horizontal scroll; HUD stacks, side struts collapse.
- **Idle homepage** unchanged at 1440 / 1024 / 375 (frog, rocket on pad, 18 planets, crew; no console errors).
- **Auth:** `git diff origin/main` over `alpha-access.tsx`, `app/(auth)`, `lib/auth*`, `hooks/use-auth*`,
  `lib/api-client*` is **empty**.
- **Gates:** eslint clean; tsc = the 5 pre-existing errors; vitest 1135 pass / 1 pre-existing failure
  (AppSidebar QueryClient); `next build` green.

Screenshots and the QA script live OUTSIDE the repo (no new dev dependency was added):
`~/Projects/memescope-moon-qa/intro-qa.js`, `~/Projects/memescope-moon-qa/shots/`
(`full-*.png`, `mobile-*.png`, `reduced-0.7s.png`, `short-1.2s.png`, `idle-*.png`),
numbers in `~/Projects/memescope-moon-qa/qa-report.json`. Run: start the production build on :3131,
then `node intro-qa.js`.

## Deviations from the brief
- **Playwright:** `playwright-core` driving the installed Chrome from a folder outside the repo, instead of
  `@playwright/test` as a repo dev dep — this Mac can't download Playwright's browsers (npm/GitHub TLS
  filtering), and it keeps the app's dependencies unchanged.
- **"Login fades in inside the cockpit":** the next screen is another route (`/karthik-lab`, which sends a
  signed-out visitor on to `/login`), so it can't render inside the frame. The canopy becomes a
  LANDING CONSOLE ("Docking with Karthik's Lab…"), the frame dollies past the camera, and the dashboard
  (prefetched when the code is accepted) takes over.
- **End-to-end login** was not exercised: it needs the real access code / credentials. The alpha API was
  faked inside the test browser only; the handoff calls the unchanged `enter()`.
- **Frame timings** are headless-Chrome numbers on an M-series Mac, not a trace from a mid laptop.

## Tuning (all in `timeline.ts`)
- Phase lengths: `TIMELINE` (full), `SHORT_TIMELINE`, `REDUCED_TIMELINE`.
- Beats inside a phase: `MOMENTS` (fractions of the phase), e.g. `approach.nearMiss`, `landing.touchdown`.
- Shake: `SHAKE.base` per phase and the kicks `lockIn` 4 px, `nearMiss` 14 px, `touchdown` 10 px —
  the near-miss kick is the first thing to soften if it feels harsh.
- Words: `SWITCHES`, `RADIO`, `WARP_READOUTS`, `ASTEROID_LABELS`.

## Worth a look before shipping
- ~0.4–0.8 s of the idle page between Enter and the black cut if the idle prefetch hasn't run yet.
- At the very end the last frame holds until the dashboard paints.
- Sound is off by default (speaker toggle, remembered per browser) — Karthik earlier asked for a silent
  launch, so it stays opt-in.
