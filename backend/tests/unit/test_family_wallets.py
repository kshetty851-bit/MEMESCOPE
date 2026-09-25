"""The family members' own wallets: who owns which key, and what the signer
will do with it (stage 1 — withdrawals to Karthik's address, nothing else).

These run the real signer functions against throwaway keys written to a temp
directory, so they check behaviour, not the source's wording.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from solders.keypair import Keypair

from app.core.config import settings
from app.real_wallet import family_wallets
from app.real_wallet import mainnet_signer as ms
from app.real_wallet.devnet_transaction import (
    NativeTransferSpec,
    build_unsigned_native_transfer,
)

pytestmark = pytest.mark.unit

BLOCKHASH = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"


def _key(path: Path, keypair: Keypair) -> None:
    path.write_text(json.dumps(list(bytes(keypair))))
    os.chmod(path, 0o600)


@pytest.fixture
def keys(tmp_path, monkeypatch):
    """Owner, Karthik's withdrawal address, and two family wallets on disk."""
    owner, karthik, jaya, asha = Keypair(), Keypair(), Keypair(), Keypair()
    _key(tmp_path / "owner.json", owner)
    family = tmp_path / "family"
    family.mkdir()
    _key(family / "jaya.json", jaya)
    _key(family / "asha.json", asha)
    monkeypatch.setenv("MAINNET_SIGNER_FILE", str(tmp_path / "owner.json"))
    monkeypatch.setenv("FAMILY_SIGNER_DIR", str(family))
    monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY", str(owner.pubkey()))
    monkeypatch.setattr(settings, "REAL_WALLET_WITHDRAWAL_ADDRESS", str(karthik.pubkey()))
    monkeypatch.setattr(settings, "REAL_WALLET_FAMILY_WALLETS",
                        f"jaya={jaya.pubkey()},Asha={asha.pubkey()}")

    async def chain() -> str:
        return "genesis"

    monkeypatch.setattr(ms, "_verified_chain", chain)
    return SimpleNamespace(owner=owner, karthik=karthik, jaya=jaya, asha=asha, family=family)


# --- the map --------------------------------------------------------------------

def test_the_map_names_members_by_their_own_keys(keys):
    assert family_wallets.pinned() == {"JAYA": str(keys.jaya.pubkey()),
                                       "ASHA": str(keys.asha.pubkey())}
    assert family_wallets.address("jaya") == str(keys.jaya.pubkey())
    assert family_wallets.address("APOORVA") is None
    assert family_wallets.member_for(str(keys.asha.pubkey())) == "ASHA"
    assert family_wallets.member_for(str(keys.owner.pubkey())) is None


@pytest.mark.parametrize("raw, why", [
    ("bob={a}", "unknown_family_member"),
    ("jaya={a},jaya={b}", "family_member_listed_twice"),
    ("jaya=not-a-key", "invalid_family_wallet"),
    ("jaya={owner}", "family_wallet_collides"),
    ("jaya={karthik}", "family_wallet_collides"),
    ("jaya={a},asha={a}", "family_wallet_shared"),
    ("jaya", "unknown_family_member"),
])
def test_a_map_a_signer_could_misread_is_refused_whole(raw, why):
    a, b, owner, karthik = (str(Keypair().pubkey()) for _ in range(4))
    with pytest.raises(family_wallets.FamilyWalletConfigError, match=why):
        family_wallets.parse(raw.format(a=a, b=b, owner=owner, karthik=karthik),
                             owner=owner, withdrawal=karthik)


def test_an_empty_map_means_no_family_wallets():
    assert family_wallets.parse("", owner="x", withdrawal="y") == {}


def test_a_bad_map_gives_nobody_an_address(monkeypatch):
    monkeypatch.setattr(settings, "REAL_WALLET_FAMILY_WALLETS", "jaya=nonsense")
    assert family_wallets.address("JAYA") is None


# --- the signer -----------------------------------------------------------------

def test_each_wallet_loads_its_own_key(keys):
    for kp in (keys.owner, keys.jaya, keys.asha):
        assert ms._signer_for(str(kp.pubkey())).public_key == str(kp.pubkey())


