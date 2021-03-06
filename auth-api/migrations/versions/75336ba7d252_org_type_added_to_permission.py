"""org type added to permission 

Revision ID: 75336ba7d252
Revises: fc8b221f938f
Create Date: 2020-11-24 06:17:51.309701

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import column, table


# revision identifiers, used by Alembic.
revision = '75336ba7d252'
down_revision = 'fc8b221f938f'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('permissions', sa.Column('org_status_code', sa.String(length=25), nullable=True))
    op.alter_column('permissions', 'membership_type_code',
                    existing_type=sa.VARCHAR(length=15),
                    type_=sa.String(length=25),
                    nullable=True)
    op.drop_constraint('permissions_membership_type_code_fkey', 'permissions', type_='foreignkey')

    permissions_table = table('permissions',
                              column('id', sa.Integer()),
                              column('membership_type_code', sa.String(length=15)),
                              column('org_status_code', sa.String(length=25)),
                              column('actions', sa.String(length=100)))

    # Insert code values
    op.bulk_insert(
        permissions_table,
        [
            {'id': 25, 'membership_type_code': 'ADMIN', 'org_status_code': 'NSF_SUSPENDED',
             'actions': 'MANAGE_STATEMENTS'},
            {'id': 26, 'membership_type_code': 'ADMIN', 'org_status_code': 'NSF_SUSPENDED',
             'actions': 'VIEW_ACCOUNT'},
            {'id': 27, 'membership_type_code': 'ADMIN', 'org_status_code': 'NSF_SUSPENDED',
             'actions': 'INVITE_MEMBERS'},
            {'id': 28, 'membership_type_code': 'ADMIN', 'org_status_code': 'NSF_SUSPENDED',
             'actions': 'TRANSACTION_HISTORY'},

        ]
    )

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.execute('delete from permissions where id in(25,26,27,28)')
    op.create_foreign_key('permissions_membership_type_code_fkey', 'permissions', 'membership_type',
                          ['membership_type_code'], ['code'])
    op.alter_column('permissions', 'membership_type_code',
                    existing_type=sa.String(length=25),
                    type_=sa.VARCHAR(length=15),
                    nullable=False)
    op.drop_column('permissions', 'org_status_code')

    # ### end Alembic commands ###
