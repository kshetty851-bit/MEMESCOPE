"""Opportunity Radar — the intelligence layer above the launch scanner.

The scanner answers "what launched?". The Radar answers "which projects are
getting stronger?", of any age, and records what happened to every one it ever
surfaced.

Package layout mirrors `services/scoring` on purpose — a pure engine with two
I/O seams — so that one discipline covers both and `test_radar_purity.py`
enforces it:

    models.py       domain types (pure)
    normalise.py    bounded transforms (pure)
    momentum.py     is it getting stronger? (pure)
    technical.py    what is the price structure? (pure)
    health.py       health · liquidity quality · risk (pure)
    community.py    declared, no data source (pure)
    scorer.py       weights, renormalisation, coverage (pure)
    detector.py     category gates (pure)
    achievements.py milestones + performance from first detection (pure)
    explain.py      reason codes rendered to English (pure)
    repository.py   ← I/O seam: database
    service.py      ← I/O seam: orchestration
    scheduler.py    ← I/O seam: Celery tasks
    api.py          ← I/O seam: HTTP
"""
