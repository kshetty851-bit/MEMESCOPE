"""HQ operations: the machinery MEMESCOPE runs on, as something HQ can read.

Deliberately separate from `app.health`, which answers "is the *pipeline*
producing anything" — discovery, enrichment, scoring, radar. This package
answers the different question underneath it: are the container's disk, the
broker, the database, the worker and the scheduler alive, and is anything
queued behind them.

Nothing in here touches trading. It reads infrastructure and it writes an
audit trail; it has no access to strategy, position sizing, wallets or the
permanent record, and it is not permitted to acquire one.
"""
