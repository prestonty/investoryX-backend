"""add simulator tables

Revision ID: 3b9e4a1e2f8b
Revises: cd42a415ef5a
Create Date: 2026-01-25 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3b9e4a1e2f8b"
down_revision: Union[str, Sequence[str], None] = "cd42a415ef5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "simulators",
        sa.Column("simulator_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("starting_cash", sa.Numeric(12, 2), nullable=False),
        sa.Column("cash_balance", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("simulator_id"),
    )

    op.create_table(
        "simulator_tracked_stocks",
        sa.Column("tracked_id", sa.Integer(), nullable=False),
        sa.Column("simulator_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("target_allocation", sa.Numeric(5, 2), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="TRUE"),
        sa.ForeignKeyConstraint(
            ["simulator_id"],
            ["simulators.simulator_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tracked_id"),
        sa.UniqueConstraint(
            "simulator_id",
            "ticker",
            name="uq_simulator_tracked_stock_ticker",
        ),
    )
    op.create_index(
        "ix_simulator_tracked_stock_simulator_id",
        "simulator_tracked_stocks",
        ["simulator_id"],
        unique=False,
    )

    op.create_table(
        "simulator_positions",
        sa.Column("position_id", sa.Integer(), nullable=False),
        sa.Column("simulator_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("shares", sa.Numeric(14, 6), nullable=False),
        sa.Column("avg_cost", sa.Numeric(12, 4), nullable=False),
        sa.ForeignKeyConstraint(
            ["simulator_id"],
            ["simulators.simulator_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("position_id"),
        sa.UniqueConstraint(
            "simulator_id",
            "ticker",
            name="uq_simulator_position_ticker",
        ),
    )
    op.create_index(
        "ix_simulator_position_simulator_id",
        "simulator_positions",
        ["simulator_id"],
        unique=False,
    )

    op.create_table(
        "simulator_trades",
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("simulator_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("price", sa.Numeric(12, 4), nullable=False),
        sa.Column("shares", sa.Numeric(14, 6), nullable=False),
        sa.Column("fee", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column(
            "executed_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["simulator_id"],
            ["simulators.simulator_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("trade_id"),
    )
    op.create_index(
        "ix_simulator_trade_simulator_id",
        "simulator_trades",
        ["simulator_id"],
        unique=False,
    )

    op.create_table(
        "simulator_cash_ledger",
        sa.Column("ledger_id", sa.Integer(), nullable=False),
        sa.Column("simulator_id", sa.Integer(), nullable=False),
        sa.Column("delta", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("balance_after", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["simulator_id"],
            ["simulators.simulator_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ledger_id"),
    )
    op.create_index(
        "ix_simulator_cash_ledger_simulator_id",
        "simulator_cash_ledger",
        ["simulator_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_simulator_cash_ledger_simulator_id",
        table_name="simulator_cash_ledger",
    )
    op.drop_table("simulator_cash_ledger")

    op.drop_index("ix_simulator_trade_simulator_id", table_name="simulator_trades")
    op.drop_table("simulator_trades")

    op.drop_index(
        "ix_simulator_position_simulator_id",
        table_name="simulator_positions",
    )
    op.drop_table("simulator_positions")

    op.drop_index(
        "ix_simulator_tracked_stock_simulator_id",
        table_name="simulator_tracked_stocks",
    )
    op.drop_table("simulator_tracked_stocks")

    op.drop_table("simulators")
