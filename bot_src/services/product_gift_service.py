"""شراء أكواد المخزون الرقمية كهدية لمستفيد محدد."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from database.models import (
    CategoryType,
    DigitalInventoryItem,
    InventoryItemStatus,
    Product,
    ProductFulfillmentType,
    ProductGift,
    ProductGiftStatus,
    ProductStatus,
    SubCategory,
    Transaction,
    TransactionType,
    UnifiedOrder,
    UnifiedOrderStatus,
    User,
)
from services.balance_service import BalanceService
from services.inventory_service import InventoryError, InventoryService


class ProductGiftError(Exception):
    """خطأ آمن يمكن عرضه للمستخدم أثناء شراء الهدية أو استلامها."""


class ProductGiftService:
    @staticmethod
    def is_giftable(product: Product) -> bool:
        category = getattr(getattr(product, "sub_category", None), "category", None)
        return bool(
            product.fulfillment_type == ProductFulfillmentType.INVENTORY
            and category is not None
            and category.type in (CategoryType.CARDS, CategoryType.SUBSCRIPTIONS)
        )

    @staticmethod
    async def create(
        session,
        sender_user_id: int,
        recipient_user_id: int,
        product_id: int,
        price_usd: Decimal,
    ) -> tuple[ProductGift, UnifiedOrder]:
        price_usd = Decimal(str(price_usd)).quantize(Decimal("0.0001"))
        if price_usd <= 0:
            raise ProductGiftError("سعر الهدية غير صالح.")
        if sender_user_id == recipient_user_id:
            raise ProductGiftError("لا يمكنك إرسال هدية إلى حسابك نفسه.")

        async with BalanceService._get_lock(sender_user_id):
            sender = await session.get(User, sender_user_id)
            recipient = await session.get(User, recipient_user_id)
            product_result = await session.execute(
                select(Product)
                .options(
                    selectinload(Product.sub_category).selectinload(SubCategory.category)
                )
                .where(Product.id == product_id)
            )
            product = product_result.scalar_one_or_none()
            if sender is None or recipient is None:
                raise ProductGiftError("تعذر العثور على حساب المرسل أو المستفيد.")
            if recipient.is_banned:
                raise ProductGiftError("لا يمكن إرسال هدية إلى هذا الحساب.")
            if product is None or product.status != ProductStatus.ACTIVE:
                raise ProductGiftError("المنتج غير متاح حالياً.")
            if not ProductGiftService.is_giftable(product):
                raise ProductGiftError("الإهداء متاح للأكواد والاشتراكات الرقمية من مخزون المتجر فقط.")
            if sender.balance < price_usd:
                raise ProductGiftError("رصيدك غير كافٍ لشراء هذه الهدية.")

            reserved_item = None
            for _ in range(3):
                candidate_result = await session.execute(
                    select(DigitalInventoryItem)
                    .where(
                        DigitalInventoryItem.product_id == product_id,
                        DigitalInventoryItem.status == InventoryItemStatus.AVAILABLE,
                    )
                    .order_by(DigitalInventoryItem.id)
                    .limit(1)
                )
                candidate = candidate_result.scalar_one_or_none()
                if candidate is None:
                    raise ProductGiftError("نفد مخزون هذا المنتج حالياً.")
                reserved = await session.execute(
                    update(DigitalInventoryItem)
                    .where(
                        DigitalInventoryItem.id == candidate.id,
                        DigitalInventoryItem.status == InventoryItemStatus.AVAILABLE,
                    )
                    .values(status=InventoryItemStatus.RESERVED)
                )
                if reserved.rowcount == 1:
                    candidate.status = InventoryItemStatus.RESERVED
                    reserved_item = candidate
                    break
            if reserved_item is None:
                raise ProductGiftError("تعذر حجز عنصر من المخزون، حاول مجدداً.")

            now = datetime.utcnow()
            sender.balance -= price_usd
            sender.total_spent_usd = (sender.total_spent_usd or Decimal("0")) + price_usd
            sender.total_orders = (sender.total_orders or 0) + 1
            order = UnifiedOrder(
                user_id=sender_user_id,
                product_id=product_id,
                quantity=1,
                price_usd=price_usd,
                cost_price_usd=Decimal("0"),
                status=UnifiedOrderStatus.PROCESSING,
                status_message="هدية رقمية بانتظار استلام المستفيد",
                result_data=json.dumps(
                    {"gift_pending": True, "recipient_user_id": recipient_user_id},
                    ensure_ascii=False,
                ),
            )
            session.add(order)
            await session.flush()

            gift = ProductGift(
                sender_user_id=sender_user_id,
                recipient_user_id=recipient_user_id,
                product_id=product_id,
                inventory_item_id=reserved_item.id,
                unified_order_id=order.id,
                status=ProductGiftStatus.PENDING,
            )
            session.add(gift)
            await session.flush()
            session.add(
                Transaction(
                    user_id=sender_user_id,
                    type=TransactionType.PURCHASE,
                    amount=-price_usd,
                    balance_after=sender.balance,
                    related_table="unified_orders",
                    related_id=order.id,
                    description=f"شراء هدية رقمية للمستخدم #{recipient_user_id}",
                )
            )
            await session.commit()
            await session.refresh(gift)
            await session.refresh(order)
            return gift, order

    @staticmethod
    async def claim(session, gift_id: int, recipient_user_id: int) -> ProductGift:
        result = await session.execute(
            select(ProductGift)
            .options(selectinload(ProductGift.product))
            .where(
                ProductGift.id == gift_id,
                ProductGift.recipient_user_id == recipient_user_id,
            )
        )
        gift = result.scalar_one_or_none()
        if gift is None:
            raise ProductGiftError("الهدية غير موجودة لهذا الحساب.")
        if gift.status == ProductGiftStatus.CANCELLED:
            raise ProductGiftError("ألغى المرسل هذه الهدية واسترد قيمتها.")
        if gift.status == ProductGiftStatus.CLAIMED:
            return gift

        item = await session.get(DigitalInventoryItem, gift.inventory_item_id)
        order = await session.get(UnifiedOrder, gift.unified_order_id)
        if (
            item is None
            or order is None
            or item.status != InventoryItemStatus.RESERVED
        ):
            raise ProductGiftError("تعذر استلام الهدية، تواصل مع الدعم مع رقم الهدية.")
        try:
            InventoryService.decrypt_value(item.encrypted_value)
        except InventoryError:
            raise ProductGiftError("تعذر تجهيز الهدية الآن. أبلغ الدعم برقم الهدية.") from None

        now = datetime.utcnow()
        changed = await session.execute(
            update(ProductGift)
            .where(
                ProductGift.id == gift_id,
                ProductGift.recipient_user_id == recipient_user_id,
                ProductGift.status == ProductGiftStatus.PENDING,
            )
            .values(status=ProductGiftStatus.CLAIMED, claimed_at=now)
        )
        if changed.rowcount != 1:
            await session.rollback()
            raise ProductGiftError("تغيرت حالة الهدية. حدّث القائمة وحاول مجدداً.")

        item.status = InventoryItemStatus.SOLD
        item.unified_order_id = order.id
        item.sold_at = now
        order.status = UnifiedOrderStatus.COMPLETED
        order.status_message = "تم استلام الهدية الرقمية وتسليمها للمستفيد"
        order.completed_at = now
        order.result_data = json.dumps(
            {
                "gift_id": gift.id,
                "recipient_user_id": recipient_user_id,
                "inventory_item_id": item.id,
            },
            ensure_ascii=False,
        )
        await session.commit()
        await session.refresh(gift)
        return gift

    @staticmethod
    async def cancel(session, gift_id: int, sender_user_id: int) -> None:
        gift_result = await session.execute(
            select(ProductGift).where(
                ProductGift.id == gift_id,
                ProductGift.sender_user_id == sender_user_id,
            )
        )
        gift = gift_result.scalar_one_or_none()
        if gift is None:
            raise ProductGiftError("الهدية غير موجودة لهذا الحساب.")

        async with BalanceService._get_lock(sender_user_id):
            await session.refresh(gift)
            if gift.status != ProductGiftStatus.PENDING:
                raise ProductGiftError("يمكن إلغاء الهدية قبل استلامها فقط.")
            sender = await session.get(User, sender_user_id)
            order = await session.get(UnifiedOrder, gift.unified_order_id)
            if sender is None or order is None:
                raise ProductGiftError("تعذر استرجاع قيمة الهدية. تواصل مع الدعم.")

            changed = await session.execute(
                update(ProductGift)
                .where(
                    ProductGift.id == gift_id,
                    ProductGift.sender_user_id == sender_user_id,
                    ProductGift.status == ProductGiftStatus.PENDING,
                )
                .values(status=ProductGiftStatus.CANCELLED)
            )
            if changed.rowcount != 1:
                await session.rollback()
                raise ProductGiftError("استلم المستفيد الهدية قبل إلغائها.")

            released = await session.execute(
                update(DigitalInventoryItem)
                .where(
                    DigitalInventoryItem.id == gift.inventory_item_id,
                    DigitalInventoryItem.status == InventoryItemStatus.RESERVED,
                )
                .values(status=InventoryItemStatus.AVAILABLE)
            )
            if released.rowcount != 1:
                await session.rollback()
                raise ProductGiftError("تعذر تحرير المخزون؛ تواصل مع الدعم.")

            amount = order.price_usd
            sender.balance += amount
            sender.total_spent_usd = max(
                Decimal("0"), (sender.total_spent_usd or Decimal("0")) - amount
            )
            sender.total_orders = max(0, (sender.total_orders or 0) - 1)
            order.status = UnifiedOrderStatus.REFUNDED
            order.status_message = "ألغى المرسل الهدية قبل استلامها وأُعيد المبلغ"
            session.add(
                Transaction(
                    user_id=sender_user_id,
                    type=TransactionType.REFUND,
                    amount=amount,
                    balance_after=sender.balance,
                    related_table="unified_orders",
                    related_id=order.id,
                    description=f"استرجاع قيمة الهدية الرقمية #{gift.id}",
                )
            )
            await session.commit()
