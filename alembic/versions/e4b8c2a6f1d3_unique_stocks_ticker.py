"""make stocks.ticker unique

The daily listing sync skips tickers that already exist; the unique index
guarantees an overlapping seed and sync can never insert the same ticker twice.

Revision ID: e4b8c2a6f1d3
Revises: d8e1f4a7b2c5
Create Date: 2026-10-06 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e4b8c2a6f1d3"
down_revision: Union[str, Sequence[str], None] = "d8e1f4a7b2c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Duplicates aren't deleted automatically: watchlists cascade-delete with
    # their stock, so removing a row could silently drop users' data.
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT ticker FROM stocks GROUP BY ticker HAVING COUNT(*) > 1 LIMIT 20"
            )
        )
        .scalars()
        .all()
    )
    if duplicates:
        raise RuntimeError(
            f"Duplicate tickers in stocks; resolve them before upgrading: {duplicates}"
        )

    op.drop_index("ix_stocks_ticker", table_name="stocks")
    op.create_index("ix_stocks_ticker", "stocks", ["ticker"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_stocks_ticker", table_name="stocks")
    op.create_index("ix_stocks_ticker", "stocks", ["ticker"])
