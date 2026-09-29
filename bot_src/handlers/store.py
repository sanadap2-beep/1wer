"""
واجهة المتجر للزبون: تصفح الأقسام والشراء الديناميكي.

التدفق: store:home ← قسم ← فرع ← (فرع داخلي) ← منتج
← إدخال الهدف (رابط/Player ID/رقم 09) ← الكمية أو الفئة
← تأكيد السعر ← تنفيذ ← تتبع.
"""

from decimal import Decimal

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import desc, select

from database.models import ApiProvider, Category, CategoryType, Product, ProductStatus, ProviderService, SubCategory, UnifiedOrder
from services.dynamic_service import DynamicService
from services.store_order_service import (
    price_for,
    quantity_options_of,
    target_kind_of,
    validate_target,
)
from states.states import StoreStates

router = Router(name="store")

TARGET_NAMES = {"phone": "📱 رقم الهاتف", "player": "🎮 معرّف اللاعب", "link": "🔗 الرابط", "none": ""}
TARGET_SHORT = {"phone": "رقم", "player": "User ID", "link": "رابط", "none": "الهدف"}


async def _lux_ctx(session, db_user):
    """(سعر الصرف ل.س، سطر الرتبة أو None) لرسائل Lux."""
    from services.settings_service import SettingsService
    from services.trader_service import user_tier

    rate = await SettingsService.get_decimal("usd_to_syp_rate", Decimal("130"))
    rank = None
    try:
        tier = await user_tier(session, db_user.id)
        if tier.get("key") not in (None, "none"):
            rank = f"{tier.get('name')} — خصم {tier.get('discount')}%"
    except Exception:
        pass
    return rate, rank


def _back_home() -> list:
    return [[InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="back_to_main")]]


async def _home_kb(session, db_user=None) -> InlineKeyboardMarkup:
    result = await session.execute(
        select(Category)
        .where(Category.is_active.is_(True), Category.type != CategoryType.NUMBERS)
        .order_by(Category.sort_order, Category.id)
    )
    cats = list(result.scalars().all())
    rows = [[InlineKeyboardButton(text=f"{c.emoji} {c.name_ar}", callback_data=f"store:cat:{c.id}", style="success")] for c in cats]
    cart_label = "🧺 السلة"
    if db_user is not None:
        from services import cart_service as _cart

        items = await _cart.list_items(session, db_user.id)
        if items:
            cart_label = f"🧺 السلة ({len(items)})"
    rows.append([InlineKeyboardButton(text=cart_label, callback_data="store:cart", style="primary")])
    from services.offer_service import list_active as _active_offers

    if await _active_offers(session):
        rows.append([InlineKeyboardButton(text="🔥 العروض المؤقتة", callback_data="store:deals", style="success")])
    rows.append([InlineKeyboardButton(text="🧾 طلباتي", callback_data="store:myorders", style="primary")])
    rows.extend(_back_home())
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "store:home")
async def store_home(callback: CallbackQuery, session, state: FSMContext, db_user):
    await callback.answer()
    await state.clear()
    try:
        await callback.message.edit_text(
            "🛍 <b>المتجر</b>\n\nاختر القسم:",
            reply_markup=await _home_kb(session, db_user),
        )
    except Exception:
        await callback.message.answer("🛍 <b>المتجر</b>", reply_markup=await _home_kb(session, db_user))


