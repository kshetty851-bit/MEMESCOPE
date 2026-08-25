"""One authoritative answer to: what stands between here and a funded canary?

The execution rail is complete and fail-closed — `LiveSubmissionGuard` alone
names twenty-one conditions — but that is a list of refusals, not a plan. An
operator reading it cannot tell which refusals are waiting on a code change,
which on their own hands, and which on evidence that does not exist yet. This
module answers exactly that, and nothing else.

**It can never enable anything.** Every function here is a read. It holds no
signer, builds no transaction, performs no write, and returning `READY` is a
statement about preconditions, not permission — the guard and the transport
policy remain the only authorities on whether a submission may happen.

Each check names its OWNER, because the three kinds of blocker have completely
different resolutions:

  CODE      a reviewed diff. Cannot be resolved by editing an environment.
  OPERATOR  a human action — a key, a funded wallet, a configuration decision.
  EVIDENCE  a result the tournament has not produced yet. No amount of
            engineering closes one of these, which is the point of listing them
            beside the others rather than leaving them implicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from urllib.parse import urlparse

from app.core.config import settings
from app.real_wallet.policy import configured_entry_size_usd
from app.real_wallet.transport_policy import (
    ALLOWED_EXECUTE_HOSTS,
    LIVE_TRANSPORT_RELEASE_APPROVED,
)


class Owner(StrEnum):
    CODE = "CODE"
    OPERATOR = "OPERATOR"
    EVIDENCE = "EVIDENCE"


class Status(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Check:
    key: str
    title: str
    owner: Owner
    status: Status
    detail: str
    remediation: str


@dataclass(frozen=True, slots=True)
class FundingReadiness:
    ready_to_fund: bool
    ready_to_trade: bool
    checks: tuple[Check, ...]

    @property
    def blocked(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.status is not Status.PASS)

    def by_owner(self, owner: Owner) -> tuple[Check, ...]:
        return tuple(c for c in self.blocked if c.owner is owner)


def _check(key, title, owner, ok, detail, remediation, *, unknown=False) -> Check:
    status = Status.UNKNOWN if unknown else (Status.PASS if ok else Status.BLOCKED)
    return Check(key=key, title=title, owner=owner, status=status,
                 detail=detail, remediation=remediation)


def evaluate(
    *,
    wallet_balance_sol: Decimal | None = None,
    network_verified: bool | None = None,
    kill_switch_active: bool | None = None,
    validated_strategy: str | None = None,
) -> FundingReadiness:
    """Assess every precondition. Facts the caller could not measure pass as
    `None` and are reported UNKNOWN — never as satisfied."""
    public_key = settings.REAL_WALLET_PUBLIC_KEY.strip()
    secret_file = settings.REAL_WALLET_EXECUTION_SECRET_FILE.strip()
    entry_size = configured_entry_size_usd()
    execute_host = (urlparse(settings.JUPITER_V2_BASE_URL).hostname or "").lower() \
        if getattr(settings, "JUPITER_V2_BASE_URL", "") else ""
    fee_reserve = settings.REAL_WALLET_MIN_SOL_FEE_RESERVE

    checks: list[Check] = [
        # --- OPERATOR: the wallet itself ------------------------------------
        _check(
            "wallet_configured", "A dedicated execution wallet exists",
            Owner.OPERATOR, bool(public_key),
            f"REAL_WALLET_PUBLIC_KEY={public_key or '(unset)'}",
            "Generate a dedicated wallet (app/real_wallet/generate_wallet.py), "
            "then set REAL_WALLET_PUBLIC_KEY. Use a fresh keypair that has never "
            "held anything else.",
        ),
        _check(
            "signer_secret_configured", "The signer secret is mounted",
            Owner.OPERATOR, bool(secret_file),
            f"REAL_WALLET_EXECUTION_SECRET_FILE={secret_file or '(unset)'}",
            "Mount the keypair file read-only (0600, never tracked in git) and "
            "point REAL_WALLET_EXECUTION_SECRET_FILE at it. Claude must not "
            "handle the key material.",
        ),
        _check(
            "network_is_mainnet", "The wallet is pointed at mainnet",
            Owner.OPERATOR, settings.REAL_WALLET_NETWORK == "mainnet",
            f"REAL_WALLET_NETWORK={settings.REAL_WALLET_NETWORK}",
            "Set REAL_WALLET_NETWORK=mainnet and REAL_WALLET_RPC_URL to a mainnet "
            "endpoint. Devnet proves the rail; it cannot prove the market.",
        ),
        _check(
            "network_verified", "The RPC endpoint's genesis hash matches",
            Owner.OPERATOR, bool(network_verified),
            "verified" if network_verified else
            ("unverified" if network_verified is False else "not measured"),
            "The wallet reader verifies genesis before showing chain state. An "
            "unverified endpoint is refused rather than trusted.",
            unknown=network_verified is None,
        ),
        _check(
            "wallet_funded", "The wallet holds enough SOL for fees",
            Owner.OPERATOR,
            wallet_balance_sol is not None and wallet_balance_sol >= fee_reserve,
            (f"balance {wallet_balance_sol} SOL vs reserve {fee_reserve} SOL"
             if wallet_balance_sol is not None else "balance not readable"),
            f"Fund the wallet with at least {fee_reserve} SOL for fees, and keep it "
            f"under the {settings.REAL_WALLET_MAX_BALANCE_SOL} SOL ceiling the canary "
            "policy enforces. Funding is an operator action.",
            unknown=wallet_balance_sol is None,
        ),
        _check(
            "entry_size_configured", "An entry size has been decided",
            Owner.OPERATOR, entry_size is not None,
            f"REAL_WALLET_ENTRY_SIZE_USD={settings.REAL_WALLET_ENTRY_SIZE_USD} "
            f"({'set' if entry_size else 'unconfigured — refuses'})",
            "Set REAL_WALLET_ENTRY_SIZE_USD deliberately. Zero means nobody has "
            "decided, and unconfigured refuses on purpose so no fallback ships.",
        ),
        _check(
            "kill_switch_clear", "The kill switch is not armed",
            Owner.OPERATOR, kill_switch_active is False,
            "clear" if kill_switch_active is False else
            ("ARMED" if kill_switch_active else "not measured"),
            "Clear it through the audited endpoint once the cause is understood.",
            unknown=kill_switch_active is None,
        ),
        # --- OPERATOR: the three enable flags -------------------------------
        _check(
            "mode_live", "Execution mode is live",
            Owner.OPERATOR, settings.REAL_WALLET_EXECUTION_MODE == "live",
            f"REAL_WALLET_EXECUTION_MODE={settings.REAL_WALLET_EXECUTION_MODE}",
            "Modes run disabled -> dry_run -> armed -> live. `armed` rehearses the "
            "whole chain with submission still impossible; do that before live.",
        ),
        _check(
            "execution_enabled", "Execution is enabled",
            Owner.OPERATOR, settings.REAL_WALLET_EXECUTION_ENABLED,
            f"REAL_WALLET_EXECUTION_ENABLED={settings.REAL_WALLET_EXECUTION_ENABLED}",
            "Set REAL_WALLET_EXECUTION_ENABLED=true. One of three independent "
            "flags; none is sufficient alone.",
        ),
        _check(
            "autotrade_enabled", "Autotrade is enabled",
            Owner.OPERATOR, settings.REAL_WALLET_AUTOTRADE_ENABLED,
            f"REAL_WALLET_AUTOTRADE_ENABLED={settings.REAL_WALLET_AUTOTRADE_ENABLED}",
            "Set REAL_WALLET_AUTOTRADE_ENABLED=true only when a strategy is "
            "actually meant to act without a human per trade.",
        ),
        # --- CODE: the reviewed release -------------------------------------
        _check(
            "execute_host_allowlisted", "The execute host is allowlisted",
            Owner.CODE, execute_host in ALLOWED_EXECUTE_HOSTS,
            f"host={execute_host or '(unset)'} allowlist={sorted(ALLOWED_EXECUTE_HOSTS)}",
            "A signed transaction is bearer-grade material and must not be "
            "postable to an arbitrary configured host.",
        ),
        _check(
            "release_approved", "The reviewed release switch is on",
            Owner.CODE, LIVE_TRANSPORT_RELEASE_APPROVED,
            f"LIVE_TRANSPORT_RELEASE_APPROVED={LIVE_TRANSPORT_RELEASE_APPROVED}",
            "This is a module constant, not a setting: enabling mainnet execution "
            "is a reviewable diff that `git log -S` can find. It is the LAST step, "
            "and it requires a focused security review plus a real submission "
            "transport — the installed one refuses by construction.",
        ),
        # --- EVIDENCE: what the wallet would even trade ----------------------
        _check(
            "validated_strategy", "A strategy has earned real money",
            Owner.EVIDENCE, bool(validated_strategy),
            validated_strategy or
            "none promoted — seven NO-EDGE verdicts; V6 is running forward",
            "The V6 tournament's 30-day review (protocol §13a) is the gate: >=100 "
            "closed trades, beats CASH and RANDOM, survives -best-1 and -best-3, "
            "top-3 trades under 80% of gross profit. No engineering closes this "
            "one — only forward evidence does.",
        ),
    ]

    ordered = tuple(checks)
    operator_and_code = tuple(
        c for c in ordered if c.owner in (Owner.OPERATOR, Owner.CODE)
    )
    return FundingReadiness(
        # Funding the wallet needs the rail configured — not the release, and
        # not a validated strategy. A funded wallet that cannot submit is a
        # perfectly safe intermediate state, and it is the next real milestone.
        ready_to_fund=all(
            c.status is Status.PASS
            for c in ordered
            if c.key in ("wallet_configured", "signer_secret_configured",
                         "network_is_mainnet", "network_verified")
        ),
        # Trading needs everything, evidence included.
        ready_to_trade=all(c.status is Status.PASS for c in ordered),
        checks=ordered,
    )


def as_dict(readiness: FundingReadiness) -> dict:
    return {
        "ready_to_fund": readiness.ready_to_fund,
        "ready_to_trade": readiness.ready_to_trade,
        "blocked_total": len(readiness.blocked),
        "blocked_by_owner": {
            owner.value: [c.key for c in readiness.by_owner(owner)]
            for owner in Owner
        },
        "checks": [
            {"key": c.key, "title": c.title, "owner": c.owner.value,
             "status": c.status.value, "detail": c.detail,
             "remediation": c.remediation}
            for c in readiness.checks
        ],
    }
