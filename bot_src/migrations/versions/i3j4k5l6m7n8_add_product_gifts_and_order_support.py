"""add product gifting and order-linked support tickets

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-09-30 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i3j4k5l6m7n8"
down_revision: Union[str, None] = "h2i3j4k5l6m7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {
        column["name"] for column in inspector.get_columns("support_tickets")
    }
    existing_foreign_keys = {
        (tuple(fk.get("constrained_columns") or ()), fk.get("referred_table"))
        for fk in inspector.get_foreign_keys("support_tickets")
    }

    # SQLite cannot ALTER a table to add foreign-key constraints. Batch mode
    # rebuilds the table and also recovers safely if an earlier attempt added
    # one of the nullable columns before failing at its FK constraint.
    with op.batch_alter_table("support_tickets", recreate="always") as batch_op:
        if "number_order_id" not in existing_columns:
            batch_op.add_column(sa.Column("number_order_id", sa.Integer(), nullable=True))
        if "unified_order_id" not in existing_columns:
            batch_op.add_column(sa.Column("unified_order_id", sa.Integer(), nullable=True))
        if "attachment_file_id" not in existing_columns:
            batch_op.add_column(sa.Column("attachment_file_id", sa.String(length=255), nullable=True))
        if (("number_order_id",), "number_orders") not in existing_foreign_keys:
            batch_op.create_foreign_key(
                "fk_support_tickets_number_order_id",
                "number_orders",
                ["number_order_id"],
                ["id"],
            )
        if (("unified_order_id",), "unified_orders") not in existing_foreign_keys:
            batch_op.create_foreign_key(
                "fk_support_tickets_unified_order_id",
                "unified_orders",
                ["unified_order_id"],
                ["id"],
            )

    inspector = sa.inspect(bind)
    support_indexes = {index["name"] for index in inspector.get_indexes("support_tickets")}
    if "ix_support_tickets_number_order_id" not in support_indexes:
        op.create_index("ix_support_tickets_number_order_id", "support_tickets", ["number_order_id"])
    if "ix_support_tickets_unified_order_id" not in support_indexes:
        op.create_index("ix_support_tickets_unified_order_id", "support_tickets", ["unified_order_id"])

    if "product_gifts" not in inspector.get_table_names():
        op.create_table(
            "product_gifts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("sender_user_id", sa.Integer(), nullable=False),
            sa.Column("recipient_user_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("inventory_item_id", sa.Integer(), nullable=False),
            sa.Column("unified_order_id", sa.Integer(), nullable=False),
            sa.Column(
                "status",
                sa.Enum("PENDING", "CLAIMED", "CANCELLED", name="productgiftstatus"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
            sa.Column("claimed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
            sa.ForeignKeyConstraint(["inventory_item_id"], ["digital_inventory_items.id"]),
            sa.ForeignKeyConstraint(["unified_order_id"], ["unified_orders.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("inventory_item_id", name="uq_product_gift_inventory_item"),
            sa.UniqueConstraint("unified_order_id", name="uq_product_gift_unified_order"),
        )

    product_gift_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("product_gifts")
    }
    for index_name, column_name in (
        ("ix_product_gifts_sender_user_id", "sender_user_id"),
        ("ix_product_gifts_recipient_user_id", "recipient_user_id"),
        ("ix_product_gifts_product_id", "product_id"),
        ("ix_product_gifts_status", "status"),
    ):
        if index_name not in product_gift_indexes:
            op.create_index(index_name, "product_gifts", [column_name])


def downgrade() -> None:
    op.drop_index("ix_product_gifts_status", table_name="product_gifts")
    op.drop_index("ix_product_gifts_product_id", table_name="product_gifts")
    op.drop_index("ix_product_gifts_recipient_user_id", table_name="product_gifts")
    op.drop_index("ix_product_gifts_sender_user_id", table_name="product_gifts")
    op.drop_table("product_gifts")
    sa.Enum(name="productgiftstatus").drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_support_tickets_unified_order_id", table_name="support_tickets")
    op.drop_index("ix_support_tickets_number_order_id", table_name="support_tickets")
    with op.batch_alter_table("support_tickets") as batch_op:
        batch_op.drop_column("attachment_file_id")
        batch_op.drop_column("unified_order_id")
        batch_op.drop_column("number_order_id")
