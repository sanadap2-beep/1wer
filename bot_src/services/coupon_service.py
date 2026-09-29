"""
الكوبونات وأكواد الحملات: إنشاء + تحقق + تطبيق.

- coupons: كوبونات عامة (percent / fixed).
- campaign_codes: أكواد حملات مع tracking للمصدر.
- لكل مستخدم استخدام واحد لكل كود (uq constraints) + حد عام + صلاحية + حد أدنى.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.models import CampaignCode, CampaignCodeUsage, Coupon, CouponUsage
from services.coupon_math import calc_discount

KINDS = ("coupon", "campaign")


async def _get_code(session, kind: str, code: str):
    code = (code or "").strip().upper()
    if kind == "campaign":
        r = await session.execute(select(CampaignCode).where(CampaignCode.code == code))
    else:
        r = await session.execute(select(Coupon).where(Coupon.code == code))
    return r.scalar_one_or_none()


async def validate(
    session, kind: str, code: str, user_id: int, order_total: Decimal
) -> tuple[bool, object | None, Decimal, str]:
    """يتحقق من الكود. يرجع (صالح، السجل، مبلغ الخصم، رسالة)."""
    row = await _get_code(session, kind, code)
    if row is None:
        return False, None, Decimal("0"), "⚠️ الكود غير موجود."
    if not row.is_active:
        return False, None, Decimal("0"), "⚠️ هذا الكود معطّل."
    if row.expires_at and datetime.utcnow() > row.expires_at:
        return False, None, Decimal("0"), "⚠️ انتهت صلاحية هذا الكود."
    if row.used_count >= row.max_uses:
        return False, None, Decimal("0"), "⚠️ استُنفد هذا الكود."
    if order_total < (row.min_order_usd or Decimal("0")):
        return False, None, Decimal("0"), (
            f"⚠️ هذا الكود للطلبات فوق {row.min_order_usd}$ فقط."
        )
    if kind == "campaign":
        used = await session.execute(select(CampaignCodeUsage).where(
            CampaignCodeUsage.campaign_id == row.id, CampaignCodeUsage.user_id == user_id))
    else:
        used = await session.execute(select(CouponUsage).where(
            CouponUsage.coupon_id == row.id, CouponUsage.user_id == user_id))
    if used.scalar_one_or_none():
        return False, None, Decimal("0"), "⚠️ استخدمت هذا الكود من قبل."
    discount = calc_discount(order_total, row.discount_type, row.discount_value)
    if discount <= 0:
        return False, None, Decimal("0"), "⚠️ الكود لا يعطي خصماً على هذا المبلغ."
    label = "حملة" if kind == "campaign" else "كوبون"
    track = f" ({row.tracking})" if kind == "campaign" and row.tracking else ""
    return True, row, discount, f"✅ {label}{track}: خصم <b>{discount}$</b>"


async def apply_use(session, kind: str, code_id: int, user_id: int, discount: Decimal) -> bool:
    """يسجل الاستخدام (يُستدعى بعد نجاح الدفع). يرجع False إذا كان مستخدماً."""
    try:
        if kind == "campaign":
            row = await session.get(CampaignCode, code_id)
            if row is None:
                return False
            session.add(CampaignCodeUsage(campaign_id=code_id, user_id=user_id, discount_applied=discount))
        else:
            row = await session.get(Coupon, code_id)
            if row is None:
                return False
            session.add(CouponUsage(coupon_id=code_id, user_id=user_id, discount_applied=discount))
        row.used_count = (row.used_count or 0) + 1
        await session.commit()
        return True
    except IntegrityError:
        await session.rollback()
        return False


async def create_code(
    session, kind: str, created_by: int, code: str, discount_type: str,
    value: Decimal, max_uses: int = 100, min_order_usd: Decimal = Decimal("0"),
    days_valid: int = 30, tracking: str = "",
):
    """ينشئ كوبون/حملة جديدة."""
    code = (code or "").strip().upper()
    if not code or len(code) > 32:
        raise ValueError("الكود فارغ أو طويل")
    if discount_type not in ("percent", "fixed"):
        raise ValueError("النوع percent أو fixed فقط")
    value = Decimal(str(value))
    if value <= 0 or (discount_type == "percent" and value > 100):
        raise ValueError("قيمة غير صالحة")
    expires = datetime.utcnow() + timedelta(days=days_valid) if days_valid > 0 else None
    if kind == "campaign":
        row = CampaignCode(
            code=code, tracking=(tracking or "")[:64], discount_type=discount_type,
            discount_value=value, max_uses=max(1, max_uses),
            min_order_usd=min_order_usd, expires_at=expires, created_by=created_by,
        )
    else:
        row = Coupon(
            code=code, discount_type=discount_type, discount_value=value,
            max_uses=max(1, max_uses), min_order_usd=min_order_usd,
            expires_at=expires, created_by=created_by,
        )
    session.add(row)
    await session.commit()
    return row
