"""
⭐ تقييمات المنتجات: نجمة 1-5 بعد اكتمال الطلب + متوسط التقييم.
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select

from database.models import ProductReview, UnifiedOrder, UnifiedOrderStatus

router = Router(name="reviews")


async def product_rating(session, product_id: int) -> tuple[float, int]:
    """(المتوسط، العدد) لتقييمات منتج."""
    result = await session.execute(
        select(func.avg(ProductReview.rating), func.count(ProductReview.id)).where(
            ProductReview.product_id == product_id)
    )
    avg, count = result.one()
    return (float(avg or 0), int(count or 0))


@router.callback_query(F.data.startswith("review:start:"))
async def review_start(callback: CallbackQuery, session, db_user):
    order_id = int(callback.data.rsplit(":", 1)[1])
    order = await session.get(UnifiedOrder, order_id)
    if not order or order.user_id != db_user.id:
        await callback.answer("⚠️ غير موجود.", show_alert=True)
        return
    if order.status != UnifiedOrderStatus.COMPLETED or not order.product_id:
        await callback.answer("⚠️ التقييم للطلبات المكتملة فقط.", show_alert=True)
        return
    existing = await session.execute(select(ProductReview).where(
        ProductReview.user_id == db_user.id, ProductReview.product_id == order.product_id))
    if existing.scalar_one_or_none():
        await callback.answer("قيّمت هذا المنتج مسبقاً. شكراً! ⭐", show_alert=True)
        return
    rows = [[InlineKeyboardButton(text="⭐" * n, callback_data=f"review:rate:{order_id}:{n}", style="primary")] for n in (5, 4, 3, 2, 1)]
    await callback.message.edit_text(
        "⭐ <b>قيّم تجربتك</b>\n\nكم نجمة تعطي هذا المنتج؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("review:rate:"))
async def review_rate(callback: CallbackQuery, session, db_user):
    _, _, order_id, stars = callback.data.split(":")
    order = await session.get(UnifiedOrder, int(order_id))
    if not order or order.user_id != db_user.id or order.status != UnifiedOrderStatus.COMPLETED:
        await callback.answer("⚠️ غير صالح.", show_alert=True)
        return
    stars = max(1, min(5, int(stars)))
    existing = await session.execute(select(ProductReview).where(
        ProductReview.user_id == db_user.id, ProductReview.product_id == order.product_id))
    if existing.scalar_one_or_none():
        await callback.answer("قيّمت مسبقاً. شكراً! ⭐", show_alert=True)
        return
    session.add(ProductReview(
        user_id=db_user.id, product_id=order.product_id,
        unified_order_id=order.id, rating=stars,
    ))
    await session.commit()
    await callback.message.edit_text(f"شكراً لتقييمك! {'⭐' * stars}\nرأيك يساعد الزبائن الآخرين 🤝")
    await callback.answer("✅ تم حفظ تقييمك")
