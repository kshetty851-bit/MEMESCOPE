

def test_the_withdrawal_address_is_protected():
    """Where the money can go is the most security-critical value in the system.

    A deployment that changed `REAL_WALLET_WITHDRAWAL_ADDRESS` would redirect
    every withdrawal, and until it was listed here nothing in the platform would
    have noticed — not the signer, which checks the value it is given, and not
    HQ, which was not looking at it.
    """
    from app.hq_ops import invariants

    assert "REAL_WALLET_WITHDRAWAL_ADDRESS" in invariants.PROTECTED_SETTINGS
    assert "REAL_WALLET_PUBLIC_KEY" in invariants.PROTECTED_SETTINGS
    assert "REAL_WALLET_WITHDRAWAL_ADDRESS" in invariants.capture()["values"]


def test_a_changed_withdrawal_address_is_detected(monkeypatch):
    """The whole point: it must be visible that it moved, and to what."""
    from app.core.config import settings
    from app.hq_ops import invariants

    monkeypatch.setattr(settings, "REAL_WALLET_WITHDRAWAL_ADDRESS", "AAAA")
    before = invariants.capture()
    monkeypatch.setattr(settings, "REAL_WALLET_WITHDRAWAL_ADDRESS", "BBBB")
    after = invariants.capture()

    assert before["digest"] != after["digest"]
    verdict = invariants.compare(before, after)
    assert verdict["held"] is False
    moved = verdict["changed"]["REAL_WALLET_WITHDRAWAL_ADDRESS"]
    # Naming the value AND both sides is the difference between "an invariant
    # broke" and a sentence somebody can act on.
    assert moved == {"before": "AAAA", "after": "BBBB"}


def test_the_lab_spec_is_fingerprinted():
    """The Lab's own SPEC_HASH check protects the RECORD — it halts scoring when
    rules drift. This protects the OPERATOR: it reports that they moved, in the
    same place every other protected value is reported.

    A deliberate change bumps SPEC_VERSION alongside the hash; seeing both move
    together is what makes an accidental change obvious.
    """
    from app.lab import spec
    from app.hq_ops import invariants

    lab = invariants.capture()["values"]["_lab"]
    assert lab["spec_hash"] == spec.SPEC_HASH
    assert lab["spec_version"] == spec.SPEC_VERSION
    assert lab["strategies"] == len(spec.STRATEGIES)


def test_an_unreadable_protected_value_is_not_reported_as_unchanged():
    """"Unreadable" differs from whatever it was before — a guard that reports a
    failure to read as "no change" is a guard that stops guarding silently."""
    import ast
    from pathlib import Path

    from app.hq_ops import invariants

    src = Path(invariants.__file__).read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "capture")
    body = ast.unparse(fn)
    assert body.count("<unreadable:") >= 3, "each block must mark its own failure"
