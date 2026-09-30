"""user streak add

Revision ID: 00c31541c227
Revises: 456650f36206
Create Date: 2026-09-30 12:41:47.319523

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00c31541c227'
down_revision: Union[str, Sequence[str], None] = '456650f36206'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('users', sa.Column('current_streak', sa.Integer(), server_default='0', nullable=False))
    op.add_column('users', sa.Column('longest_streak', sa.Integer(), server_default='0', nullable=False))
    op.add_column('users', sa.Column('last_activity_date', sa.Date(), nullable=True))

def downgrade():
    op.drop_column('users', 'last_activity_date')
    op.drop_column('users', 'longest_streak')
    op.drop_column('users', 'current_streak')