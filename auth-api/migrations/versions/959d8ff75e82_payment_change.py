"""payment change

Revision ID: 959d8ff75e82
Revises: 66ae9d618842
Create Date: 2020-09-28 07:34:51.175055

"""
from typing import Dict, List

import sqlalchemy as sa
from alembic import op
from flask import current_app

from auth_api.models import Org
from auth_api.services.rest_service import RestService
from auth_api.utils.enums import OrgType, PaymentMethod


revision = '959d8ff75e82'
down_revision = '66ae9d618842'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('org', sa.Column('bcol_account_id', sa.String(length=20), nullable=True))
    op.add_column('org', sa.Column('bcol_user_id', sa.String(length=20), nullable=True))
    op.add_column('org_version', sa.Column('bcol_account_id', sa.String(length=20), autoincrement=False, nullable=True))
    op.add_column('org_version', sa.Column('bcol_user_id', sa.String(length=20), autoincrement=False, nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('org_version', 'bcol_user_id')
    op.drop_column('org_version', 'bcol_account_id')
    op.drop_column('org', 'bcol_user_id')
    op.drop_column('org', 'bcol_account_id')
    # ### end Alembic commands ###
