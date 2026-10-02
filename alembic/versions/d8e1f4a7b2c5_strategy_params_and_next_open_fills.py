"""add simulators.strategy_params, drop simulators.price_mode

strategy_params stores each simulator's strategy tunables (windows, trade size,
thresholds...). price_mode is gone because every fill, live or backtest, now
happens at the next trading day's open after the signal's close.

Revision ID: d8e1f4a7b2c5
Revises: c3e5a7b9d1f2
Create Date: 2026-10-02 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d8e1f4a7b2c5"
down_revision: Union[str, Sequence[str], None] = "c3e5a7b9d1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "simulators",
        sa.Column("strategy_params", sa.JSON(), nullable=True),
    )
    op.drop_constraint("ck_simulators_price_mode_values", "simulators", type_="check")
    op.drop_column("simulators", "price_mode")


def downgrade() -> None:
    op.add_column(
        "simulators",
        sa.Column("price_mode", sa.String(), nullable=False, server_default="close"),
    )
    op.create_check_constraint(
        "ck_simulators_price_mode_values",
        "simulators",
        "price_mode IN ('open', 'close')",
    )
    op.drop_column("simulators", "strategy_params")
