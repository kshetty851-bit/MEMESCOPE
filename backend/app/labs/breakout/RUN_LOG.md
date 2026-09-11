# Breakout Lab — run log

One line per VERIFY pass. Newest at the bottom.

| # | phase | iter | what failed | what changed |
|---|---|---|---|---|
| 1 | 0 | 1 | — (carry-over fixes) | hourly/daily cadence now clock-derived (no request when a bar has not closed); explicit `breakout-lab-tick` beat line + `include` in celery_app.py, `setdefault` removed; `starved_tokens` added to data_health; MAX_ATTEMPTS 5→7, backoff ceiling 30s→60s after measuring GeckoTerminal at 3 spacings (2.4s→8/15 429, 4s→7/15, 6s→5/15: sustained rate is ~4-5/min, not 30) |
| 2 | 2 | 1 | levels: the "merge duplicate clusters" pass was unreachable — a new group opens only when the previous group's mean is already final and >pct away, so no two clusters can converge | removed `_merge_adjacent` as dead code; replaced its test with a parametrised assertion of the INVARIANT (no two clusters within CLUSTER_PCT), which is what the decision was actually for |
| 3 | 2 | 2 | momentum/levels: 3 ruff findings (zip-over-pairwise x2, dict() literal); test asserted a dataclass equals a tuple; win_rate compared exactly against a value the route rounds to 4dp | switched to `itertools.pairwise`, dict literal, compared fields not tuples, added `abs=1e-4` |
| 4 | 2 | 3 | isolation suite still described one migration and two Phase-1 route paths | parametrised over both migrations, added the six route paths, added a test that levels/momentum/setups import no network module |
| 5 | 2 | 4 | — all DoD items pass | migration 0064 up->down->up clean, `alembic check` zero `bo_`, 185 lab tests green, live setups pass: 13 tokens / 9 levels / 1 episode / 0 errors / 0 requests |
| 6 | 3 | 1 | trader: `latest_bar()` returned `MAX(close_time)` and ignored `now`, so every tick of a replay acted on the newest bar in the table | bounded it by `close_time <= now` — a bar that has not closed must never be traded on, and a backfilled table holds bars ahead of the tick being replayed |
| 7 | 3 | 2 | consistency test failed 54.45% vs 56.78%: `config` values were bound as DEFAULT ARGUMENTS in rules.py, so `monkeypatch.setattr(config, ...)` silently changed nothing | every cost and cap now reads `config` inside the body, as the flag functions already did. A future replay sweeping slippage would have hit the same trap |
| 8 | 3 | 3 | two test fixtures wrong, not the code: filler positions had no universe row (correctly force-exited, freeing the slots) and the kill-switch position's trail fired before the halt | gave fillers universe rows + bars; widened the kill-switch position's slot so the halt is what closes it |
| 9 | 3 | 4 | — all DoD items pass | migration 0065 up->down->up clean, `alembic check` zero `bo_`, 242 lab tests green, live tick with trading on: equity 1000.00, 0/10 slots, 0 positions |
| 10 | 4 | 1 | `@testing-library/user-event` is not a dependency and may not be added | rewrote the interaction tests on `fireEvent`, which RTL already ships |
| 11 | 4 | 2 | `EmptyState` takes `body`, not `description` — 4 typecheck errors | renamed the prop at all four call sites |
| 12 | 4 | 3 | — all DoD items pass | 27 lab tests + the full 1023-test frontend suite green; eslint clean; typecheck at the pre-existing baseline of 4 errors (none in this lab); every field the page reads diffed against the live routes: ZERO mismatches; all 11 routes 200 over real HTTP |
