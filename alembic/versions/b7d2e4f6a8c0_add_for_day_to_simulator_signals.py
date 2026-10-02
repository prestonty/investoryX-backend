"""add for_day to simulator_signals

Records which trading day's prices a signal was evaluated on. The unique
constraint makes "evaluate a simulator once per trading day" enforceable by the
database, so concurrent runs can't create duplicate signals (and trades).
Existing rows keep NULL, which the constraint ignores.

Revision ID: b7d2e4f6a8c0
Revises: e9c4d1f2a3b8
Create Date: 2026-10-01 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7d2e4f6a8c0"
down_revision: Union[str, Sequence[str], None] = "e9c4d1f2a3b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "simulator_signals",
        sa.Column("for_day", sa.Date(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_simulator_signal_day_ticker",
        "simulator_signals",
        ["simulator_id", "for_day", "ticker"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_simulator_signal_day_ticker", "simulator_signals", type_="unique")
    op.drop_column("simulator_signals", "for_day")
