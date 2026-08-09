from datetime import UTC, datetime, timedelta

from app.services.alpha_activity import status_for


def test_activity_status_boundaries() -> None:
    now = datetime.now(UTC)
    assert status_for(now - timedelta(seconds=60), now=now) == "active"
    assert status_for(now - timedelta(seconds=61), now=now) == "idle"
    assert status_for(now - timedelta(seconds=600), now=now) == "idle"
    assert status_for(now - timedelta(seconds=601), now=now) == "offline"
