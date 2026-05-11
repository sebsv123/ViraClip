"""add_error_message_retry_count

Revision ID: 7ee536e859b8
Revises: face92e74fe7
Create Date: 2026-05-11 16:54:50.188449

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7ee536e859b8'
down_revision: Union[str, Sequence[str], None] = 'face92e74fe7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
