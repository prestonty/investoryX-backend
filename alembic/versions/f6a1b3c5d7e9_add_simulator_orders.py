"""add simulator_orders

Manual market orders placed while the market is closed wait in this table and
fill at the next trading day's open. Orders placed during market hours fill
immediately and only create a trade.

Revision ID: f6a1b3c5d7e9
Revises: e4b8c2a6f1d3
Create Date: 2026-10-06 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a1b3c5d7e9"
down_revision: Union[str, Sequence[str], None] = "e4b8c2a6f1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "simulator_orders",
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("simulator_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("shares", sa.Numeric(14, 6), nullable=False),
        sa.Column("quote_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("fill_day", sa.Date(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("trade_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["simulator_id"], ["simulators.simulator_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"], ["simulator_trades.trade_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("order_id"),
    )
    op.create_index(
        "ix_simulator_order_simulator_id", "simulator_orders", ["simulator_id"]
    )
    op.create_index(
        "ix_simulator_order_status_fill_day", "simulator_orders", ["status", "fill_day"]
    )


def downgrade() -> None:
    op.drop_index("ix_simulator_order_status_fill_day", table_name="simulator_orders")
    op.drop_index("ix_simulator_order_simulator_id", table_name="simulator_orders")
    op.drop_table("simulator_orders")
