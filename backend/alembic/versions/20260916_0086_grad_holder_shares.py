"""Holder concentration on grad_tokens, read once at graduation.

`grad_checkpoints` already carried `top10_holder_share` and it sat empty for
months: its only source was a metered trade stream the lab stopped buying, and
a 0 there was indistinguishable from "never asked". These columns are nullable
and carry `holders_checked_at` so the difference is on the row.

Placed on `grad_tokens` rather than on a position, because concentration is a
property of the MINT at its graduation — five arms buying the same token would
otherwise each pay for the same RPC read and store five copies of one fact.

Revision ID: 0086_grad_holder_shares
Revises: 0085_forex_lab
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0086_grad_holder_shares"
down_revision: str = "0085_forex_lab"
branch_labels: None = None
depends_on: None = None

_TABLE = "grad_tokens"
_COLUMNS = (
    ("top1_holder_share", sa.Numeric(9, 6)),
    ("top10_holder_share", sa.Numeric(9, 6)),
    ("top_holder_address", sa.String(64)),
    ("holders_seen", sa.Integer()),
    ("holders_checked_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column(_TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column(_TABLE, name)
