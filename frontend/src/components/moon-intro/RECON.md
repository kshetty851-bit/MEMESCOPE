# Moon intro — recon (branch feat/moon-intro)

**Slot.** Homepage alpha gate, `src/components/alpha/landing-page.tsx`. `<AlphaAccess onPhase>`
calls `onPhase("approved")` AFTER the server accepted the access code (auth is done). The page
latches `approved`, `useLaunchSequence` (`alpha/launch-sequence.tsx`, timeline in `lib/launch.ts`)
walks approved → countdown ×5 → ignition → launching → flight → approach → unlock → enter, and
`enter()` = `router.push(ALPHA_ACCESS.dashboardPath)` = `/karthik-lab` (signed-out visitors are then
sent to `/login` by the dashboard). The new intro replaces that sequence in the same slot and calls
the same `enter()` when done. `AlphaAccess` and everything under `src/lib/auth*`, `hooks/use-auth*`,
`app/(auth)` must not change.

**Old visuals to retire (Worker D, after the new flow works):** `LaunchOverlay` +
`useLaunchSequence` (`alpha/launch-sequence.tsx` + test), the "Access approved"/"Launching in"
card CSS in `styles/memescope.css` (`.launch-card*`), `alpha-transition`, and the launch-only
rules in `styles/home-universe.css` driven by `data-launch`/`data-sequence`/`data-lit`/`data-flying`.
The idle homepage scene (rocket on its pad, moon, crew, cartoon planets) stays.

**Stack.** Next 15 (app router, `next/navigation`), React 19, TypeScript 5.7 strict, Tailwind v4
(tokens in `src/styles/globals.css` `@theme`), plain global CSS files imported in
`src/app/layout.tsx` (no CSS modules). Vitest + Testing Library (jsdom). Fonts: Geist Sans
(`--font-geist-sans`), Geist Mono (`--font-geist-mono`) — use the mono for all HUD text.

**Palette (oklch tokens).** canvas/sunken near-black blue (`--color-void`, `--color-abyss`),
`--color-surface` panels, `--color-line*` borders, `--color-ink`…`--color-ink-4` text,
`--color-accent` cyan, `--color-up` green (pump), `--color-down` red (dump), `--color-warn` amber
(hazard stripes). Use `var(--color-…)`; no new hex palettes except inside canvas drawing.

**Contract.** `src/components/moon-intro/timeline.ts` is the single source of timing: phases,
durations, `MOMENTS` (fractions within a phase), `Frame {t, dt, phase, p, mode}`, readouts, labels.
All files live in `src/components/moon-intro/`. Layers never run their own loops or timers.

**Hooks already present:** `useReducedMotion()` (`src/hooks/use-reduced-motion.ts`).

**Gates.** `npm run lint` (max-warnings 0), `npm run typecheck` (baseline: 5 pre-existing errors in
`space-audio-toggle.test.tsx`, `lib/hq/visitors.test.ts`, `lib/paper.test.ts` — do not add any),
`npm run build`, `npx vitest run <paths>`. Run commands from `frontend/`.

**Prior owner wishes (Karthik):** launch audio was removed at his request — sound must be OFF by
default. He likes cute cartoon motion (bouncy easing is approved). Times shown in Dubai.
