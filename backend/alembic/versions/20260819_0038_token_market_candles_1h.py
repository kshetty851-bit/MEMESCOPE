"""token_market_candles_1h

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-19 13:08:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0038'
down_revision = '0037_real_wallet_devnet_exec'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        'token_market_candles_1h',
        sa.Column('mint_address', sa.String(length=44), nullable=False),
        sa.Column('bucket', sa.DateTime(timezone=True), nullable=False),
        sa.Column('open_price', sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column('high_price', sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column('low_price', sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column('close_price', sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column('close_market_cap', sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column('close_liquidity_usd', sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column('volume', sa.Numeric(precision=24, scale=4), nullable=True),
        sa.PrimaryKeyConstraint('mint_address', 'bucket')
    )
    op.create_index(
        'ix_candles_1h_mint_bucket_desc',
        'token_market_candles_1h',
        ['mint_address', sa.text('bucket DESC')],
        unique=False
    )

def downgrade() -> None:
    op.drop_index('ix_candles_1h_mint_bucket_desc', table_name='token_market_candles_1h')
    op.drop_table('token_market_candles_1h')
