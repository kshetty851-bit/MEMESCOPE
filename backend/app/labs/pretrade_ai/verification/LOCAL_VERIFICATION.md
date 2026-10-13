# MEMESCOPE isolated-lab verification — 13 October 2026

- Original archive: all 37 manifest entries matched SHA-256 before import.
- Scope: new files under `backend/app/labs/pretrade_ai/` only. Pre-existing modifications to `graduation/tournament.py` and `backend/.venv`, and all other untracked work, were left as found.
- Environment: dedicated lab `.venv`, Python 3.12.13; no backend dependency file changes.
- Regression suite: **17 passed** (six supplied tests, eleven isolation/hardening tests).
- End-to-end lab demo: **passed**, 120 synthetic input rows and 23 held-out rows.
- Shell demo entry point: **passed**.
- Public lab `validate` command: **passed**, 120 records with outcomes.
- Public lab `score` command: **passed**, 23 held-out advisory scores.
- No migrations, database operations, application registration, deployment, scheduled jobs, strategy hooks, or wallet changes.
- Real data mapping remains unresolved; no real model training or forward validation is claimed.

Generated fixtures/model/reports remain ignored in `artifacts/demo/`. They demonstrate software behavior only; none is evidence of trading profitability. The original `VERIFICATION.md` describes the upstream build, while this file describes the local integration.