@router.callback_query(F.data.startswith("store:cat:"))
async def store_cat(callback: CallbackQuery, session, state: FSMContext):
    await state.clear()
    cid = int(callback.data.rsplit(":", 1)[1])
    cat = await DynamicService.get_category(session, cid)
    if not cat or not cat.is_active:
        await callback.answer("⚠️ القسم غير متوفر.", show_alert=True)
        return
    subs = await DynamicService.get_active_root_sub_categories(session, cid)
    if not subs:
        await callback.answer("⚠️ لا توجد فروع بعد.", show_alert=True)
        return
    rows = [[InlineKeyboardButton(text=f"{s.emoji} {s.name_ar}", callback_data=f"store:sub:{s.id}", style="success")] for s in subs]
    rows.append([InlineKeyboardButton(text="🔙 المتجر", callback_data="store:home", style="success")])
    await callback.message.edit_text(
        f"{cat.emoji} <b>{cat.name_ar}</b>\n\n{cat.description or 'اختر الفرع:'}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("store:sub:"))
async def store_sub(callback: CallbackQuery, session, state: FSMContext):
    await state.clear()
    sid = int(callback.data.rsplit(":", 1)[1])
    sub = await DynamicService.get_sub_category(session, sid)
    if not sub or not sub.is_active:
        await callback.answer("⚠️ غير متوفر.", show_alert=True)
        return
    children = await DynamicService.get_active_child_sections(session, sid)
    products = [p for p in (sub.products or []) if p.status == ProductStatus.ACTIVE]
    rows: list[list[InlineKeyboardButton]] = []
    text = f"{sub.emoji} <b>{sub.name_ar}</b>\n"
    if sub.description:
        text += f"\n{sub.description}\n"
    if children:
        text += "\nاختر النوع:"
        for ch in children:
            rows.append([InlineKeyboardButton(text=f"{ch.emoji} {ch.name_ar}", callback_data=f"store:sub:{ch.id}", style="success")])
    if products:
        if children:
            text += "\n\nمنتجات مباشرة:"
        else:
            text += "\nاختر المنتج:"
        for p in products:
            rows.append([InlineKeyboardButton(
                text=f"📦 {p.name_ar[:35]} — {p.price_usd}$",
                callback_data=f"store:prod:{p.id}", style="success",
            )])
    if not children and not products:
        text += "\n⚠️ لا توجد منتجات هنا بعد."
    back = f"store:sub:{sub.parent_sub_category_id}" if sub.parent_sub_category_id else f"store:cat:{sub.category_id}"
    rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data=back)])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("store:prod:"))
async def store_product(callback: CallbackQuery, session, db_user, state: FSMContext = None):
    if state is not None:
        await state.clear()
    pid = int(callback.data.rsplit(":", 1)[1])
    p = await DynamicService.get_product(session, pid)
    if not p or p.status != ProductStatus.ACTIVE:
        await callback.answer("⚠️ المنتج غير متوفر.", show_alert=True)
        return
    ps = await session.get(ProviderService, p.provider_service_ref_id) if p.provider_service_ref_id else None
    kind = target_kind_of(p, ps)
    from services.currency_service import CurrencyService
    from handlers.reviews import product_rating

    avg, count = await product_rating(session, p.id)
    price_display = await CurrencyService.format_dual(p.price_usd, db_user, session)
    lines = [
        f"📦 <b>{p.name_ar}</b>\n",
        f"💰 السعر: <b>{price_display}</b>",
    ]
    if count:
        lines.append(f"⭐ التقييم: <b>{avg:.1f}</b> ({count})")
    _rate, _rank = await _lux_ctx(session, db_user)
    if _rank:
        lines.append(f"👑 مستوى حسابك: {_rank}")
    if p.display_type.value == "per_1000":
        lines.append("(السعر لكل 1000 وحدة)")
    if p.description:
        lines.append(f"\n{p.description[:300]}")
    if p.estimated_time:
        lines.append(f"\n⏱ المدة التقريبية: {p.estimated_time}")
    if p.requires_quantity:
        lines.append(f"📊 الكمية: من {p.min_quantity} إلى {p.max_quantity}")
    if kind != "none":
        lines.append(f"📝 المطلوب: {TARGET_NAMES.get(kind, 'الهدف')}")
    from handlers.watch import is_watching as _is_watching

    watching = await _is_watching(session, db_user.id, p.id)
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 شراء الآن", callback_data=f"store:buy:{p.id}", style="success")],
        [InlineKeyboardButton(
            text="🔕 إلغاء التنبيه" if watching else "🔔 نبهني عند تغير السعر",
            callback_data=f"watch:toggle:{p.id}")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data=f"store:sub:{p.sub_category_id}")],
    ]))
    await callback.answer()


