"""The lab's DexScreener reads carry paid promotion for the Boost Lab."""

from datetime import UTC, datetime

from app.labs.graduation import config
from app.labs.graduation.postgrad import parse_pair

TS = datetime(2026, 10, 10, 10, 0, tzinfo=UTC)


def pair(**extra):
    return {"chainId": config.NETWORK, "baseToken": {"address": "MINT"}, "pairAddress": "POOL",
            "dexId": "pumpswap", "priceNative": "0.0001", **extra}


def test_profile_and_boosts_are_read():
    row = parse_pair(pair(info={"imageUrl": "x"}, boosts={"active": 20}), ts=TS)
    assert row["has_profile"] is True and row["boosts_active"] == 20


def test_absent_or_junk_is_null_not_false():
    row = parse_pair(pair(), ts=TS)
    assert row["has_profile"] is None and row["boosts_active"] is None
    row = parse_pair(pair(info={}, boosts={"active": 0}), ts=TS)
    assert row["has_profile"] is None and row["boosts_active"] is None
    assert parse_pair(pair(boosts="junk"), ts=TS)["boosts_active"] is None
