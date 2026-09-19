"""The Rafiq Lab's database fixtures, reused: their own engine, and a session
in an outer transaction that is always rolled back, with autoflush off like
production's. Skipped cleanly when there is no Postgres."""

from app.labs.rafiq.tests.conftest import lab_engine, lab_session  # noqa: F401
