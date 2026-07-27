"""Unit tests for password hashing and JWT handling."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)

pytestmark = pytest.mark.unit


def test_password_round_trip() -> None:
    hashed = hash_password("CorrectHorse123!")
    assert hashed != "CorrectHorse123!"
    assert verify_password("CorrectHorse123!", hashed)
    assert not verify_password("wrong-password", hashed)


def test_password_hashes_are_salted() -> None:
    assert hash_password("same-input-123") != hash_password("same-input-123")


def test_password_longer_than_bcrypt_limit_is_supported() -> None:
    long_password = "a" * 200 + "1"
    hashed = hash_password(long_password)
    assert verify_password(long_password, hashed)
    # A different long password must not collide after pre-hashing.
    assert not verify_password("b" * 200 + "1", hashed)


def test_verify_password_rejects_malformed_hash() -> None:
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_access_token_round_trip() -> None:
    subject = uuid.uuid4()
    token, issued = create_access_token(subject, scopes=["user"])
    decoded = decode_access_token(token)

    assert decoded.subject == str(subject)
    assert decoded.token_type == "access"
    assert decoded.jti == issued.jti
    assert decoded.scopes == ("user",)


def test_expired_access_token_is_rejected() -> None:
    token, _ = create_access_token(uuid.uuid4(), expires_delta=timedelta(seconds=-10))
    with pytest.raises(AuthenticationError) as exc:
        decode_access_token(token)
    assert exc.value.code == "token_expired"


def test_tampered_access_token_is_rejected() -> None:
    token, _ = create_access_token(uuid.uuid4())
    with pytest.raises(AuthenticationError) as exc:
        decode_access_token(token + "x")
    assert exc.value.code == "token_invalid"


def test_refresh_token_digest_matches() -> None:
    plaintext, digest, expires_at = create_refresh_token()
    assert hash_refresh_token(plaintext) == digest
    assert len(digest) == 64
    assert expires_at.tzinfo is not None
