"""rename simulation tables to simulator tables

Revision ID: 5a1c8e9f2d3b
Revises: 3b9e4a1e2f8b
Create Date: 2026-01-25 18:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5a1c8e9f2d3b"
down_revision: Union[str, Sequence[str], None] = "3b9e4a1e2f8b"
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

    op.execute(
        """
        INSERT INTO simulators (
            simulator_id,
            name,
            starting_cash,
            cash_balance,
            created_at,
            updated_at
        )
        SELECT
            simulation_id,
            name,
            starting_cash,
            cash_balance,
            created_at,
            updated_at
        FROM simulations
        """
    )

    op.execute(
        """
        INSERT INTO simulator_tracked_stocks (
            tracked_id,
            simulator_id,
            ticker,
            target_allocation,
            enabled
        )
        SELECT
            tracked_id,
            simulation_id,
            ticker,
            target_allocation,
            enabled
        FROM tracked_stocks
        """
    )

    op.execute(
        """
        INSERT INTO simulator_positions (
            position_id,
            simulator_id,
            ticker,
            shares,
            avg_cost
        )
        SELECT
            position_id,
            simulation_id,
            ticker,
            shares,
            avg_cost
        FROM positions
        """
    )

    op.execute(
        """
        INSERT INTO simulator_trades (
            trade_id,
            simulator_id,
            ticker,
            side,
            price,
            shares,
            fee,
            executed_at
        )
        SELECT
            trade_id,
            simulation_id,
            ticker,
            side,
            price,
            shares,
            fee,
            executed_at
        FROM trades
        """
    )

    op.execute(
        """
        INSERT INTO simulator_cash_ledger (
            ledger_id,
            simulator_id,
            delta,
            reason,
            balance_after,
            created_at
        )
        SELECT
            ledger_id,
            simulation_id,
            delta,
            reason,
            balance_after,
            created_at
        FROM cash_ledger
        """
    )

    op.drop_table("cash_ledger")
    op.drop_table("trades")
    op.drop_table("positions")
    op.drop_table("tracked_stocks")
    op.drop_table("simulations")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "simulations",
        sa.Column("simulation_id", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("simulation_id"),
    )

    op.create_table(
        "tracked_stocks",
        sa.Column("tracked_id", sa.Integer(), nullable=False),
        sa.Column("simulation_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("target_allocation", sa.Numeric(5, 2), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="TRUE"),
        sa.ForeignKeyConstraint(
            ["simulation_id"],
            ["simulations.simulation_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tracked_id"),
        sa.UniqueConstraint(
            "simulation_id",
            "ticker",
            name="uq_tracked_stock_sim_ticker",
        ),
    )
    op.create_index(
        "ix_tracked_stock_simulation_id",
        "tracked_stocks",
        ["simulation_id"],
        unique=False,
    )

    op.create_table(
        "positions",
        sa.Column("position_id", sa.Integer(), nullable=False),
        sa.Column("simulation_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("shares", sa.Numeric(14, 6), nullable=False),
        sa.Column("avg_cost", sa.Numeric(12, 4), nullable=False),
        sa.ForeignKeyConstraint(
            ["simulation_id"],
            ["simulations.simulation_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("position_id"),
        sa.UniqueConstraint(
            "simulation_id",
            "ticker",
            name="uq_position_sim_ticker",
        ),
    )
    op.create_index(
        "ix_position_simulation_id",
        "positions",
        ["simulation_id"],
        unique=False,
    )

    op.create_table(
        "trades",
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("simulation_id", sa.Integer(), nullable=False),
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
            ["simulation_id"],
            ["simulations.simulation_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("trade_id"),
    )
    op.create_index(
        "ix_trade_simulation_id",
        "trades",
        ["simulation_id"],
        unique=False,
    )

    op.create_table(
        "cash_ledger",
        sa.Column("ledger_id", sa.Integer(), nullable=False),
        sa.Column("simulation_id", sa.Integer(), nullable=False),
        sa.Column("delta", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("balance_after", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["simulation_id"],
            ["simulations.simulation_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ledger_id"),
    )
    op.create_index(
        "ix_cash_ledger_simulation_id",
        "cash_ledger",
        ["simulation_id"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO simulations (
            simulation_id,
            name,
            starting_cash,
            cash_balance,
            created_at,
            updated_at
        )
        SELECT
            simulator_id,
            name,
            starting_cash,
            cash_balance,
            created_at,
            updated_at
        FROM simulators
        """
    )

    op.execute(
        """
        INSERT INTO tracked_stocks (
            tracked_id,
            simulation_id,
            ticker,
            target_allocation,
            enabled
        )
        SELECT
            tracked_id,
            simulator_id,
            ticker,
            target_allocation,
            enabled
        FROM simulator_tracked_stocks
        """
    )

    op.execute(
        """
        INSERT INTO positions (
            position_id,
            simulation_id,
            ticker,
            shares,
            avg_cost
        )
        SELECT
            position_id,
            simulator_id,
            ticker,
            shares,
            avg_cost
        FROM simulator_positions
        """
    )

    op.execute(
        """
        INSERT INTO trades (
            trade_id,
            simulation_id,
            ticker,
            side,
            price,
            shares,
            fee,
            executed_at
        )
        SELECT
            trade_id,
            simulator_id,
            ticker,
            side,
            price,
            shares,
            fee,
            executed_at
        FROM simulator_trades
        """
    )

    op.execute(
        """
        INSERT INTO cash_ledger (
            ledger_id,
            simulation_id,
            delta,
            reason,
            balance_after,
            created_at
        )
        SELECT
            ledger_id,
            simulator_id,
            delta,
            reason,
            balance_after,
            created_at
        FROM simulator_cash_ledger
        """
    )

    op.drop_table("simulator_cash_ledger")
    op.drop_table("simulator_trades")
    op.drop_table("simulator_positions")
    op.drop_table("simulator_tracked_stocks")
    op.drop_table("simulators")
