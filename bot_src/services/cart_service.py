"""
سلة المتجر: إضافة/عرض/حذف/إتمام جماعي.

ملاحظة: السلة تدعم المنتجات ذات الكميات المرنة (رشق، ألعاب).
منتجات الفئات الثابتة (dropdown سيريتل/MTN) تُشترى مباشرة فقط.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.models import CartItem, Product, ProductStatus


async def add_item(session, user_id: int, product_id: int, target: str, qty: int) -> CartItem:
    product = await session.get(Product, product_id)
    if product is None or product.status != ProductStatus.ACTIVE:
        raise ValueError("المنتج غير متوفر")
    existing = await session.execute(select(CartItem).where(
        CartItem.user_id == user_id, CartItem.product_id == product_id))
    row = existing.scalar_one_or_none()
    if row:
        row.target = (target or "")[:500]
        row.quantity = max(1, int(qty))
    else:
        row = CartItem(user_id=user_id, product_id=product_id,
                       target=(target or "")[:500], quantity=max(1, int(qty)))
        session.add(row)
    await session.commit()
    return row


async def list_items(session, user_id: int) -> list[CartItem]:
    result = await session.execute(
        select(CartItem)
        .where(CartItem.user_id == user_id)
        .options(selectinload(CartItem.product))
        .order_by(CartItem.id)
    )
    return list(result.scalars().all())


async def remove_item(session, user_id: int, item_id: int) -> bool:
    row = await session.get(CartItem, item_id)
    if row is None or row.user_id != user_id:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def clear(session, user_id: int) -> None:
    result = await session.execute(select(CartItem).where(CartItem.user_id == user_id))
    for row in result.scalars().all():
        await session.delete(row)
    await session.commit()


async def totals(session, items: list[CartItem], user=None) -> tuple[Decimal, list[tuple[CartItem, Decimal]]]:
    """(الإجمالي، [(item, sell)]) — أسعار لحظية بعد الهامش وخصم التاجر."""
    from services.store_order_service import price_for

    lines: list[tuple[CartItem, Decimal]] = []
    total = Decimal("0")
    for item in items:
        product = item.product or await session.get(Product, item.product_id)
        if product is None or product.status != ProductStatus.ACTIVE:
            continue
        _cost, sell, _m = await price_for(session, product, str(item.quantity), user)
        lines.append((item, sell))
        total += sell
    return total.quantize(Decimal("0.0001")), lines
