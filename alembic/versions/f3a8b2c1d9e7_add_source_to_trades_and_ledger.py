"""add source to simulator_trades and simulator_cash_ledger

Revision ID: f3a8b2c1d9e7
Revises: 9d31b7c4e2aa
Create Date: 2026-04-10 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f3a8b2c1d9e7"
down_revision: Union[str, Sequence[str], None] = "a1f3c2d4e5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "simulator_trades",
        sa.Column("source", sa.String(), nullable=True, server_default="live"),
    )
    op.add_column(
        "simulator_cash_ledger",
        sa.Column("source", sa.String(), nullable=True, server_default="live"),
    )


def downgrade() -> None:
    op.drop_column("simulator_trades", "source")
    op.drop_column("simulator_cash_ledger", "source")
