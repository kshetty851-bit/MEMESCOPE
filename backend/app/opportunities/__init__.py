"""The Opportunity Engine — MEMESCOPE's central intelligence layer.

Every opportunity exists because something changed. The engine receives
candidate signals from providers, merges them into opportunities, drives the
lifecycle, and records every transition as an immutable event.

It is subject-matter free by construction: it knows nothing about Pump.fun,
graduation or any other domain. `providers/` supplies those, and adding one is
a registration plus a pure module (ARCHITECTURE_DECISIONS.md AD-04).

Detection is event-driven. It runs when enrichment commits a snapshot for a
token, so work is proportional to change rather than to table size — there is
no recurring scan of the universe.

Deliberately no re-exports. `app.models.opportunity` imports the enums from
`models.py` to type its columns, so pulling the engine in here would make
importing a table definition drag in the whole engine — and, since the engine
imports those tables back, form a cycle. Import from the module you need:

    from app.opportunities.engine import OpportunityEngine
    from app.opportunities.models import OpportunityStatus
"""
