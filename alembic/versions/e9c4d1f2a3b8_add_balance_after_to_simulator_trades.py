"""add balance_after to simulator_trades

Revision ID: e9c4d1f2a3b8
Revises: f3a8b2c1d9e7
Create Date: 2026-04-10 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e9c4d1f2a3b8"
down_revision: Union[str, Sequence[str], None] = "f3a8b2c1d9e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "simulator_trades",
        sa.Column("balance_after", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("simulator_trades", "balance_after")
