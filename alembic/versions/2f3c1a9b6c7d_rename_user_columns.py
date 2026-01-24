"""Rename user columns to snake_case

Revision ID: 2f3c1a9b6c7d
Revises: 46bae94b9254
Create Date: 2026-01-12 09:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "2f3c1a9b6c7d"
down_revision: Union[str, Sequence[str], None] = "46bae94b9254"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("users", "UserId", new_column_name="user_id")
    op.alter_column("users", "Name", new_column_name="name")


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("users", "user_id", new_column_name="UserId")
    op.alter_column("users", "name", new_column_name="Name")