@router.callback_query(F.data.startswith("store:buy:"))
async def store_buy(callback: CallbackQuery, session, state: FSMContext, db_user):
    pid = int(callback.data.rsplit(":", 1)[1])
    p = await DynamicService.get_product(session, pid)
    if not p or p.status != ProductStatus.ACTIVE:
        await callback.answer("⚠️ المنتج غير متوفر.", show_alert=True)
        return
    await state.update_data(store_prod=pid)
    ps = await session.get(ProviderService, p.provider_service_ref_id) if p.provider_service_ref_id else None
    kind = target_kind_of(p, ps)
    await state.update_data(store_kind=kind)
    if kind != "none":
        hint = {
            "phone": "📱 أرسل رقم الهاتف (سوري — يبدأ بـ <code>09</code>):",
            "player": "🎮 أرسل معرّف اللاعب (Player ID):",
            "link": "🔗 أرسل الرابط:",
        }[kind]
        from services.message_style import SEP

        await callback.message.edit_text(
            f"📦 <b>{p.name_ar}</b>\n\n{hint}\n\n"
            f"👇🏻 أدخـل {TARGET_SHORT.get(kind, 'الـهـدف')}\n{SEP}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ إلغاء", callback_data=f"store:prod:{pid}", style="danger")]
            ]),
        )
        await state.set_state(StoreStates.waiting_target)
    else:
        await _ask_quantity(callback.message, state, session, p, ps, edit=True, db_user=db_user)
    await callback.answer()


@router.message(StoreStates.waiting_target)
async def store_target_received(message: Message, state: FSMContext, session, db_user):
    data = await state.get_data()
    kind = data.get("store_kind", "link")
    ok, value_or_err = validate_target(kind, message.text or "")
    if not ok:
        await message.answer(value_or_err)
        return
    await state.update_data(store_target=value_or_err)
    p = await DynamicService.get_product(session, int(data["store_prod"]))
    ps = await session.get(ProviderService, p.provider_service_ref_id) if p.provider_service_ref_id else None
    await _ask_quantity(message, state, session, p, ps, edit=False, db_user=db_user)


async def _ask_quantity(message, state, session, p, ps, edit: bool, db_user=None):
    opts = quantity_options_of(ps)
    if opts:
        # فئات ثابتة — أزرار (10 في كل رسالة)
        shown = opts[:20]
        rows = []
        row: list[InlineKeyboardButton] = []
        for o in shown:
            _c, sell, _m = await price_for(session, p, o, db_user)
            row.append(InlineKeyboardButton(text=f"{o} = {sell}$", callback_data=f"store:qty:{p.id}:{o}", style="success"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(text="❌ إلغاء", callback_data=f"store:prod:{p.id}", style="danger")])
        text = f"📦 <b>{p.name_ar}</b>\n\nاختر الفئة ({len(opts)} فئة متاحة):"
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        # إبقاء البيانات مع تصفير الحالة: الاختيار عبر الأزرار فقط
        try:
            await state.set_state(None)
        except Exception:
            pass
        if edit:
            try:
                await message.edit_text(text, reply_markup=kb)
            except Exception:
                await message.answer(text, reply_markup=kb)
        else:
            await message.answer(text, reply_markup=kb)
        return
    if p.requires_quantity:
        await state.set_state(StoreStates.waiting_quantity)
        text = (
            f"📦 <b>{p.name_ar}</b>\n\n"
            f"📊 أرسل الكمية المطلوبة (من {p.min_quantity} إلى {p.max_quantity}):"
        )
        if edit:
            try:
                await message.edit_text(text)
            except Exception:
                await message.answer(text)
        else:
            await message.answer(text)
        return
    # بدون كمية: تأكيد مباشر
    await state.update_data(store_qty="1")
    await _show_confirm(message, state, session, p, edit=edit, db_user=db_user)


@router.callback_query(F.data.startswith("store:qty:"))
async def store_qty_picked(callback: CallbackQuery, state: FSMContext, session, db_user):
    _, _, pid, qty = callback.data.split(":", 3)
    await state.update_data(store_prod=int(pid), store_qty=qty)
    p = await DynamicService.get_product(session, int(pid))
    await _show_confirm(callback.message, state, session, p, edit=True, db_user=db_user)
    await callback.answer()


