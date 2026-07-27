# MemeScope AI — Frontend

Next.js 15 App Router client.

## Layout

```
src/
├── app/              Routes. Route groups: (auth) public, (dashboard) protected.
├── components/
│   ├── ui/           Presentational primitives (Button, Input, Card).
│   └── layout/       Shell pieces (AppHeader).
├── hooks/            useAuth, useRequireAuth.
├── lib/              api-client (fetch + refresh), env (validated), utils.
├── stores/           Zustand session store.
├── styles/           Tailwind v4 entry and design tokens.
└── types/            Types mirroring the backend schemas.
```

## Auth model

The access token is held in memory in `lib/api-client.ts` — never in
localStorage, which any injected script can read. The refresh token is an
httpOnly cookie the browser attaches on its own.

On load, `Providers` calls `bootstrap()`, which hits `/auth/refresh`. A valid
cookie restores the session; otherwise the visitor is anonymous.

`apiFetch` retries once through a refresh on a 401. Concurrent 401s share one
in-flight refresh, because the server rotates refresh tokens and treats a
replayed one as theft — parallel refreshes would log the user out.

## State

- **Server state** — TanStack Query. Anything fetched from the API.
- **Session state** — Zustand (`stores/auth-store.ts`).
- **Local UI state** — `useState`.

Do not mirror API responses into Zustand; the query cache is the source of truth.

## Styling

Tailwind CSS v4, configured in CSS. Design tokens live in the `@theme` block of
`src/styles/globals.css` and become utilities automatically — `bg-surface`,
`text-muted`, `text-brand`. There is no `tailwind.config.js`.

## Commands

```bash
npm run dev
npm run build
npm run lint
npm run typecheck
npm run test
```

Or from the repository root: `make test-frontend`, `make lint`.

## Environment

`NEXT_PUBLIC_*` variables are validated by Zod in `src/lib/env.ts` at import
time, so a missing value fails the build rather than a user's session. They are
inlined at build time — changing one requires a rebuild.
