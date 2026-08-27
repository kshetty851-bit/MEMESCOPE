"""The funding checklist must never be able to authorise anything, and must
never report an unmeasured precondition as satisfied.

Its only job is to say what is left. A report that can be talked into READY is
worse than no report, because it would be believed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.real_wallet import funding_readiness as fr
from app.real_wallet.funding_readiness import Owner, Status


def test_the_default_deployment_is_not_ready_for_anything():
    r = fr.evaluate()
    assert r.ready_to_fund is False
    assert r.ready_to_trade is False
    assert r.blocked, "a wallet with no key configured cannot be ready"


def test_every_check_names_an_owner_and_a_remediation():
    for c in fr.evaluate().checks:
        assert c.owner in Owner
        assert c.title and c.detail and c.remediation, c.key
        # A blocker a reader cannot act on is a blocker they will ignore.
        assert len(c.remediation) > 20, c.key


def test_unmeasured_facts_are_unknown_and_never_pass():
    r = fr.evaluate(wallet_balance_sol=None, network_verified=None,
                    kill_switch_active=None)
    for key in ("wallet_funded", "network_verified", "kill_switch_clear"):
        check = next(c for c in r.checks if c.key == key)
        assert check.status is Status.UNKNOWN
        assert check.status is not Status.PASS
    assert r.ready_to_fund is False


def test_an_armed_kill_switch_blocks_rather_than_unknowns():
    r = fr.evaluate(kill_switch_active=True)
    check = next(c for c in r.checks if c.key == "kill_switch_clear")
    assert check.status is Status.BLOCKED


def test_a_balance_below_the_fee_reserve_is_blocked(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "REAL_WALLET_MIN_SOL_FEE_RESERVE", Decimal("0.01"))
    low = fr.evaluate(wallet_balance_sol=Decimal("0.001"))
    assert next(c for c in low.checks if c.key == "wallet_funded").status is Status.BLOCKED
    ok = fr.evaluate(wallet_balance_sol=Decimal("0.05"))
    assert next(c for c in ok.checks if c.key == "wallet_funded").status is Status.PASS


def test_the_release_switch_is_owned_by_code_not_by_configuration():
    """An operator with environment access alone must not be able to reach
    mainnet — the switch is a constant so enabling it is a reviewable diff."""
    check = next(c for c in fr.evaluate().checks if c.key == "release_approved")
    assert check.owner is Owner.CODE
    assert check.status is Status.PASS
    from app.real_wallet.transport_policy import LIVE_TRANSPORT_RELEASE_APPROVED

    assert LIVE_TRANSPORT_RELEASE_APPROVED is True


def test_a_missing_strategy_is_an_evidence_blocker_no_code_can_close():
    check = next(c for c in fr.evaluate().checks if c.key == "validated_strategy")
    assert check.owner is Owner.EVIDENCE
    assert check.status is Status.BLOCKED
    assert "30-day" in check.remediation or "closed trades" in check.remediation


def test_naming_a_strategy_alone_never_makes_it_ready_to_trade():
    r = fr.evaluate(validated_strategy="V6-06")
    assert next(c for c in r.checks
                if c.key == "validated_strategy").status is Status.PASS
    assert r.ready_to_trade is False, (
        "evidence is necessary and never sufficient — the rail still has to be "
        "configured and the release still has to be reviewed"
    )


def test_ready_to_fund_asks_only_what_receiving_sol_requires(monkeypatch):
    """The bug this pins: a wallet funded correctly on mainnet reported
    `ready_to_fund: False` because the flag also demanded a SIGNER — which is
    about spending, not receiving. Funding needs an address and the right chain.
    """
    from decimal import Decimal

    from app.core.config import settings

    monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY",
                        "7WctMGpqz1tGkYStBBjJRMnmuh9uwJubYV2tL4pLwRr9")
    monkeypatch.setattr(settings, "REAL_WALLET_NETWORK", "mainnet")

    r = fr.evaluate(wallet_balance_sol=Decimal("0.05"), network_verified=True,
                    kill_switch_active=False)
    assert r.ready_to_fund is True, "no signer is needed to RECEIVE SOL"
    # And the things that gate SPENDING are all still blocking.
    assert r.ready_to_trade is False
    blocked = {c.key for c in r.blocked}
    assert "signer_holds_pinned_key" in blocked
    assert "validated_strategy" in blocked


def test_ready_to_fund_is_false_without_an_address_or_a_proven_chain(monkeypatch):
    from decimal import Decimal

    from app.core.config import settings

    monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY", "")
    assert fr.evaluate(network_verified=True).ready_to_fund is False

    monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY",
                        "7WctMGpqz1tGkYStBBjJRMnmuh9uwJubYV2tL4pLwRr9")
    monkeypatch.setattr(settings, "REAL_WALLET_NETWORK", "mainnet")
    # An unverified chain is not a chain you should be sending real SOL to.
    assert fr.evaluate(network_verified=None,
                       wallet_balance_sol=Decimal("0.05")).ready_to_fund is False
    assert fr.evaluate(network_verified=False,
                       wallet_balance_sol=Decimal("0.05")).ready_to_fund is False


def test_the_module_performs_no_io_and_holds_no_signer():
    import ast
    from pathlib import Path

    src = Path(fr.__file__).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(("httpx", "solana", "app.db")), node.module
    # Checked on the parse tree, not on the text: remediation prose legitimately
    # says the words "keypair" and "secret", and advice about key handling must
    # not fail a test about key handling.
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for banned in ("sign", "sign_message", "submit", "execute", "send"):
        assert banned not in calls, f"readiness must not call {banned}()"
    assigned = {
        t.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
    }
    assert not {"keypair", "secret", "private_key"} & assigned


@pytest.mark.parametrize("owner", list(Owner))
def test_every_owner_bucket_is_reachable(owner):
    r = fr.evaluate()
    buckets = {o: r.by_owner(o) for o in Owner}
    assert sum(len(v) for v in buckets.values()) == len(r.blocked)
    assert isinstance(buckets[owner], tuple)


def test_the_signer_check_is_measured_over_the_socket_not_read_from_config():
    """This container is deliberately denied any key path, so asking its own
    environment whether a key is mounted can only ever answer 'no'. That is what
    it did: a permanently BLOCKED item no operator action could clear, because
    clearing it would mean handing an application container a key path.

    Unreachable is UNKNOWN, not failure — nothing here is misconfigured when the
    signer is simply down.
    """
    unmeasured = {c.key: c for c in fr.evaluate().checks}["signer_holds_pinned_key"]
    assert unmeasured.status is fr.Status.UNKNOWN

    holds = {c.key: c for c in fr.evaluate(signer_holds_pinned_key=True).checks}
    assert holds["signer_holds_pinned_key"].status is fr.Status.PASS

    wrong = {c.key: c for c in fr.evaluate(signer_holds_pinned_key=False).checks}
    assert wrong["signer_holds_pinned_key"].status is fr.Status.BLOCKED


def test_no_readiness_check_reads_a_key_path_from_this_container():
    """The isolation guarantee, pinned where it would be broken: readiness must
    never learn about the key from settings."""
    import ast
    from pathlib import Path

    src = Path(fr.__file__).read_text()
    names = {
        n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)
    }
    assert "REAL_WALLET_EXECUTION_SECRET_FILE" not in names
    assert "MAINNET_SIGNER_FILE" not in names


def test_the_mainnet_clause_is_measured_not_restated():
    """This check hardcoded `REAL_WALLET_NETWORK != "mainnet"`, which DESCRIBED
    the phase gate rather than measuring it.

    So when the clause was reviewed and removed, the report went on naming a
    blocker that no longer existed — and an operator reading it would have
    believed mainnet was still code-blocked when it was not. A readiness check
    that cannot notice the thing it reports on is worse than no check, because
    it is trusted.
    """
    import ast
    from pathlib import Path

    from app.real_wallet import transport_policy

    src = Path(fr.__file__).read_text()
    tree = ast.parse(src)
    assigns = [
        ast.unparse(n) for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and "mainnet_clause_engaged" in ast.unparse(n)
    ]
    assert assigns, "the clause is not measured anywhere"
    assert "transport_readiness()" in assigns[0], "it is inferred, not asked"

    # And the answer tracks the policy, whichever way the policy points.
    engaged = (
        transport_policy.TransportReason.MAINNET_EXECUTION_DISABLED
        in transport_policy.readiness().reasons
    )
    check = {c.key: c for c in fr.evaluate().checks}["mainnet_execution_permitted"]
    assert (check.status is Status.BLOCKED) == engaged
