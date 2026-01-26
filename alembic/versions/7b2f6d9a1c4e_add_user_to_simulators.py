"""add user_id to simulators

Revision ID: 7b2f6d9a1c4e
Revises: 5a1c8e9f2d3b
Create Date: 2026-01-25 18:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7b2f6d9a1c4e"
down_revision: Union[str, Sequence[str], None] = "5a1c8e9f2d3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "simulators",
        sa.Column("user_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_simulators_user_id",
        "simulators",
        ["user_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_simulators_user_id",
        "simulators",
        "users",
        ["user_id"],
        ["user_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_simulators_user_id", "simulators", type_="foreignkey")
    op.drop_index("ix_simulators_user_id", table_name="simulators")
    op.drop_column("simulators", "user_id")