def test_a_wallet_nobody_pinned_is_refused_before_any_file_is_read(keys):
    with pytest.raises(ms.MainnetSignerError, match="wallet_is_not_pinned"):
        ms._signer_for(str(Keypair().pubkey()))


def test_key_files_swapped_between_members_sign_nothing(keys):
    _key(keys.family / "jaya.json", keys.asha)  # Asha's key in Jaya's file
    from app.real_wallet.signer import ExecutionWalletPublicKeyMismatchError

    with pytest.raises(ExecutionWalletPublicKeyMismatchError):
        ms._signer_for(str(keys.jaya.pubkey()))


def test_a_readable_family_key_is_refused(keys):
    os.chmod(keys.family / "jaya.json", 0o644)
    with pytest.raises(ms.MainnetSignerError, match="permissions"):
        ms._signer_for(str(keys.jaya.pubkey()))


def test_a_misconfigured_map_stops_the_family_path(keys, monkeypatch):
    monkeypatch.setattr(settings, "REAL_WALLET_FAMILY_WALLETS", "jaya=nonsense")
    with pytest.raises(ms.MainnetSignerError, match="family_wallets_misconfigured"):
        ms._signer_for(str(keys.jaya.pubkey()))
    # ...and the owner's own wallet is untouched by it.
    assert ms._signer_for(str(keys.owner.pubkey())).public_key == str(keys.owner.pubkey())


def _transfer(payer: Keypair, to: str, lamports: int = 1_000_000) -> str:
    return build_unsigned_native_transfer(
        spec=NativeTransferSpec(fee_payer=str(payer.pubkey()), destination=to,
                                lamports=lamports),
        blockhash=BLOCKHASH)


async def test_a_family_wallet_can_withdraw_to_karthik(keys):
    out = await ms.sign_withdrawal(
        _transfer(keys.jaya, str(keys.karthik.pubkey())), wallet=str(keys.jaya.pubkey()))
    assert out["destination"] == str(keys.karthik.pubkey())
    assert out["lamports"] == 1_000_000


async def test_a_family_wallet_cannot_withdraw_anywhere_else(keys):
    thief = str(Keypair().pubkey())
    with pytest.raises(ms.MainnetSignerError, match="withdrawal_rejected"):
        await ms.sign_withdrawal(_transfer(keys.jaya, thief), wallet=str(keys.jaya.pubkey()))


async def test_one_members_key_cannot_pay_from_another_members_wallet(keys):
    # Bytes paid by Asha, presented as Jaya's withdrawal.
    with pytest.raises(ms.MainnetSignerError, match="withdrawal_rejected"):
        await ms.sign_withdrawal(_transfer(keys.asha, str(keys.karthik.pubkey())),
                                 wallet=str(keys.jaya.pubkey()))


async def test_the_owners_withdrawal_is_unchanged(keys):
    out = await ms.sign_withdrawal(_transfer(keys.owner, str(keys.karthik.pubkey())))
    assert out["destination"] == str(keys.karthik.pubkey())


def _fake_intent_store(monkeypatch, intent):
    class Repo:
        def __init__(self, _session):
            pass

        async def by_id(self, _id):
            return intent

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(ms, "LiveIntentRepository", Repo)
    monkeypatch.setattr(ms, "SessionFactory", Session)


async def test_a_family_wallet_may_sign_its_own_trade(keys, monkeypatch):
    """Stage 2: a trade intent naming Jaya's wallet passes the wallet check and
    goes on to the checks every trade faces (here: no order was built yet)."""
    from app.real_wallet.live_readiness import ExecutionState

    intent = SimpleNamespace(id=uuid.uuid4(), state=ExecutionState.ORDER_CREATED,
                             wallet_public_key=str(keys.jaya.pubkey()), order_evidence={})
    _fake_intent_store(monkeypatch, intent)
    with pytest.raises(ms.MainnetSignerError, match="intent_has_no_unsigned_transaction"):
        await ms.sign_intent(intent.id)


