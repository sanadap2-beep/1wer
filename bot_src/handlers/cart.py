"""
🧺 سلة المتجر: عرض + إتمام جماعي بدفعة واحدة.

- الإضافة من شاشة تأكيد المنتج (تحمل الهدف والكمية من الجلسة).
- الإتمام: تنفيذ متسلسل لكل صنف (الكوبون — إن وُجد — على الصنف الأول).
"""

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from database.models import Product, ProductStatus
from services import cart_service
from services.store_order_service import quantity_options_of

router = Router(name="cart")


def _item_line(name: str, qty: int, sell) -> str:
    return f"• {name[:30]} × {qty} = <b>{sell}$</b>"


@router.callback_query(F.data.startswith("store:cart_add:"))
async def cart_add(callback: CallbackQuery, session, db_user, state: FSMContext):
    from database.models import ProviderService

    data = await state.get_data()
    pid = int(callback.data.rsplit(":", 1)[1] or data.get("store_prod", 0))
    target, qty = data.get("store_target", ""), data.get("store_qty", "1")
    product = await session.get(Product, pid)
    if not product or product.status != ProductStatus.ACTIVE:
        await callback.answer("⚠️ المنتج غير متوفر.", show_alert=True)
        return
    ps = await session.get(ProviderService, product.provider_service_ref_id) if product.provider_service_ref_id else None
    if quantity_options_of(ps):
        await callback.answer("هذا المنتج بفئات ثابتة — يُشترى مباشرة فقط.", show_alert=True)
        return
    try:
        qty_int = max(1, int(float(str(qty))))
    except (ValueError, TypeError):
        qty_int = 1
    try:
        await cart_service.add_item(session, db_user.id, pid, target, qty_int)
    except ValueError:
        await callback.answer("⚠️ تعذر الإضافة.", show_alert=True)
        return
    await state.clear()
    items = await cart_service.list_items(session, db_user.id)
    await callback.message.edit_text(
        f"🧺 أُضيف للسلة: <b>{product.name_ar[:40]}</b>\n\nأصبح فيها <b>{len(items)}</b> صنف.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧺 عرض السلة", callback_data="store:cart", style="primary")],
            [InlineKeyboardButton(text="🛍 متابعة التسوق", callback_data="store:home", style="success")],
        ]),
    )
    await callback.answer("✅ أُضيف للسلة")


@router.callback_query(F.data == "store:cart")
async def cart_view(callback: CallbackQuery, session, db_user):
    items = await cart_service.list_items(session, db_user.id)
    if not items:
        await callback.message.edit_text(
            "🧺 <b>سلتك فارغة.</b>\n\nتصفح المتجر وأضف منتجاتك.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛍 المتجر", callback_data="store:home", style="success")]
            ]),
        )
        await callback.answer()
        return
    total, lines = await cart_service.totals(session, items, db_user)
    text = ["🧺 <b>سلة التسوق</b>\n"]
    rows: list[list[InlineKeyboardButton]] = []
    for item, sell in lines:
        pname = (item.product.name_ar if item.product else f"#{item.product_id}")
        text.append(_item_line(pname, item.quantity, sell))
        rows.append([InlineKeyboardButton(
            text=f"❌ {pname[:25]}", callback_data=f"store:cart_del:{item.id}", style="danger")])
    text.append(f"\n💳 <b>الإجمالي: {total}$</b> (رصيدك: {db_user.balance}$)")
    rows.append([InlineKeyboardButton(text="✅ إتمام الشراء (دفعة واحدة)", callback_data="store:checkout", style="primary")])
    rows.append([InlineKeyboardButton(text="🗑 إفراغ السلة", callback_data="store:cart_clear", style="danger")])
    rows.append([InlineKeyboardButton(text="🛍 متابعة التسوق", callback_data="store:home", style="success")])
    await callback.message.edit_text("\n".join(text), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("store:cart_del:"))
async def cart_delete(callback: CallbackQuery, session, db_user):
    await cart_service.remove_item(session, db_user.id, int(callback.data.rsplit(":", 1)[1]))
    await callback.answer("🗑 حُذف من السلة.")
    await cart_view(callback, session, db_user)


@router.callback_query(F.data == "store:cart_clear")
async def cart_clear(callback: CallbackQuery, session, db_user):
    await cart_service.clear(session, db_user.id)
    await callback.answer("🧺 أُفرغت السلة.")
    await cart_view(callback, session, db_user)


@router.callback_query(F.data == "store:checkout")
async def cart_checkout(callback: CallbackQuery, session, db_user, state: FSMContext):
    from services.store_order_service import place_store_order

    items = await cart_service.list_items(session, db_user.id)
    if not items:
        await callback.answer("السلة فارغة.", show_alert=True)
        return
    total, lines = await cart_service.totals(session, items, db_user)
    if not lines:
        await callback.answer("لا أصناف صالحة (عُطلت المنتجات).", show_alert=True)
        return
    if db_user.balance < total:
        await callback.answer(f"❌ رصيدك ({db_user.balance}$) لا يغطي الإجمالي ({total}$).", show_alert=True)
        return
    await callback.answer("⏳ جاري تنفيذ طلباتك...")
    data = await state.get_data()
    coupon = data.get("store_coupon") or {}
    ok_names, failed = [], []
    first = True
    for item, _sell in lines:
        order, msg = await place_store_order(
            session, callback.bot, db_user, item.product_id,
            item.target or "", str(item.quantity),
            coupon_kind=coupon.get("kind") if first else None,
            coupon_id=coupon.get("id") if first else None,
        )
        first = False
        pname = (item.product.name_ar[:30] if item.product else f"#{item.product_id}")
        if order:
            ok_names.append(f"✅ {pname} (#{order.id})")
            await cart_service.remove_item(session, db_user.id, item.id)
        else:
            failed.append(f"❌ {pname}: {msg[:80]}")
    await state.clear()
    text = ["🧾 <b>نتيجة إتمام السلة:</b>\n"] + ok_names + failed
    if failed:
        text.append("\nالأصناف الفاشلة بقيت بالسلة — راجع رصيدك وحاول مجدداً.")
    else:
        text.append("\n🎉 تم تنفيذ كل طلباتك بنجاح!")
    await callback.message.edit_text("\n".join(text), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧾 طلباتي", callback_data="store:myorders", style="primary")],
        [InlineKeyboardButton(text="🛍 المتجر", callback_data="store:home", style="success")],
    ]))
