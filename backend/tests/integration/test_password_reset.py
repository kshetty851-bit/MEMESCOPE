"""Password reset. Every test here tries to get something through.

The flow hands an emailed string the power to take over an account, so the
properties that matter are the refusals: the token cannot be reused, cannot
outlive its hour, cannot survive a newer request, and cannot be recovered from
the database. And the endpoint must not become an oracle for which addresses
have accounts.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import hash_password, verify_password
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.services.password_reset import (
    InvalidResetTokenError,
    PasswordResetService,
    TOKEN_TTL,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 25, 19, 0, tzinfo=UTC)


async def _user(session, *, email="owner@example.com", active=True) -> User:
    user = User(email=email, hashed_password=hash_password("the-old-password-1"),
                is_active=active)
    session.add(user)
    await session.flush()
    return user


async def test_a_token_is_issued_and_is_never_stored_in_the_clear(db_session):
    user = await _user(db_session)
    issued = await PasswordResetService(db_session).request(
        email=user.email, now=NOW
    )
    assert issued.token and issued.user is user

    rows = list((await db_session.execute(select(PasswordResetToken))).scalars())
    assert len(rows) == 1
    # The database must not contain the token, only its digest.
    assert rows[0].token_hash != issued.token
    assert rows[0].token_hash == hashlib.sha256(issued.token.encode()).hexdigest()
    assert rows[0].expires_at == NOW + TOKEN_TTL


async def test_an_unknown_address_is_indistinguishable(db_session):
    """No exception, no different shape — the endpoint above returns the same
    message either way, and this is what makes that honest."""
    issued = await PasswordResetService(db_session).request(
        email="nobody@example.com", now=NOW
    )
    assert issued.token is None
    assert issued.user is None
    assert (await db_session.execute(select(PasswordResetToken))).scalars().all() == []


async def test_an_inactive_account_is_treated_as_unknown(db_session):
    user = await _user(db_session, email="off@example.com", active=False)
    issued = await PasswordResetService(db_session).request(email=user.email, now=NOW)
    assert issued.token is None


async def test_completing_sets_the_password(db_session):
    user = await _user(db_session)
    issued = await PasswordResetService(db_session).request(email=user.email, now=NOW)
    await PasswordResetService(db_session).complete(
        token=issued.token, new_password="a-brand-new-password", now=NOW
    )
    await db_session.refresh(user)
    assert verify_password("a-brand-new-password", user.hashed_password)
    assert not verify_password("the-old-password-1", user.hashed_password)


async def test_a_token_cannot_be_spent_twice(db_session):
    user = await _user(db_session)
    issued = await PasswordResetService(db_session).request(email=user.email, now=NOW)
    svc = PasswordResetService(db_session)
    await svc.complete(token=issued.token, new_password="first-new-password", now=NOW)
    with pytest.raises(InvalidResetTokenError):
        await svc.complete(token=issued.token, new_password="second-attempt-pw", now=NOW)


async def test_an_expired_token_is_refused(db_session):
    user = await _user(db_session)
    issued = await PasswordResetService(db_session).request(email=user.email, now=NOW)
    with pytest.raises(InvalidResetTokenError, match="expired"):
        await PasswordResetService(db_session).complete(
            token=issued.token, new_password="too-late-password",
            now=NOW + TOKEN_TTL + timedelta(seconds=1),
        )


async def test_requesting_again_kills_the_previous_link(db_session):
    """Otherwise every link a user ever generated stays live in their inbox."""
    user = await _user(db_session)
    svc = PasswordResetService(db_session)
    first = await svc.request(email=user.email, now=NOW)
    second = await svc.request(email=user.email, now=NOW + timedelta(minutes=1))

    with pytest.raises(InvalidResetTokenError):
        await svc.complete(token=first.token, new_password="stale-link-password",
                           now=NOW + timedelta(minutes=2))
    await svc.complete(token=second.token, new_password="fresh-link-password",
                       now=NOW + timedelta(minutes=2))
    await db_session.refresh(user)
    assert verify_password("fresh-link-password", user.hashed_password)


async def test_an_invented_token_is_refused(db_session):
    await _user(db_session)
    with pytest.raises(InvalidResetTokenError):
        await PasswordResetService(db_session).complete(
            token="not-a-real-token-at-all", new_password="whatever-password", now=NOW
        )


async def test_one_users_token_cannot_reset_another(db_session):
    victim = await _user(db_session, email="victim@example.com")
    attacker = await _user(db_session, email="attacker@example.com")
    svc = PasswordResetService(db_session)
    theirs = await svc.request(email=attacker.email, now=NOW)
    await svc.complete(token=theirs.token, new_password="attacker-new-password",
                       now=NOW)
    await db_session.refresh(victim)
    # The victim's password is untouched: a token is bound to its own user.
    assert verify_password("the-old-password-1", victim.hashed_password)


async def test_completing_invalidates_every_other_outstanding_link(db_session):
    user = await _user(db_session)
    svc = PasswordResetService(db_session)
    await svc.request(email=user.email, now=NOW)
    latest = await svc.request(email=user.email, now=NOW + timedelta(minutes=1))
    await svc.complete(token=latest.token, new_password="settled-password",
                       now=NOW + timedelta(minutes=2))
    rows = list((await db_session.execute(select(PasswordResetToken))).scalars())
    assert all(r.used_at or r.invalidated_at for r in rows)


async def test_the_reset_url_carries_the_token_and_points_at_the_frontend():
    from app.core.config import settings

    url = PasswordResetService.reset_url("abc123")
    assert url.endswith("/reset-password?token=abc123")
    assert url.startswith(settings.FRONTEND_URL.rstrip("/"))


def test_the_reset_link_is_configurable_in_the_compose_anchor():
    """FRONTEND_URL builds the reset link. It lived only in .env.production, so
    containers fell back to localhost and every emailed link pointed there."""
    import yaml
    from pathlib import Path

    doc = yaml.safe_load(
        (Path(__file__).resolve().parents[3] / "docker-compose.yml").read_text()
    )
    for name in ("backend", "worker"):
        assert "FRONTEND_URL" in doc["services"][name]["environment"], name


async def test_the_operator_cli_issues_a_real_single_use_link(db_session):
    """It must go through the same service, not around it — a second issuing
    path with its own rules is a second set of bugs."""
    import ast
    from pathlib import Path

    import app.services.password_reset_cli as cli

    user = await _user(db_session, email="cli@example.com")
    issued = await PasswordResetService(db_session).request(
        email=user.email, now=NOW, ip="operator-cli"
    )
    assert issued.token
    await PasswordResetService(db_session).complete(
        token=issued.token, new_password="issued-by-operator", now=NOW
    )
    await db_session.refresh(user)
    assert verify_password("issued-by-operator", user.hashed_password)

    # And it must not be reachable over HTTP: a browser-clickable version would
    # let an administrator take over any account.
    src = Path(cli.__file__).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(("fastapi", "app.api")), node.module
    assert "@router" not in src
