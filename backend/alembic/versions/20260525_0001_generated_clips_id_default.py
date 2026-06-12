"""set generated_clips id default

Revision ID: 20260525_0001
Revises: f5918c02a037
Create Date: 2026-05-25 11:50:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260525_0001"
down_revision: Union[str, Sequence[str], None] = "f5918c02a037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow raw INSERTs into generated_clips to omit id."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        "ALTER TABLE generated_clips "
        "ALTER COLUMN id SET DEFAULT gen_random_uuid()::text"
    )


def downgrade() -> None:
    """Remove generated_clips.id database default."""
    op.execute("ALTER TABLE generated_clips ALTER COLUMN id DROP DEFAULT")
