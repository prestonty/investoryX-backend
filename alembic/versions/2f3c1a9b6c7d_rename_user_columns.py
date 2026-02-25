"""Rename user columns to snake_case

Revision ID: 2f3c1a9b6c7d
Revises: 46bae94b9254
Create Date: 2026-01-12 09:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "2f3c1a9b6c7d"
down_revision: Union[str, Sequence[str], None] = "46bae94b9254"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    if _column_exists(bind, "users", "UserId") and not _column_exists(bind, "users", "user_id"):
        op.alter_column("users", "UserId", new_column_name="user_id")
    if _column_exists(bind, "users", "Name") and not _column_exists(bind, "users", "name"):
        op.alter_column("users", "Name", new_column_name="name")


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    if _column_exists(bind, "users", "user_id") and not _column_exists(bind, "users", "UserId"):
        op.alter_column("users", "user_id", new_column_name="UserId")
    if _column_exists(bind, "users", "name") and not _column_exists(bind, "users", "Name"):
        op.alter_column("users", "name", new_column_name="Name")


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    query = text(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = :table_name
          AND column_name = :column_name
        """
    )
    result = bind.execute(query, {"table_name": table_name, "column_name": column_name}).first()
    return result is not None
