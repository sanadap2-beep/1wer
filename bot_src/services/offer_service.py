"""
🔥 العروض المؤقتة: خصم ثابت على منتجات ثابتة السعر مع عدّاد انتهاء.

- الإنشاء من صفحة المنتج باللوحة (خصم % + مدة ساعات).
- السعر يُحسب لحظياً بخصم العرض في price_for.
- مهمة المتجر تُنهي العروض المنتهية تلقائياً.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from database.models import Product, SpecialOffer

ACTIVE = "active"


async def active_offer_for_product(session, product: Product) -> SpecialOffer | None:
    """العرض الفعال لمنتج (إن وجد)."""
    if not product.provider_service_ref_id:
        return None
    result = await session.execute(select(SpecialOffer).where(
        SpecialOffer.status == ACTIVE,
        SpecialOffer.provider_service_ref_id == product.provider_service_ref_id,
    ).order_by(SpecialOffer.id.desc()))
    for offer in result.scalars().all():
        if offer.ends_at and offer.ends_at <= datetime.utcnow():
            continue
        return offer
    return None


async def offer_eligible(product, provider_service) -> bool:
    """العروض للمنتجات ثابتة السعر فقط (بدون كمية حرة أو فئات)."""
    from services.store_order_service import quantity_options_of

    if product.requires_quantity:
        return False
    if quantity_options_of(provider_service):
        return False
    return True


async def create_offer(
    session, product_id: int, discount_percent: Decimal, hours: int, created_by: int,
) -> SpecialOffer:
    """ينشئ عرضاً من منتج: السعر = البيع الحالي × (1 - الخصم)."""
    from services.store_order_service import price_for

    product = await session.get(Product, product_id)
    if product is None:
        raise ValueError("المنتج غير موجود")
    if not (0 < discount_percent < 100):
        raise ValueError("الخصم بين 1 و 99")
    hours = max(1, min(168, int(hours)))
    _cost, sell, _m = await price_for(session, product, "1")
    price = (sell * (Decimal("100") - discount_percent) / Decimal("100")).quantize(Decimal("0.0001"))
    now = datetime.utcnow()
    offer = SpecialOffer(
        offer_type="api",
        name=f"عرض: {product.name_ar[:100]}",
        description=f"خصم {discount_percent}% لفترة محدودة",
        price_usd=price,
        input_label="",
        status=ACTIVE,
        api_provider_id=product.api_provider_id,
        provider_service_id=product.provider_service_id,
        provider_service_ref_id=product.provider_service_ref_id,
        required_quantity=1,
        starts_at=now,
        ends_at=now + timedelta(hours=hours),
        created_by=created_by,
    )
    session.add(offer)
    await session.commit()
    return offer


async def list_active(session) -> list[SpecialOffer]:
    result = await session.execute(select(SpecialOffer).where(
        SpecialOffer.status == ACTIVE).order_by(SpecialOffer.ends_at))
    now = datetime.utcnow()
    return [o for o in result.scalars().all() if not o.ends_at or o.ends_at > now]


async def expire_due(session) -> int:
    """ينهي العروض المنتهية. يرجع العدد."""
    result = await session.execute(select(SpecialOffer).where(SpecialOffer.status == ACTIVE))
    now = datetime.utcnow()
    n = 0
    for offer in result.scalars().all():
        if offer.ends_at and offer.ends_at <= now:
            offer.status = "expired"
            n += 1
    if n:
        await session.commit()
    return n


def remaining_ar(offer: SpecialOffer) -> str:
    """المتبقي نصاً (ساعة/دقائق)."""
    if not offer.ends_at:
        return "مستمر"
    delta = offer.ends_at - datetime.utcnow()
    total_min = max(0, int(delta.total_seconds() // 60))
    h, m = divmod(total_min, 60)
    if h >= 24:
        return f"{h // 24} يوم و {h % 24} ساعة"
    if h:
        return f"{h} ساعة و {m} دقيقة"
    return f"{m} دقيقة"
