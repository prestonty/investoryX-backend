"""add strategy_name to simulators

Revision ID: a1f3c2d4e5b6
Revises: db0b831751b7
Create Date: 2026-04-09 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1f3c2d4e5b6'
down_revision: Union[str, Sequence[str], None] = 'db0b831751b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "simulators",
        sa.Column(
            "strategy_name",
            sa.String(),
            nullable=False,
            server_default="sma_crossover",
        ),
    )


def downgrade() -> None:
    op.drop_column("simulators", "strategy_name")
