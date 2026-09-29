"""add trader rank requests (user applies, admin approves from channel/panel)

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-09-29 00:00:00.000000

طلبات رتب التجار (خصم التجار):
- trader_requests: طلب المستخدم لرتبة + حالته + قرار الأدمن.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h2i3j4k5l6m7"
down_revision: Union[str, None] = "g1h2i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trader_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("tier_key", sa.String(length=32), nullable=False, index=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending", index=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("admin_chat_message_id", sa.BigInteger(), nullable=True),
        sa.Column("reject_reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("trader_requests")
