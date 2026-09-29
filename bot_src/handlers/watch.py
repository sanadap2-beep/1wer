"""
🔔 تنبيهات المنتجات: متابعة/إلغاء + فحص دوري موجود بـ WatchService.
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select

from database.models import ProductWatch
from services.watch_service import WatchService

router = Router(name="watch")


@router.callback_query(F.data.startswith("watch:toggle:"))
async def watch_toggle(callback: CallbackQuery, session, db_user):
    pid = int(callback.data.rsplit(":", 1)[1])
    try:
        on = await WatchService.toggle(session, db_user.id, pid)
    except ValueError:
        await callback.answer("⚠️ المنتج غير متوفر.", show_alert=True)
        return
    await callback.answer("🔔 تم تفعيل التنبيه" if on else "🔕 أُلغي التنبيه")
    # تحديث صفحة المنتج لتعكس الحالة
    try:
        from handlers.store import store_product

        await store_product(callback, session, db_user)
    except Exception:
        pass


async def is_watching(session, user_id: int, product_id: int) -> bool:
    result = await session.execute(select(ProductWatch).where(
        ProductWatch.user_id == user_id, ProductWatch.product_id == product_id,
        ProductWatch.is_active.is_(True)))
    return result.scalar_one_or_none() is not None
