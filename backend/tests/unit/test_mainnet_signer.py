"""The mainnet signer holds the key. Everything about it is adversarial.

Four properties, and losing any one of them loses the wallet:
  * it proves the chain BEFORE it says anything about the key;
  * it never returns a secret, only a public key and a signature;
  * it reloads and re-verifies every intent it signs, so a compromised caller
    can ask for a signature and still not choose what gets signed;
  * an application container can never read the key path it uses.
"""

from __future__ import annotations

import ast
import json
import stat
from pathlib import Path

import pytest

from app.core.config import settings
from app.real_wallet import mainnet_signer as ms
from app.real_wallet.mainnet_signer_client import UnixMainnetSignerClient

pytestmark = pytest.mark.unit


async def test_a_sign_request_without_an_intent_id_is_refused():
    """The caller may send exactly one thing: an id. Anything else is refused
    before a database or a key is touched."""
    captured: dict = {}

    class _Writer:
        def write(self, payload): captured["body"] = json.loads(payload)
        async def drain(self): ...
        def close(self): ...
        async def wait_closed(self): ...

    class _Reader:
        async def readline(self): return b'{"op":"sign"}\n'

    await ms._handle_connection(_Reader(), _Writer())
    assert captured["body"]["ok"] is False
    assert captured["body"]["error"] == "invalid_signer_request"


def test_signing_never_trusts_what_the_caller_sends():
    """Every value deciding WHAT gets signed is reloaded inside the signer, so
    a compromised caller can ask for a signature and still not choose it."""
    tree = ast.parse(Path(ms.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "sign_intent")
    assert [a.arg for a in fn.args.args] == ["intent_id"]
    called = {n.func.attr for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "by_id" in called                    # reloads the intent itself
    assert "intent_fingerprint" in called       # recomputes, never accepts
    assert "sign_jupiter_transaction" in called # signs through the re-verifier
    assert "sign_message" not in called         # never the raw key


def test_signing_is_legal_from_exactly_one_state_and_one_wallet():
    src = Path(ms.__file__).read_text()
    assert "ExecutionState.ORDER_CREATED" in src
    assert "intent_not_signable" in src
    assert "intent_wallet_is_not_this_signer" in src


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


def test_identity_returns_a_public_key_and_never_a_secret():
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
    assert {"public_key", "matches_pinned_key", "network", "genesis_hash"} <= keys
    # Identity must never return anything derived from the secret itself.
    assert not {"secret", "private_key", "keypair", "seed"} & keys


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


def test_identity_reads_public_key_as_a_property_not_a_method():
    """`FileExecutionSigner.public_key` is a @property. Calling it raised
    TypeError on the first real run against a mounted key — the rehearsal's
    whole purpose, and cheap to pin so it cannot come back."""
    import inspect

    from app.real_wallet.signer import FileExecutionSigner

    assert isinstance(
        inspect.getattr_static(FileExecutionSigner, "public_key"), property
    )
    src = Path(ms.__file__).read_text()
    assert "signer.public_key()" not in src
    assert "signer.public_key" in src


def test_the_socket_is_reachable_by_the_unprivileged_callers(tmp_path, monkeypatch):
    """The signer runs as root to read a 0600 key; every caller runs as the
    unprivileged app user. A root-owned 0660 socket is therefore unreachable —
    which is exactly how the rehearsal reported the signer down while it was
    healthy and answering. The group is the grant; 0666 would also work and is
    deliberately not what this does."""
    sock = tmp_path / "signer.sock"
    sock.touch()
    sock.chmod(0o600)

    chowned: list[tuple] = []
    monkeypatch.setattr(ms.grp, "getgrnam", lambda name: type("G", (), {"gr_gid": 4242})())
    monkeypatch.setattr(ms.os, "chown", lambda p, u, g: chowned.append((str(p), u, g)))

    ms._grant_socket_to_app_group(sock)

    assert chowned == [(str(sock), -1, 4242)]
    assert stat.S_IMODE(sock.stat().st_mode) == 0o660  # group, never world


def test_the_socket_grant_raises_rather_than_leaving_it_unreachable():
    """A signer nobody can reach is the silent failure the rehearsal exists to
    surface, so the grant must not be best-effort."""
    tree = ast.parse(Path(ms.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_grant_socket_to_app_group")
    assert not [n for n in ast.walk(fn) if isinstance(n, ast.Try)]


def test_every_image_stage_defines_the_account_the_socket_grant_needs():
    """The signer builds from `development`, which inherited no such account
    while it lived in `production` — so the grant raised KeyError on startup and
    the signer crash-looped. Defining it in `base` is what makes the name
    resolvable in both stages."""
    lines = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text().splitlines()
    stages = [i for i, ln in enumerate(lines) if ln.startswith("FROM ")]
    groupadd = [i for i, ln in enumerate(lines) if "groupadd" in ln]
    assert len(groupadd) == 1, "one account, defined once"
    # Before the second FROM means it is in `base`, which every stage descends from.
    assert groupadd[0] < stages[1]
    assert f"--gid 1001 {ms.APP_USER}" in lines[groupadd[0]]