@router.message(StoreStates.waiting_quantity)
async def store_quantity_received(message: Message, state: FSMContext, session, db_user):
    data = await state.get_data()
    p = await DynamicService.get_product(session, int(data["store_prod"]))
    try:
        qty = int((message.text or "").strip())
    except (ValueError, TypeError):
        await message.answer("⚠️ أرسل رقماً صحيحاً فقط.")
        return
    if qty < p.min_quantity or qty > p.max_quantity:
        await message.answer(f"⚠️ الكمية يجب أن تكون بين {p.min_quantity} و {p.max_quantity}.")
        return
    await state.update_data(store_qty=str(qty))
    await _show_confirm(message, state, session, p, edit=False, db_user=db_user)


async def _show_confirm(message, state, session, p, edit: bool, db_user=None):
    data = await state.get_data()
    qty = data.get("store_qty", "1")
    target = data.get("store_target", "")
    cost, sell, _margin = await price_for(session, p, qty, db_user)
    coupon = data.get("store_coupon") or {}
    discount = Decimal(str(coupon.get("discount", "0") or "0"))
    if discount > sell:
        discount = sell
    total = (sell - discount).quantize(Decimal("0.0001"))
    from services.message_style import confirm_order, dual

    _rate, _ = await _lux_ctx(session, db_user)
    _kind = data.get("store_kind", "link")
    text = confirm_order(
        product=p.name_ar, qty=qty,
        target_label=TARGET_SHORT.get(_kind, "رابط"),
        target=target or "—",
        before_dual=dual(sell, _rate), after_dual=dual(total, _rate),
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تأكيد الشراء", callback_data="store:confirm", style="primary")],
        [InlineKeyboardButton(text="🎟 عندي كوبون", callback_data=f"store:coupon:{p.id}", style="primary")],
        [InlineKeyboardButton(text="🧺 أضف للسلة بدل الشراء", callback_data=f"store:cart_add:{p.id}", style="success")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data=f"store:prod:{p.id}", style="danger")],
    ])
    text = "\n".join(l for l in lines if l)
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
        except Exception:
            await message.answer(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("store:coupon:"))
async def store_coupon_start(callback: CallbackQuery, state: FSMContext, session):
    pid = int(callback.data.rsplit(":", 1)[1])
    await state.update_data(store_prod=pid)
    await callback.message.edit_text(
        "🎟 أرسل كود الكوبون (مثال: <code>WELCOME20</code>):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ تراجع", callback_data=f"store:prod:{pid}", style="danger")]
        ]),
    )
    await state.set_state(StoreStates.waiting_coupon)
    await callback.answer()


@router.message(StoreStates.waiting_coupon)
async def store_coupon_received(message: Message, state: FSMContext, session, db_user):
    from services import coupon_service as _coupons

    data = await state.get_data()
    pid = int(data.get("store_prod", 0))
    code = (message.text or "").strip().upper()
    p = await DynamicService.get_product(session, pid)
    if not p:
        await state.clear()
        await message.answer("⚠️ انتهت الجلسة.")
        return
    qty = data.get("store_qty", "1")
    _cost, sell, _m = await price_for(session, p, qty, db_user)
    for kind in ("coupon", "campaign"):
        ok, row, discount, msg = await _coupons.validate(session, kind, code, db_user.id, sell)
        if ok:
            await state.update_data(store_coupon={"kind": kind, "id": row.id, "code": row.code, "discount": str(discount)})
            await message.answer(msg)
            await _show_confirm(message, state, session, p, edit=False, db_user=db_user)
            return
    await message.answer("⚠️ الكود غير صالح أو منتهي — تحقق منه وحاول مجدداً.")


