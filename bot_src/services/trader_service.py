"""
👑 رتب التجار: تعريف + تعيين يدوي + خصم أسعار.

- الرتب الافتراضية: عادي 0% / تاجر 5% / ذهبي 10% (تُضبط من اللوحة).
- التعيين: خريطة trader_tier_map بالإعدادات (user_id → tier_key) — بلا هجرة.
- الطلبات: جدول trader_requests (موافقة الأدمن من القناة أو اللوحة).
"""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import select

from database.models import TraderRequest

MAP_KEY = "trader_tier_map"
TIERS_KEY = "trader_tiers_json"

DEFAULT_TIERS: list[dict] = [
    {"key": "none", "name": "عادي", "discount": "0"},
    {"key": "trader", "name": "خصم تجار شام كاش 💎", "discount": "5"},
    {"key": "gold", "name": "تاجر ذهبي 👑", "discount": "10"},
]


async def get_tiers(session) -> list[dict]:
    """الرتب المعرفة (من الإعدادات أو الافتراضية)."""
    from services.settings_service import SettingsService

    raw = await SettingsService.get(TIERS_KEY, "")
    if raw:
        try:
            tiers = json.loads(raw)
            if isinstance(tiers, list) and tiers:
                return tiers
        except Exception:
            pass
    return [dict(t) for t in DEFAULT_TIERS]


async def set_tiers(session, tiers: list[dict]) -> None:
    from services.settings_service import SettingsService

    await SettingsService.set(session, TIERS_KEY, json.dumps(tiers, ensure_ascii=False))


async def get_map(session) -> dict:
    from services.settings_service import SettingsService

    raw = await SettingsService.get(MAP_KEY, "{}")
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def set_user_tier(session, user_id: int, tier_key: str) -> None:
    from services.settings_service import SettingsService

    mapping = await get_map(session)
    if tier_key in (None, "", "none"):
        mapping.pop(str(user_id), None)
    else:
        mapping[str(user_id)] = tier_key
    await SettingsService.set(session, MAP_KEY, json.dumps(mapping))


async def user_tier(session, user_id: int) -> dict:
    """رتبة المستخدم (المعينة يدوياً وإلا عادي)."""
    mapping = await get_map(session)
    key = mapping.get(str(user_id), "none")
    for tier in await get_tiers(session):
        if tier.get("key") == key:
            return tier
    return dict(DEFAULT_TIERS[0])


async def discount_for_user(session, user_id: int) -> Decimal:
    """نسبة خصم التاجر للمستخدم (0 إن لم يكن تاجراً)."""
    tier = await user_tier(session, user_id)
    try:
        return max(Decimal("0"), min(Decimal("100"), Decimal(str(tier.get("discount", "0")))))
    except Exception:
        return Decimal("0")


def apply_discount(price: Decimal, discount_pct: Decimal) -> Decimal:
    """السعر بعد خصم التاجر."""
    price = Decimal(str(price))
    discount_pct = Decimal(str(discount_pct or 0))
    if discount_pct <= 0:
        return price
    return (price * (Decimal("100") - discount_pct) / Decimal("100")).quantize(Decimal("0.0001"))


async def pending_request(session, user_id: int) -> TraderRequest | None:
    result = await session.execute(select(TraderRequest).where(
        TraderRequest.user_id == user_id, TraderRequest.status == "pending"
    ).order_by(TraderRequest.id.desc()))
    return result.scalar_one_or_none()


async def create_request(session, user_id: int, tier_key: str, note: str = "") -> TraderRequest:
    if await pending_request(session, user_id):
        raise ValueError("لديك طلب قيد المراجعة مسبقاً")
    valid = {t.get("key") for t in await get_tiers(session)} - {"none"}
    if tier_key not in valid:
        raise ValueError("رتبة غير صالحة")
    row = TraderRequest(user_id=user_id, tier_key=tier_key, note=(note or "")[:255])
    session.add(row)
    await session.commit()
    return row
