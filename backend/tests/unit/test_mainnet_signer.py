"""The mainnet signer holds the key. Everything about it is adversarial.

Three properties, and losing any one of them loses the wallet:
  * it proves the chain BEFORE it says anything about the key;
  * it never returns a secret, and cannot produce a signature at all;
  * an application container can never read the key path it uses.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.real_wallet import mainnet_signer as ms
from app.real_wallet.mainnet_signer_client import UnixMainnetSignerClient

pytestmark = pytest.mark.unit


def test_it_refuses_to_sign_by_name_not_by_omission():
    """A missing branch reads as an oversight; a named refusal reads as a
    decision, and tells the next person why."""
    assert ms.SIGN_REFUSAL == "mainnet_signing_not_implemented"
    src = Path(ms.__file__).read_text()
    tree = ast.parse(src)
    called = {
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "sign_message" not in called
    assert "sign" not in called


async def test_sign_is_refused_over_the_wire(monkeypatch):
    captured: dict = {}

    class _Writer:
        def write(self, payload): captured["body"] = json.loads(payload)
        async def drain(self): ...
        def close(self): ...
        async def wait_closed(self): ...

    class _Reader:
        async def readline(self): return b'{"op":"sign","intent_id":"x"}\n'

    await ms._handle_connection(_Reader(), _Writer())
    assert captured["body"]["ok"] is False
    assert captured["body"]["error"] == ms.SIGN_REFUSAL


async def test_an_unsupported_operation_is_refused():
    captured: dict = {}

    class _Writer:
        def write(self, payload): captured["body"] = json.loads(payload)
        async def drain(self): ...
        def close(self): ...
        async def wait_closed(self): ...

    class _Reader:
        async def readline(self): return b'{"op":"exfiltrate"}\n'

    await ms._handle_connection(_Reader(), _Writer())
    assert captured["body"]["ok"] is False
    assert captured["body"]["error"] == "unsupported_signer_operation"


async def test_it_refuses_to_run_anywhere_but_mainnet(monkeypatch):
    monkeypatch.setattr(settings, "REAL_WALLET_NETWORK", "devnet")
    with pytest.raises(ms.MainnetSignerError, match="requires_mainnet"):
        await ms._verified_chain()


def test_a_group_or_world_readable_key_is_refused(tmp_path, monkeypatch):
    key = tmp_path / "k.json"
    key.write_text("[]")
    monkeypatch.setenv("MAINNET_SIGNER_FILE", str(key))
    key.chmod(0o644)
    with pytest.raises(ms.MainnetSignerError, match="permissions"):
        ms._secret_file()
    key.chmod(0o600)
    assert ms._secret_file() == key


def test_an_unset_key_path_refuses_rather_than_defaulting(monkeypatch):
    monkeypatch.delenv("MAINNET_SIGNER_FILE", raising=False)
    with pytest.raises(ms.MainnetSignerError, match="not_configured"):
        ms._secret_file()


def test_the_key_path_is_never_read_from_settings():
    """Only the service's own environment names the key. If this were a setting,
    every application container would carry it."""
    src = Path(ms.__file__).read_text()
    assert "MAINNET_SIGNER_FILE" in src
    assert "settings.MAINNET_SIGNER_FILE" not in src


def test_the_client_sends_no_secret_and_receives_no_signature():
    """Checked on the parse tree. Prose about not carrying secrets must not be
    able to fail a test about not carrying secrets — a mistake made three times
    while writing this suite."""
    import app.real_wallet.mainnet_signer_client as client_mod

    tree = ast.parse(Path(client_mod.__file__).read_text())
    literals = {
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    # The only operation it can ask for.
    assert "identity" in literals
    assert "sign" not in literals
    # And it imports nothing that could produce or handle key material.
    imported: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
        elif isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
    assert not {"solders", "solders.keypair", "nacl"} & imported
    assert not any(m.startswith("app.real_wallet.signer") for m in imported)


async def test_the_client_refuses_when_no_socket_is_configured(monkeypatch):
    from app.real_wallet.mainnet_signer_client import MainnetSignerUnavailableError

    monkeypatch.setattr(settings, "MAINNET_SIGNER_SOCKET", "")
    with pytest.raises(MainnetSignerUnavailableError, match="not_configured"):
        await UnixMainnetSignerClient().identity()


def test_identity_returns_a_public_key_and_says_it_cannot_sign():
    """The response shape is the contract, read off the parse tree."""
    tree = ast.parse(Path(ms.__file__).read_text())
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "identity"
    )
    returned = next(n for n in ast.walk(fn) if isinstance(n, ast.Return))
    keys = {
        k.value for k in returned.value.keys
        if isinstance(k, ast.Constant)
    }
    assert {"public_key", "matches_pinned_key", "can_sign", "sign_refusal"} <= keys
    # `can_sign` is a hard False, not a computed value that could become True.
    can_sign = returned.value.values[list(keys).index("can_sign")] \
        if False else next(
            v for k, v in zip(returned.value.keys, returned.value.values)
            if isinstance(k, ast.Constant) and k.value == "can_sign"
        )
    assert isinstance(can_sign, ast.Constant) and can_sign.value is False


# --- deployment isolation ----------------------------------------------------
# The architecture's guarantee is that exactly one container can name the key.
# That lives in compose, not in Python, so it is checked where it is stated.

def _compose() -> dict:
    """Parse the compose file. Checked on the parsed document, not on its text:
    a COMMENT naming the variable is harmless, an env key is not — and matching
    text cannot tell them apart. (It failed exactly that way once.)"""
    import yaml

    path = Path(__file__).resolve().parents[3] / "docker-compose.yml"
    return yaml.safe_load(path.read_text())


def test_only_the_signer_service_names_the_key_file():
    """If an application container ever gained MAINNET_SIGNER_FILE, key material
    would be one misconfiguration away from the API. One service, ever."""
    doc = _compose()
    holders = [
        name
        for name, svc in doc["services"].items()
        if "MAINNET_SIGNER_FILE" in (svc.get("environment") or {})
    ]
    assert holders == ["mainnet-signer"]


def test_the_backend_anchor_hands_out_a_socket_never_a_key():
    doc = _compose()
    for name, svc in doc["services"].items():
        env = svc.get("environment") or {}
        if name == "mainnet-signer":
            continue
        assert "MAINNET_SIGNER_FILE" not in env, name
    api = doc["services"]["backend"]["environment"]
    assert "MAINNET_SIGNER_SOCKET" in api


def test_the_signer_is_opt_in_and_fails_closed_on_its_key_path():
    svc = _compose()["services"]["mainnet-signer"]
    assert svc["profiles"] == ["mainnet-signer"]
    mounts = [m for m in svc["volumes"] if "mainnet-signer.json" in m]
    assert len(mounts) == 1
    mount = mounts[0]
    # An unselected profile must not be able to pick up an accidental key.
    assert "MAINNET_SIGNER_FILE_HOST:-/run/memescope-mainnet-signer-missing" in mount
    assert mount.endswith(":ro"), "the key must be mounted read-only"


def test_no_application_container_mounts_the_key():
    doc = _compose()
    for name, svc in doc["services"].items():
        if name == "mainnet-signer":
            continue
        for mount in svc.get("volumes") or []:
            assert "mainnet-signer.json" not in str(mount), name