async def test_a_trade_for_a_wallet_nobody_pinned_is_refused(keys, monkeypatch):
    from app.real_wallet.live_readiness import ExecutionState

    intent = SimpleNamespace(id=uuid.uuid4(), state=ExecutionState.ORDER_CREATED,
                             wallet_public_key=str(Keypair().pubkey()), order_evidence={})
    _fake_intent_store(monkeypatch, intent)
    with pytest.raises(ms.MainnetSignerError, match="intent_wallet_is_not_this_signer"):
        await ms.sign_intent(intent.id)


def _close(wallet: Keypair) -> str:
    from app.real_wallet import account_close

    token_account = str(Keypair().pubkey())
    return account_close.build(
        wallet=str(wallet.pubkey()), blockhash=BLOCKHASH,
        accounts=[(token_account, "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")])


async def test_a_family_wallet_closes_only_its_own_accounts(keys):
    out = await ms.sign_close_accounts(_close(keys.jaya), wallet=str(keys.jaya.pubkey()))
    assert out["signature"]
    # Jaya's close presented as Asha's: the rent would not go to Asha.
    with pytest.raises(ms.MainnetSignerError, match="close_rejected"):
        await ms.sign_close_accounts(_close(keys.jaya), wallet=str(keys.asha.pubkey()))


async def test_identity_family_reports_each_member(keys):
    os.remove(keys.family / "asha.json")
    out = (await ms.identity_family())["family"]
    assert out["JAYA"] == {"public_key": str(keys.jaya.pubkey()), "matches_pinned_key": True}
    assert out["ASHA"]["matches_pinned_key"] is False
    assert "unavailable" in out["ASHA"]["error"]


# --- where the keys may live ----------------------------------------------------

def _compose() -> dict:
    import yaml

    path = Path(__file__).resolve().parents[3] / "docker-compose.yml"
    return yaml.safe_load(path.read_text())


def test_only_the_signer_mounts_or_names_the_family_keys():
    for name, svc in _compose()["services"].items():
        env = svc.get("environment") or {}
        mounts = [str(m) for m in svc.get("volumes") or [] if "/run/secrets/family" in str(m)]
        if name == "mainnet-signer":
            assert env.get("FAMILY_SIGNER_DIR") == "/run/secrets/family"
            assert len(mounts) == 1 and mounts[0].endswith(":ro")
            assert "FAMILY_SIGNER_DIR_HOST:-/run/memescope-family-signer-missing" in mounts[0]
        else:
            assert "FAMILY_SIGNER_DIR" not in env, name
            assert not mounts, name


def test_every_service_reads_the_same_public_map():
    assert "REAL_WALLET_FAMILY_WALLETS" in _compose()["services"]["backend"]["environment"]


# --- the family page's endpoints ------------------------------------------------

async def test_a_withdrawal_needs_the_members_own_password(keys):
    from fastapi import HTTPException

    from app.real_wallet import family_api

    body = family_api.WithdrawIn(sol_amount="0.1", confirmation_phrase="WITHDRAW_TO_KARTHIK")
    with pytest.raises(HTTPException) as refused:
        await family_api.member_withdraw("jaya", body, x_family_token=None)
    assert refused.value.status_code == 401


async def test_a_member_without_a_wallet_cannot_withdraw(keys, monkeypatch):
    from fastapi import HTTPException

    from app.real_wallet import family, family_api

    token, _ = family.issue_token("APOORVA")
    body = family_api.WithdrawIn(sol_amount="0.1", confirmation_phrase="WITHDRAW_TO_KARTHIK")
    with pytest.raises(HTTPException) as refused:
        await family_api.member_withdraw("apoorva", body, x_family_token=token)
    assert refused.value.status_code == 404


def test_the_withdrawal_names_no_destination():
    from app.real_wallet import family_api

    assert set(family_api.WithdrawIn.model_fields) == {"sol_amount", "confirmation_phrase"}


async def test_a_member_without_a_wallet_shows_none(keys):
    from app.real_wallet import family_api

    assert await family_api._own_wallet("APOORVA") == {"address": None}
