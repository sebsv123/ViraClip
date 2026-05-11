"""add_error_message_retry_count

Revision ID: f5918c02a037
Revises: 7ee536e859b8
Create Date: 2026-05-11 16:54:59.611702

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f5918c02a037'
down_revision: Union[str, Sequence[str], None] = '7ee536e859b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add error_message and retry_count columns to tasks table."""
    op.add_column("tasks", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    """Remove error_message and retry_count columns."""
    op.drop_column("tasks", "retry_count")
    op.drop_column("tasks", "error_message")
