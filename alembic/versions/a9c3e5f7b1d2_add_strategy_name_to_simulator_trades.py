"""add strategy_name to simulator_trades

Records which strategy decided each trade. Existing manual trades are marked
"manual", and existing live trades take the strategy of the signal they filled
(a live fill stamps the trade and its signal with the same executed_at).
Backtest trades and live trades with no matching signal stay NULL.

Revision ID: a9c3e5f7b1d2
Revises: f6a1b3c5d7e9
Create Date: 2026-10-06 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a9c3e5f7b1d2"
down_revision: Union[str, Sequence[str], None] = "f6a1b3c5d7e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "simulator_trades",
        sa.Column("strategy_name", sa.String(), nullable=True),
    )
    op.execute(
        "UPDATE simulator_trades SET strategy_name = 'manual' WHERE source = 'manual'"
    )
    op.execute(
        """
        UPDATE simulator_trades AS t
        SET strategy_name = s.strategy_name
        FROM simulator_signals AS s
        WHERE t.source = 'live'
          AND s.status = 'executed'
          AND s.simulator_id = t.simulator_id
          AND UPPER(TRIM(s.ticker)) = t.ticker
          AND LOWER(s.action) = t.side
          AND s.executed_at = t.executed_at
        """
    )


def downgrade() -> None:
    op.drop_column("simulator_trades", "strategy_name")
