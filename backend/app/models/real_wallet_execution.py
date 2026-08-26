"""Append-only dry-run evidence, kept completely separate from Paper Wallet."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class RealWalletExecutionIntent(Base, UUIDPrimaryKeyMixin):
    """One immutable autonomous decision attempt; never a submitted trade."""

    __tablename__ = "real_wallet_execution_intents"

    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="BUY")
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    radar_rank: Mapped[int] = mapped_column(nullable=False)
    signal_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_usd: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    safety_evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_safety_evaluations.id")
    )
    safety_decision: Mapped[str | None] = mapped_column(String(8))
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    sell_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    round_trip_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    buy_order: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sell_order: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_real_wallet_execution_intent_key"),
        Index("ix_real_wallet_execution_intent_evaluated", "evaluated_at"),
        Index("ix_real_wallet_execution_intent_status", "status"),
    )


class RealWalletPosition(Base, UUIDPrimaryKeyMixin):
    """Confirmed-only real-position ledger, isolated from every Paper table."""

    __tablename__ = "real_wallet_positions"

    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # This nullable legacy link is retained only so an already-migrated dry-run
    # database remains readable. New confirmed positions must use
    # ``opened_live_intent_id``; dry-run code never writes this table.
    opened_intent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_execution_intents.id")
    )
    opened_live_intent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("real_wallet_live_intents.id"),
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    entry_price_usd: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # --- exit state -------------------------------------------------------
    # What the frozen V6 exits are written against. A trailing stop or a
    # break-even rule cannot be evaluated from entry price and quantity alone;
    # without these the position could be opened and never closed, which is
    # exactly what happened.
    peak_exec_multiple: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, server_default=text("1")
    )
    #: NULL disables the liquidity-collapse exit rather than firing it against a
    #: number nobody measured.
    entry_liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    last_exec_multiple: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    break_even_armed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    partial_done: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    #: When the executable multiple entered the stagnation band. NULL means "not
    #: flat", never "flat since forever".
    flat_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    banked_proceeds_usd: Mapped[Decimal] = mapped_column(
        Numeric(24, 4), nullable=False, server_default=text("0")
    )
    last_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wallet_public_key: Mapped[str | None] = mapped_column(String(44))
    strategy_id: Mapped[str | None] = mapped_column(String(64))
    strategy_version: Mapped[str | None] = mapped_column(String(32))
    entry_safety_evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_safety_evaluations.id")
    )
    entry_transaction_signature: Mapped[str | None] = mapped_column(String(128))
    entry_actual_input_amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    entry_actual_output_amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    entry_network_fee_lamports: Mapped[int | None] = mapped_column(BigInteger)
    exit_intent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_live_intents.id")
    )
    exit_transaction_signature: Mapped[str | None] = mapped_column(String(128))
    exit_actual_input_amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    exit_actual_output_amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    exit_network_fee_lamports: Mapped[int | None] = mapped_column(BigInteger)
    exit_reason: Mapped[str | None] = mapped_column(String(64))
    realised_gross_pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    #: **Net only when it is actually net.** Until this sprint this field was
    #: assigned the gross figure, because network fees are paid in SOL and no
    #: SOL/USD reading existed to convert them. A column named `net` holding
    #: gross is worse than a null: it reads as measured. It is now `None`
    #: whenever the fees could not be priced, with the reason beside it.
    realised_net_pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    net_pnl_unavailable_reason: Mapped[str | None] = mapped_column(Text)

    # --- Fee accounting, from a dated SOL/USD reading ------------------------
    # The price is stored with the figure it produced. A later price change must
    # not silently restate a settled result, and a reader must be able to see
    # which reading was used and how old it was.
    entry_network_fee_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    exit_network_fee_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    entry_sol_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    exit_sol_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    entry_sol_price_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_sol_price_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sol_price_source: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (
        UniqueConstraint("opened_live_intent_id", name="uq_real_position_opened_live_intent"),
        UniqueConstraint(
            "entry_transaction_signature", name="uq_real_position_entry_signature"
        ),
        UniqueConstraint("exit_transaction_signature", name="uq_real_position_exit_signature"),
        Index(
            "uq_real_wallet_open_position_mint",
            "mint_address",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
    )


class RealWalletLiveIntent(Base, UUIDPrimaryKeyMixin):
    """Future-real execution intent; separate from dry-run evidence and paper."""

    __tablename__ = "real_wallet_live_intents"

    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    wallet_public_key: Mapped[str] = mapped_column(String(44), nullable=False)
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("real_wallet_positions.id", use_alter=True),
    )
    safety_evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_safety_evaluations.id")
    )
    requested_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    requested_token_quantity: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    input_mint: Mapped[str | None] = mapped_column(String(44))
    output_mint: Mapped[str | None] = mapped_column(String(44))
    jupiter_request_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    order_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    order_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transaction_signature: Mapped[str | None] = mapped_column(String(128), unique=True)
    actual_input_amount_raw: Mapped[Decimal | None] = mapped_column(Numeric(38, 0))
    actual_input_decimals: Mapped[int | None] = mapped_column(Integer)
    actual_output_amount_raw: Mapped[Decimal | None] = mapped_column(Numeric(38, 0))
    actual_output_decimals: Mapped[int | None] = mapped_column(Integer)
    network_fee_lamports: Mapped[int | None] = mapped_column(BigInteger)
    failure_reason: Mapped[str | None] = mapped_column(String(128))

    # --- Authorised order shape, written at intent creation -----------------
    # The exact base units this order is permitted to spend, decided server-side
    # before Jupiter is asked for anything. `order_evidence.verify` compares the
    # returned order against these, which is the check the signer cannot make:
    # a compiled transaction does not reveal its mints or amounts.
    authorized_input_amount_raw: Mapped[Decimal | None] = mapped_column(Numeric(38, 0))
    authorized_input_decimals: Mapped[int | None] = mapped_column(Integer)
    #: `pending` | `approved` | `rejected`. An intent may only be signed while
    #: this reads `approved`.
    order_validation_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    #: Every reason the order failed its re-check, kept for the audit record.
    order_validation_reasons: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    #: What the order actually said, beside why it was accepted or refused.
    order_validation_observed: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    order_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_real_wallet_live_intent_state", "state"),
        Index("ix_real_wallet_live_intent_mint", "mint_address"),
    )


class RealWalletExecutionEvent(Base, UUIDPrimaryKeyMixin):
    """Append-only state-transition evidence for a live intent."""

    __tablename__ = "real_wallet_execution_events"

    intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_live_intents.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_real_wallet_execution_event_intent", "intent_id"),)


class RealWalletKillSwitch(Base, UUIDPrimaryKeyMixin):
    """Persisted fail-closed kill switches; never a browser control surface.

    A switch that can only ever be armed is a switch nobody can use twice: the
    first automatic arming would permanently end execution, so the pressure
    would be to clear it by hand in the database — untracked, unattributed, and
    exactly the change nobody would find afterwards. So clearing is a first
    class, attributed operation, and both halves of the history are kept.
    """

    __tablename__ = "real_wallet_kill_switches"

    kind: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    reason: Mapped[str | None] = mapped_column(String(256))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Who armed it. `None` means the system did, from a durable failure count.
    #: Named `actor` because the column already existed under that name in the
    #: deployed database; adding an `activated_by` beside it would have left two
    #: columns for one fact, which is worse than an imperfect name.
    actor: Mapped[str | None] = mapped_column(String(128))
    #: Clearing evidence. Retained after a re-arm so the row carries the whole
    #: sequence rather than only its current state.
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleared_by: Mapped[str | None] = mapped_column(String(128))
    cleared_reason: Mapped[str | None] = mapped_column(String(256))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RealWalletAutotradeSwitch(Base, UUIDPrimaryKeyMixin):
    """The operator's start/stop control for autonomous trading.

    Deliberately the mirror image of a kill switch. A kill switch is fail-closed
    and its *armed* state stops things; this is an intent and its *on* state
    stops nothing from being checked. Starting it authorises nothing: mode, the
    enable flags, the release constant, the mainnet clause, the submission guard,
    SEC-2 freshness, network verification and the canary limits are all evaluated
    independently and are untouched by it.

    What it does own is the other direction. **Stopping is unconditional and
    immediate**, because a control an operator cannot trust to stop is a control
    they will be afraid to start. The guard reads this switch as one more
    required condition, so `off` refuses regardless of what every other barrier
    says.

    `nominated_strategy` records WHICH strategy the operator intends to trade —
    a V6 Lab id. Recording it is not promoting it; nothing reads it as
    permission, and the evidence gate in the funding report is unmoved by it.
    """

    __tablename__ = "real_wallet_autotrade_switch"

    #: Singleton in practice; unique so a second row cannot disagree with it.
    scope: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, server_default="default"
    )
    enabled: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
    #: A V6 strategy id, e.g. "V6-06". Never a permission.
    nominated_strategy: Mapped[str | None] = mapped_column(String(16))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_by: Mapped[str | None] = mapped_column(String(128))
    start_reason: Mapped[str | None] = mapped_column(String(256))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_by: Mapped[str | None] = mapped_column(String(128))
    stop_reason: Mapped[str | None] = mapped_column(String(256))


class RealWalletAutotradeEvent(Base, UUIDPrimaryKeyMixin):
    """Append-only start/stop history. The switch row is state; this is evidence."""

    __tablename__ = "real_wallet_autotrade_events"

    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    #: `started` or `stopped`.
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(String(256))
    nominated_strategy: Mapped[str | None] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class RealWalletKillSwitchEvent(Base, UUIDPrimaryKeyMixin):
    """Append-only arm/clear history. The switch row is state; this is evidence."""

    __tablename__ = "real_wallet_kill_switch_events"

    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    #: `armed` or `cleared`.
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_real_wallet_kill_switch_event_kind", "kind"),)


class RealWalletExecutionHealth(Base, UUIDPrimaryKeyMixin):
    """One durable, secret-free execution-health counter per execution scope."""

    __tablename__ = "real_wallet_execution_health"

    scope: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    consecutive_failures: Mapped[int] = mapped_column(nullable=False, default=0)
    last_failure_reason: Mapped[str | None] = mapped_column(String(128))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RealWalletDevnetQuote(Base, UUIDPrimaryKeyMixin):
    """Append-only evidence from a read-only devnet quote request."""

    __tablename__ = "real_wallet_devnet_quotes"

    network: Mapped[str] = mapped_column(String(16), nullable=False, server_default="devnet")
    wallet_public_key: Mapped[str] = mapped_column(String(44), nullable=False)
    input_mint: Mapped[str] = mapped_column(String(44), nullable=False)
    output_mint: Mapped[str] = mapped_column(String(44), nullable=False)
    input_amount_raw: Mapped[Decimal] = mapped_column(Numeric(38, 0), nullable=False)
    expected_output_raw: Mapped[Decimal] = mapped_column(Numeric(38, 0), nullable=False)
    minimum_output_raw: Mapped[Decimal] = mapped_column(Numeric(38, 0), nullable=False)
    slippage_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    estimated_fee_lamports: Mapped[int | None] = mapped_column(BigInteger)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(256))
    route: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    quoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RealWalletDevnetIntent(Base, UUIDPrimaryKeyMixin):
    """Manual devnet-only transaction intent; never a Paper Wallet record."""

    __tablename__ = "real_wallet_devnet_intents"

    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    wallet_public_key: Mapped[str] = mapped_column(String(44), nullable=False)
    network: Mapped[str] = mapped_column(String(16), nullable=False, server_default="devnet")
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    input_mint: Mapped[str] = mapped_column(String(44), nullable=False)
    output_mint: Mapped[str | None] = mapped_column(String(44))
    destination_public_key: Mapped[str | None] = mapped_column(String(44))
    input_amount_raw: Mapped[Decimal] = mapped_column(Numeric(38, 0), nullable=False)
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_devnet_quotes.id")
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default="DRAFT")
    simulation_status: Mapped[str | None] = mapped_column(String(32))
    approval_status: Mapped[str | None] = mapped_column(String(32))
    signing_status: Mapped[str | None] = mapped_column(String(32))
    submission_status: Mapped[str | None] = mapped_column(String(32))
    quote_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transaction_base64: Mapped[str | None] = mapped_column(Text)
    transaction_fingerprint: Mapped[str | None] = mapped_column(String(64))
    transaction_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    simulation_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    simulation_logs: Mapped[list[str] | None] = mapped_column(JSONB)
    simulation_units_consumed: Mapped[int | None] = mapped_column(BigInteger)
    simulation_context_slot: Mapped[int | None] = mapped_column(BigInteger)
    simulation_blockhash: Mapped[str | None] = mapped_column(String(64))
    simulated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signer_validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    signed_transaction_base64: Mapped[str | None] = mapped_column(Text)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transaction_signature: Mapped[str | None] = mapped_column(String(128), unique=True)
    rpc_endpoint: Mapped[str | None] = mapped_column(String(512))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submission_retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    submission_error: Mapped[str | None] = mapped_column(Text)
    confirmation_status: Mapped[str | None] = mapped_column(String(32))
    confirmation_slot: Mapped[int | None] = mapped_column(BigInteger)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciliation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_real_wallet_devnet_intent_state", "state"),)


class RealWalletDevnetEvent(Base, UUIDPrimaryKeyMixin):
    """Immutable, secret-free lifecycle evidence for a devnet manual intent."""

    __tablename__ = "real_wallet_devnet_events"

    intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_devnet_intents.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_order: Mapped[int] = mapped_column(
        BigInteger,
        Sequence("real_wallet_devnet_event_order_seq"),
        nullable=False,
        server_default=Sequence("real_wallet_devnet_event_order_seq").next_value(),
    )
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_real_wallet_devnet_event_intent", "intent_id"),
        Index("ix_real_wallet_devnet_event_intent_order", "intent_id", "event_order"),
    )
