"""add simulator_signals

Revision ID: 9d31b7c4e2aa
Revises: 423650f7fa82
Create Date: 2026-02-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9d31b7c4e2aa"
down_revision: Union[str, Sequence[str], None] = "423650f7fa82"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "simulator_signals",
        sa.Column("signal_id", sa.Integer(), nullable=False),
        sa.Column("simulator_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 6), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("executed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("execution_error", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["simulator_id"],
            ["simulators.simulator_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("signal_id"),
    )
    op.create_index(
        "ix_simulator_signal_simulator_id",
        "simulator_signals",
        ["simulator_id"],
        unique=False,
    )
    op.create_index(
        "ix_simulator_signal_status_created_at",
        "simulator_signals",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_simulator_signal_status_created_at",
        table_name="simulator_signals",
    )
    op.drop_index("ix_simulator_signal_simulator_id", table_name="simulator_signals")
    op.drop_table("simulator_signals")