@router.callback_query(F.data == "store:confirm")
async def store_confirm(callback: CallbackQuery, session, db_user, state: FSMContext):
    from services.store_order_service import place_store_order

    data = await state.get_data()
    pid, target, qty = int(data.get("store_prod", 0)), data.get("store_target", ""), data.get("store_qty", "1")
    coupon = data.get("store_coupon") or {}
    if not pid:
        await callback.answer("⚠️ انتهت الجلسة — ابدأ من جديد.", show_alert=True)
        return
    await callback.answer("⏳ جاري تنفيذ طلبك...")
    order, msg = await place_store_order(
        session, callback.bot, db_user, pid, target, qty,
        coupon_kind=coupon.get("kind"), coupon_id=coupon.get("id"),
    )
    await state.clear()
    if order is None:
        try:
            await callback.message.edit_text(msg)
        except Exception:
            await callback.message.answer(msg)
        return
    from services.message_style import SEP as _SEP

    try:
        await callback.message.edit_text(
            f"✅ تـم إرسـال طـلـبـك بـنـجـاح!\n{_SEP}\n\n"
            f"🆔 رقم الطلب: <code>{order.external_order_id or order.id}</code>\n"
            f"💰 المبلغ: <b>{order.price_usd}$</b>\n\n"
            "تابع حالته من 🧾 طلباتي.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧾 طلباتي", callback_data="store:myorders", style="primary")],
                [InlineKeyboardButton(text="🛍 المتجر", callback_data="store:home", style="success")],
            ]),
        )
    except Exception:
        await callback.message.answer(f"✅ تم إرسال طلبك! رقم الطلب: {order.id}")


@router.callback_query(F.data.startswith("refill:uni:"))
async def store_refill(callback: CallbackQuery, session, db_user):
    """طلب إعادة تعبئة لطلب رشق مكتمل (إن دعم المزود)."""
    from protocols.factory import ProtocolFactory

    order_id = int(callback.data.rsplit(":", 1)[1])
    order = await session.get(UnifiedOrder, order_id)
    if not order or order.user_id != db_user.id:
        await callback.answer("⚠️ غير موجود.", show_alert=True)
        return
    if order.status.value != "completed" or not order.external_order_id or not order.api_provider_id:
        await callback.answer("⚠️ إعادة التعبئة للطلبات المكتملة عبر المزود فقط.", show_alert=True)
        return
    provider = await session.get(ApiProvider, order.api_provider_id)
    if provider is None or not provider.is_active:
        await callback.answer("⚠️ المزود غير متوفر.", show_alert=True)
        return
    await callback.answer("⏳ جاري إرسال طلب التعبئة...")
    try:
        protocol = ProtocolFactory.create_from_provider(provider)
        ok = await protocol.refill_order(order.external_order_id)
    except Exception as exc:
        await callback.answer(f"❌ فشل: {str(exc)[:100]}", show_alert=True)
        return
    if not ok:
        await callback.answer("⚠️ المزود لا يدعم إعادة التعبئة لهذا الطلب.", show_alert=True)
        return
    order.refill_attempts = (order.refill_attempts or 0) + 1
    order.status_message = "طُلبت إعادة تعبئة ✅"
    await session.commit()
    await callback.message.answer(f"🔁 تم إرسال طلب إعادة تعبئة للطلب <b>#{order.id}</b> بنجاح.")
    await callback.answer("✅ تم الإرسال")


@router.callback_query(F.data == "store:myorders")
async def store_myorders(callback: CallbackQuery, session, db_user):
    result = await session.execute(
        select(UnifiedOrder).where(UnifiedOrder.user_id == db_user.id)
        .order_by(desc(UnifiedOrder.created_at)).limit(8)
    )
    orders = list(result.scalars().all())
    if not orders:
        await callback.answer("لا توجد طلبات بعد.", show_alert=True)
        return
    status_ar = {
        "pending": "⏳ بانتظار", "processing": "🔄 قيد التنفيذ", "completed": "✅ مكتمل",
        "failed": "❌ فشل", "refunded": "↩️ مسترجع", "partial": "⚠️ جزئي",
    }
    lines = ["🧾 <b>آخر طلباتك:</b>\n"]
    for o in orders:
        pname = f"#{o.product_id}" if o.product_id else "متجر"
        if o.product_id:
            prod = await session.get(Product, o.product_id)
            if prod:
                pname = prod.name_ar[:25]
        st = status_ar.get(o.status.value, o.status.value)
        lines.append(f"\n🆔 #{o.id} | {pname}\n{st} | {o.price_usd}$ | {o.created_at.strftime('%Y-%m-%d')}")
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 المتجر", callback_data="store:home", style="success")],
        [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="back_to_main")],
    ]))
    await callback.answer()
