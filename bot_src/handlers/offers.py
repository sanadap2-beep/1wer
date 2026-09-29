"""
🔥 العروض المؤقتة: قائمة الزبون + إنشاء الأدمن من صفحة المنتج.
"""

from decimal import Decimal

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from database.models import Product, ProductStatus, ProviderService
from services import offer_service
from states.states import AdminOfferStates

router = Router(name="offers")


@router.callback_query(F.data == "store:deals")
async def deals_list(callback: CallbackQuery, session):
    offers = await offer_service.list_active(session)
    if not offers:
        await callback.answer("لا توجد عروض حالياً.", show_alert=True)
        return
    from services.dynamic_service import DynamicService

    lines = ["🔥 <b>العروض المؤقتة</b>\n"]
    rows: list[list[InlineKeyboardButton]] = []
    for offer in offers[:15]:
        prod = None
        if offer.provider_service_ref_id:
            from sqlalchemy import select

            r = await session.execute(select(Product).where(
                Product.provider_service_ref_id == offer.provider_service_ref_id,
                Product.status == ProductStatus.ACTIVE,
            ).order_by(Product.id).limit(1))
            prod = r.scalar_one_or_none()
        left = offer_service.remaining_ar(offer)
        if prod:
            lines.append(f"• {prod.name_ar[:35]} — <b>{offer.price_usd}$</b> (ينتهي خلال {left})")
            rows.append([InlineKeyboardButton(
                text=f"🔥 {prod.name_ar[:30]} — {offer.price_usd}$",
                callback_data=f"store:prod:{prod.id}", style="success")])
        else:
            lines.append(f"• {offer.name[:35]} — <b>{offer.price_usd}$</b> (ينتهي خلال {left})")
    rows.append([InlineKeyboardButton(text="🛍 المتجر", callback_data="store:home", style="success")])
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:offer_create:"))
async def offer_create_start(callback: CallbackQuery, state: FSMContext, session, db_user):
    if not db_user.is_admin:
        await callback.answer("⚠️ للأدمن فقط.", show_alert=True)
        return
    pid = int(callback.data.rsplit(":", 1)[1])
    product = await session.get(Product, pid)
    if not product:
        await callback.answer("⚠️ غير موجود.", show_alert=True)
        return
    ps = await session.get(ProviderService, product.provider_service_ref_id) if product.provider_service_ref_id else None
    if not await offer_service.offer_eligible(product, ps):
        await callback.answer("العروض للمنتجات ثابتة السعر فقط.", show_alert=True)
        return
    await state.update_data(offer_product=pid)
    from services.store_order_service import price_for

    _c, sell, _m = await price_for(session, product, "1")
    await state.update_data(offer_base=str(sell))
    await callback.message.edit_text(
        f"🔥 عرض جديد على: <b>{product.name_ar[:40]}</b>\nالسعر الحالي: {sell}$\n\n"
        "أرسل نسبة الخصم (1-90):"
    )
    await state.set_state(AdminOfferStates.waiting_discount)
    await callback.answer()


@router.message(AdminOfferStates.waiting_discount)
async def offer_discount_received(message: Message, state: FSMContext):
    try:
        d = Decimal((message.text or "").strip().replace("%", ""))
    except Exception:
        await message.answer("⚠️ رقم فقط.")
        return
    if not (0 < d <= 90):
        await message.answer("⚠️ بين 1 و 90.")
        return
    await state.update_data(offer_discount=str(d))
    await message.answer("⏳ أرسل مدة العرض بالساعات (1-168):")
    await state.set_state(AdminOfferStates.waiting_hours)


@router.message(AdminOfferStates.waiting_hours)
async def offer_hours_received(message: Message, state: FSMContext, session):
    try:
        hours = max(1, min(168, int((message.text or "").strip())))
    except (ValueError, TypeError):
        await message.answer("⚠️ رقم صحيح فقط.")
        return
    data = await state.get_data()
    try:
        offer = await offer_service.create_offer(
            session, int(data["offer_product"]), Decimal(data["offer_discount"]),
            hours, created_by=message.from_user.id,
        )
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    await state.clear()
    await message.answer(
        f"🔥 تم تفعيل العرض!\n\n{offer.name}\n💰 السعر: <b>{offer.price_usd}$</b>\n"
        f"⏳ ينتهي خلال {offer_service.remaining_ar(offer)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 المنتج", callback_data=f"admin:store_prod:{data['offer_product']}")]
        ]),
    )
