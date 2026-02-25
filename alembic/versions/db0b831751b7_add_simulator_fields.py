"""add simulator fields

Revision ID: db0b831751b7
Revises: 9d31b7c4e2aa
Create Date: 2026-02-18 04:05:43.389231

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db0b831751b7'
down_revision: Union[str, Sequence[str], None] = '9d31b7c4e2aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "simulators",
        sa.Column("status", sa.String(), nullable=False, server_default="Active Trading"),
    )
    op.add_column(
        "simulators",
        sa.Column("last_run_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "simulators",
        sa.Column("next_run_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "simulators",
        sa.Column("frequency", sa.String(), nullable=False, server_default="daily"),
    )
    op.add_column(
        "simulators",
        sa.Column("price_mode", sa.String(), nullable=False, server_default="close"),
    )
    op.add_column(
        "simulators",
        sa.Column("max_position_pct", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "simulators",
        sa.Column("max_daily_loss_pct", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "simulators",
        sa.Column("stopped_reason", sa.String(), nullable=True),
    )

    op.create_check_constraint(
        "ck_simulators_status_values",
        "simulators",
        "status IN ('Active Trading', 'Pause Trading')",
    )
    op.create_check_constraint(
        "ck_simulators_frequency_values",
        "simulators",
        "frequency IN ('daily', 'twice_daily')",
    )
    op.create_check_constraint(
        "ck_simulators_price_mode_values",
        "simulators",
        "price_mode IN ('open', 'close')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_simulators_price_mode_values", "simulators", type_="check")
    op.drop_constraint("ck_simulators_frequency_values", "simulators", type_="check")
    op.drop_constraint("ck_simulators_status_values", "simulators", type_="check")

    op.drop_column("simulators", "stopped_reason")
    op.drop_column("simulators", "max_daily_loss_pct")
    op.drop_column("simulators", "max_position_pct")
    op.drop_column("simulators", "price_mode")
    op.drop_column("simulators", "frequency")
    op.drop_column("simulators", "next_run_at")
    op.drop_column("simulators", "last_run_at")
    op.drop_column("simulators", "status")
