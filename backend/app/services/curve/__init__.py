"""Direct bonding-curve observation.

DexScreener reports a *pair*; the chain reports the *curve*. Sprint 7 measured
that the first cannot stand in for the second — `market_cap` on a bonding-curve
pair identified 5 of 386 observed graduations (ARCHITECTURE_DECISIONS.md §14a).
This package reads the curve itself.

Deliberately no re-exports: `app/models/curve.py` is imported by the collector,
and pulling the collector in here would drag the whole I/O path into a table
definition. Import from the module you need.
"""
