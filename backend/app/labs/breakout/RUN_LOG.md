# Breakout Lab — run log

One line per VERIFY pass. Newest at the bottom.

| # | phase | iter | what failed | what changed |
|---|---|---|---|---|
| 1 | 0 | 1 | — (carry-over fixes) | hourly/daily cadence now clock-derived (no request when a bar has not closed); explicit `breakout-lab-tick` beat line + `include` in celery_app.py, `setdefault` removed; `starved_tokens` added to data_health; MAX_ATTEMPTS 5→7, backoff ceiling 30s→60s after measuring GeckoTerminal at 3 spacings (2.4s→8/15 429, 4s→7/15, 6s→5/15: sustained rate is ~4-5/min, not 30) |
| 2 | 2 | 1 | levels: the "merge duplicate clusters" pass was unreachable — a new group opens only when the previous group's mean is already final and >pct away, so no two clusters can converge | removed `_merge_adjacent` as dead code; replaced its test with a parametrised assertion of the INVARIANT (no two clusters within CLUSTER_PCT), which is what the decision was actually for |
| 3 | 2 | 2 | momentum/levels: 3 ruff findings (zip-over-pairwise x2, dict() literal); test asserted a dataclass equals a tuple; win_rate compared exactly against a value the route rounds to 4dp | switched to `itertools.pairwise`, dict literal, compared fields not tuples, added `abs=1e-4` |
| 4 | 2 | 3 | isolation suite still described one migration and two Phase-1 route paths | parametrised over both migrations, added the six route paths, added a test that levels/momentum/setups import no network module |
| 5 | 2 | 4 | — all DoD items pass | migration 0064 up->down->up clean, `alembic check` zero `bo_`, 185 lab tests green, live setups pass: 13 tokens / 9 levels / 1 episode / 0 errors / 0 requests |
