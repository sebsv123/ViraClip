"""add tasks include_broll

Revision ID: 20260526_0001
Revises: 20260525_0001
Create Date: 2026-05-26 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260526_0001"
down_revision: Union[str, Sequence[str], None] = "20260525_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tasks "
        "ADD COLUMN IF NOT EXISTS caption_template varchar(50) DEFAULT 'default'"
    )
    op.execute(
        "ALTER TABLE tasks "
        "ADD COLUMN IF NOT EXISTS include_broll boolean DEFAULT false"
    )


def downgrade() -> None:
    op.drop_column("tasks", "include_broll")
    op.drop_column("tasks", "caption_template")
