"""
واجهة المتجر للزبون: تصفح الأقسام والشراء الديناميكي.

التدفق: store:home ← قسم ← فرع ← (فرع داخلي) ← منتج
← إدخال الهدف (رابط/Player ID/رقم 09) ← الكمية أو الفئة
← تأكيد السعر ← تنفيذ ← تتبع.
"""

from decimal import Decimal
from html import escape

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

from database.models import ApiProvider, Category, CategoryType, DigitalInventoryItem, InventoryItemStatus, Product, ProductGift, ProductGiftStatus, ProductStatus, ProviderService, SubCategory, UnifiedOrder, User
from services.dynamic_service import DynamicService
from services.inventory_service import InventoryError, InventoryService
from services.store_order_service import (
    price_for,
    quantity_options_of,
    target_kind_of,
    validate_target,
)
from states.states import ProductGiftStates, StoreStates

router = Router(name="store")

TARGET_NAMES = {"phone": "📱 رقم الهاتف", "player": "🎮 معرّف اللاعب", "link": "🔗 الرابط", "none": ""}
TARGET_SHORT = {"phone": "رقم", "player": "User ID", "link": "رابط", "none": "الهدف"}

PAGE_SIZE = 20


async def _direct_product_count(session, sub_id: int) -> int:
    from sqlalchemy import func as _func

    result = await session.execute(
        select(_func.count(Product.id)).where(
            Product.sub_category_id == sub_id, Product.status == ProductStatus.ACTIVE)
    )
    return int(result.scalar_one() or 0)


async def _sub_has_content(session, sub_id: int, depth: int = 2) -> bool:
    """الفرع يستحق الظهور؟ فيه منتجات مفعّلة أو فروع ناشطة تحته."""
    if await _direct_product_count(session, sub_id) > 0:
        return True
    if depth <= 0:
        return False
    result = await session.execute(select(SubCategory.id).where(
        SubCategory.parent_sub_category_id == sub_id, SubCategory.is_active.is_(True)))
    for (child_id,) in result.all():
        if await _sub_has_content(session, int(child_id), depth - 1):
            return True
    return False


async def _visible_children(session, parent_id: int) -> list:
    result = await session.execute(select(SubCategory).where(
        SubCategory.parent_sub_category_id == parent_id,
        SubCategory.is_active.is_(True)).order_by(SubCategory.sort_order, SubCategory.id))
    return [s for s in result.scalars().all() if await _sub_has_content(session, s.id)]


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
    # المتجر = 4 أقسام فقط: ألعاب / تطبيقات / رشق / أرصدة
    result = await session.execute(
        select(Category)
        .where(
            Category.is_active.is_(True),
            Category.type.in_([CategoryType.GAMES, CategoryType.APPS, CategoryType.SMM, CategoryType.BALANCES]),
        )
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
    parts = callback.data.split(":")
    cid = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    cat = await DynamicService.get_category(session, cid)
    if not cat or not cat.is_active:
        await callback.answer("⚠️ القسم غير متوفر.", show_alert=True)
        return
    subs = await DynamicService.get_active_root_sub_categories(session, cid)
    subs = [s for s in subs if await _sub_has_content(session, s.id)]
    if not subs:
        await callback.answer("⚠️ لا توجد فروع بعد.", show_alert=True)
        return
    total_pages = max(1, (len(subs) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = subs[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for s in chunk:
        pair.append(InlineKeyboardButton(text=f"{s.emoji} {s.name_ar}", callback_data=f"store:sub:{s.id}", style="success"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀ السابق", callback_data=f"store:cat:{cid}:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="التالي ▶", callback_data=f"store:cat:{cid}:{page + 1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔍 ما لقيت لعبتك / برنامجك؟", callback_data=f"store:find:{cid}", style="primary")])
    rows.append([InlineKeyboardButton(text="🔙 المتجر", callback_data="store:home", style="success")])
    await callback.message.edit_text(
        f"{cat.emoji} <b>{cat.name_ar}</b>\n\n{cat.description or 'اختر الفرع:'}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("store:sub:"))
async def store_sub(callback: CallbackQuery, session, state: FSMContext):
    await state.clear()
    parts = callback.data.split(":")
    sid = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    sub = await DynamicService.get_sub_category(session, sid)
    if not sub or not sub.is_active:
        await callback.answer("⚠️ غير متوفر.", show_alert=True)
        return
    children = await _visible_children(session, sid)
    # المنتجات: 20 بكل صفحة (صفين)
    from sqlalchemy import func as _func

    total_result = await session.execute(select(_func.count(Product.id)).where(
        Product.sub_category_id == sid, Product.status == ProductStatus.ACTIVE))
    total = int(total_result.scalar_one() or 0)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    prod_result = await session.execute(select(Product).where(
        Product.sub_category_id == sid, Product.status == ProductStatus.ACTIVE
    ).order_by(Product.sort_order, Product.id).limit(PAGE_SIZE).offset(page * PAGE_SIZE))
    products = list(prod_result.scalars().all())

    rows: list[list[InlineKeyboardButton]] = []
    text = f"{sub.emoji} <b>{sub.name_ar}</b>\n"
    if sub.description:
        text += f"\n{sub.description}\n"
    if children:
        text += "\nاختر النوع:"
        crow: list[InlineKeyboardButton] = []
        for ch in children:
            crow.append(InlineKeyboardButton(text=f"{ch.emoji} {ch.name_ar}", callback_data=f"store:sub:{ch.id}", style="success"))
            if len(crow) == 2:
                rows.append(crow)
                crow = []
        if crow:
            rows.append(crow)
    if products:
        text += "\n\nاختر المنتج:" if children else "\nاختر المنتج:"
        prow: list[InlineKeyboardButton] = []
        for p in products:
            prow.append(InlineKeyboardButton(
                text=f"{p.name_ar[:28]} — {p.price_usd}$",
                callback_data=f"store:prod:{p.id}", style="success",
            ))
            if len(prow) == 2:
                rows.append(prow)
                prow = []
        if prow:
            rows.append(prow)
        if total_pages > 1:
            nav: list[InlineKeyboardButton] = []
            if page > 0:
                nav.append(InlineKeyboardButton(text="◀ السابق", callback_data=f"store:sub:{sid}:{page - 1}"))
            nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
            if page < total_pages - 1:
                nav.append(InlineKeyboardButton(text="التالي ▶", callback_data=f"store:sub:{sid}:{page + 1}"))
            rows.append(nav)
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
        f"🛍 <b>{p.name_ar}</b>\n",
    ]
    if p.display_type.value == "per_1000":
        lines.append(f"💵 السعر لكل 1000: <b>{price_display}</b>")
    else:
        lines.append(f"💰 السعر: <b>{price_display}</b>")
    
    if count:
        lines.append(f"⭐ التقييم: <b>{avg:.1f}</b> ({count})")
    _rate, _rank = await _lux_ctx(session, db_user)
    if _rank:
        lines.append(f"👑 مستوى حسابك: {_rank}")
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
    product_buttons = [
        [InlineKeyboardButton(text="🛒 شراء الآن", callback_data=f"store:buy:{p.id}", style="success")],
    ]
    from services.product_gift_service import ProductGiftService

    if ProductGiftService.is_giftable(p):
        product_buttons.append([
            InlineKeyboardButton(text="🎁 إهداء هذا المنتج", callback_data=f"gift:create:{p.id}", style="primary")
        ])
    product_buttons.extend([
        [InlineKeyboardButton(
            text="🔕 إلغاء التنبيه" if watching else "🔔 نبهني عند تغير السعر",
            callback_data=f"watch:toggle:{p.id}")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data=f"store:sub:{p.sub_category_id}")],
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=product_buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("gift:create:"))
async def product_gift_start(callback: CallbackQuery, state: FSMContext, session):
    from services.product_gift_service import ProductGiftService

    product_id = int(callback.data.rsplit(":", 1)[1])
    product = await DynamicService.get_product(session, product_id)
    if not product or product.status != ProductStatus.ACTIVE or not ProductGiftService.is_giftable(product):
        await callback.answer("⚠️ يمكن إهداء الأكواد والاشتراكات الرقمية من المخزون فقط.", show_alert=True)
        return
    stock = await InventoryService.available_count(session, product_id)
    if stock < 1:
        await callback.answer("⚠️ لا يوجد مخزون متاح لهذا المنتج.", show_alert=True)
        return
    await state.clear()
    await state.update_data(gift_product_id=product_id)
    await state.set_state(ProductGiftStates.waiting_recipient)
    await callback.answer()
    await callback.message.edit_text(
        f"🎁 <b>إهداء {escape(product.name_ar)}</b>\n\n"
        "أرسل اسم المستخدم في تيليجرام (مع أو بدون @) أو رقم تيليجرام للمستفيد.\n"
        "يجب أن يكون لديه حساب مسجل في البوت.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ إلغاء", callback_data="gift:cancel_create")]
        ]),
    )


@router.message(ProductGiftStates.waiting_recipient)
async def product_gift_recipient_received(message: Message, state: FSMContext, session, db_user):
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("⚠️ أرسل اسم المستخدم أو رقم تيليجرام.")
        return

    if raw.isdecimal():
        recipient = (
            await session.execute(select(User).where(User.telegram_id == int(raw)))
        ).scalar_one_or_none()
    else:
        username = raw.lstrip("@").strip().casefold()
        matches = list(
            (
                await session.execute(
                    select(User).where(func.lower(User.username) == username).limit(2)
                )
            ).scalars().all()
        )
        recipient = matches[0] if len(matches) == 1 else None
        if len(matches) > 1:
            await message.answer("⚠️ اسم المستخدم غير فريد في قاعدة الحسابات. أرسل رقم تيليجرام بدلاً منه.")
            return

    if recipient is None:
        await message.answer("⚠️ لم أجد حساباً مسجلاً بهذا الاسم أو الرقم. تحقق منه وحاول مجدداً.")
        return
    if recipient.id == db_user.id or recipient.is_banned:
        await message.answer("⚠️ اختر مستفيداً آخر مسجلاً في البوت.")
        return

    data = await state.get_data()
    product_id = int(data.get("gift_product_id", 0))
    product = await DynamicService.get_product(session, product_id)
    from services.product_gift_service import ProductGiftService

    if not product or product.status != ProductStatus.ACTIVE or not ProductGiftService.is_giftable(product):
        await state.clear()
        await message.answer("⚠️ انتهت صلاحية المنتج. ابدأ من صفحة المنتج مجدداً.")
        return
    _cost, price, _margin = await price_for(session, product, "1", db_user)
    await state.update_data(gift_recipient_id=recipient.id)
    await state.set_state(ProductGiftStates.confirming_purchase)
    recipient_name = recipient.full_name or (f"@{recipient.username}" if recipient.username else str(recipient.telegram_id))
    await message.answer(
        f"🎁 <b>تأكيد الهدية</b>\n\n"
        f"📦 المنتج: <b>{escape(product.name_ar)}</b>\n"
        f"👤 المستفيد: <b>{escape(recipient_name)}</b>\n"
        f"💰 السعر: <b>{price}$</b>\n\n"
        "سيُخصم المبلغ من رصيدك، ولا يظهر الكود إلا للمستفيد بعد استلامه.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ شراء وإرسال الهدية", callback_data="gift:confirm", style="success")],
            [InlineKeyboardButton(text="❌ إلغاء", callback_data="gift:cancel_create")],
        ]),
    )


@router.callback_query(F.data == "gift:cancel_create")
async def product_gift_cancel_create(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("تم إلغاء الإهداء.")
    await callback.message.edit_text("تم إلغاء الإهداء. يمكنك الرجوع إلى المتجر.", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🏠 المتجر", callback_data="store:home")]]
    ))


@router.callback_query(F.data == "gift:confirm", ProductGiftStates.confirming_purchase)
async def product_gift_confirm(callback: CallbackQuery, state: FSMContext, session, db_user):
    from services.product_gift_service import ProductGiftError, ProductGiftService

    data = await state.get_data()
    product_id = int(data.get("gift_product_id", 0))
    recipient_id = int(data.get("gift_recipient_id", 0))
    product = await DynamicService.get_product(session, product_id)
    recipient = await session.get(User, recipient_id)
    if not product or not recipient:
        await state.clear()
        await callback.answer("⚠️ انتهت صلاحية العملية. ابدأ من جديد.", show_alert=True)
        return
    _cost, price, _margin = await price_for(session, product, "1", db_user)
    try:
        gift, _order = await ProductGiftService.create(
            session, db_user.id, recipient.id, product_id, price
        )
    except ProductGiftError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await state.clear()
    recipient_name = recipient.full_name or (f"@{recipient.username}" if recipient.username else str(recipient.telegram_id))
    await callback.answer("تم شراء الهدية.")
    await callback.message.edit_text(
        f"✅ <b>تم شراء الهدية #{gift.id}</b>\n\n"
        f"📦 {escape(product.name_ar)}\n"
        f"👤 المستفيد: {escape(recipient_name)}\n"
        f"💰 المبلغ: {price}$\n\n"
        "أرسلنا إشعاراً للمستفيد إن كان البوت متاحاً لديه. يمكنك متابعة الهدية أو إلغاؤها قبل استلامها من قسم «هداياي» في حسابك.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 هداياي", callback_data="gift:hub")],
            [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="back_to_main")],
        ]),
    )
    try:
        await callback.bot.send_message(
            recipient.telegram_id,
            f"🎁 <b>لديك هدية جديدة من {escape(db_user.full_name or 'أحد المستخدمين')}</b>\n\n"
            f"📦 {escape(product.name_ar)}\nاضغط لعرضها واستلامها:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎁 عرض الهدية", callback_data=f"gift:view:{gift.id}")]
            ]),
        )
    except Exception:
        # المستفيد يستطيع فتح الهدية من حسابه حتى لو تعذر إرسال الرسالة الخاصة.
        pass


@router.callback_query(F.data == "gift:hub")
async def product_gift_hub(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "🎁 <b>الهدايا الرقمية</b>\n\nاختر الهدايا الواردة إليك أو التي أرسلتها:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 الهدايا الواردة", callback_data="gift:inbox")],
            [InlineKeyboardButton(text="📤 الهدايا المرسلة", callback_data="gift:sent")],
            [InlineKeyboardButton(text="🔙 حسابي", callback_data="menu:account")],
        ]),
    )


async def _render_product_gifts(callback: CallbackQuery, session, db_user, sent: bool):
    query = select(ProductGift).options(
        selectinload(ProductGift.product),
        selectinload(ProductGift.sender),
        selectinload(ProductGift.recipient),
    )
    if sent:
        query = query.where(ProductGift.sender_user_id == db_user.id)
    else:
        query = query.where(ProductGift.recipient_user_id == db_user.id)
    result = await session.execute(query.order_by(ProductGift.created_at.desc()).limit(30))
    gifts = list(result.scalars().all())
    title = "📤 <b>الهدايا التي أرسلتها</b>" if sent else "📥 <b>الهدايا الواردة</b>"
    if not gifts:
        await callback.answer()
        await callback.message.edit_text(
            f"{title}\n\nلا توجد هدايا هنا بعد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 الهدايا", callback_data="gift:hub")]
            ]),
        )
        return

    labels = {
        ProductGiftStatus.PENDING: "بانتظار الاستلام",
        ProductGiftStatus.CLAIMED: "تم الاستلام",
        ProductGiftStatus.CANCELLED: "ملغاة",
    }
    lines = [title, ""]
    buttons = []
    for gift in gifts:
        product_name = gift.product.name_ar if gift.product else "منتج رقمي"
        counterparty = gift.recipient if sent else gift.sender
        counterparty_name = (
            (counterparty.full_name or (f"@{counterparty.username}" if counterparty.username else "مستخدم"))
            if counterparty
            else "مستخدم"
        )
        lines.append(
            f"🎁 #{gift.id} · {escape(product_name[:45])} · "
            f"{labels.get(gift.status, gift.status.value)} · {escape(counterparty_name[:40])}"
        )
        buttons.append([
            InlineKeyboardButton(text=f"عرض الهدية #{gift.id}", callback_data=f"gift:view:{gift.id}")
        ])
    buttons.append([
        InlineKeyboardButton(text="🔙 الهدايا", callback_data="gift:hub"),
        InlineKeyboardButton(text="👤 حسابي", callback_data="menu:account"),
    ])
    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data == "gift:inbox")
async def product_gift_inbox(callback: CallbackQuery, session, db_user):
    await _render_product_gifts(callback, session, db_user, sent=False)


@router.callback_query(F.data == "gift:sent")
async def product_gift_sent(callback: CallbackQuery, session, db_user):
    await _render_product_gifts(callback, session, db_user, sent=True)


async def _get_product_gift(session, gift_id: int):
    return (
        await session.execute(
            select(ProductGift)
            .options(
                selectinload(ProductGift.product),
                selectinload(ProductGift.sender),
                selectinload(ProductGift.recipient),
            )
            .where(ProductGift.id == gift_id)
        )
    ).scalar_one_or_none()


async def _render_product_gift_detail(callback: CallbackQuery, session, gift, db_user):
    is_sender = gift.sender_user_id == db_user.id
    product_name = gift.product.name_ar if gift.product else "منتج رقمي"
    status_label = {
        ProductGiftStatus.PENDING: "🕒 بانتظار استلام المستفيد",
        ProductGiftStatus.CLAIMED: "✅ تم استلام الهدية",
        ProductGiftStatus.CANCELLED: "↩️ أُلغيت وأُعيد المبلغ",
    }.get(gift.status, gift.status.value)
    if is_sender:
        recipient_name = (
            gift.recipient.full_name
            or (f"@{gift.recipient.username}" if gift.recipient.username else str(gift.recipient.telegram_id))
        ) if gift.recipient else "المستفيد"
        text = (
            f"🎁 <b>الهدية #{gift.id}</b>\n\n"
            f"📦 المنتج: <b>{escape(product_name)}</b>\n"
            f"👤 المستفيد: <b>{escape(recipient_name)}</b>\n"
            f"📊 الحالة: {status_label}\n"
            "🔒 رمز المنتج لا يظهر إلا للمستفيد."
        )
        buttons = []
        if gift.status == ProductGiftStatus.PENDING:
            buttons.append([InlineKeyboardButton(
                text="↩️ إلغاء الهدية واسترجاع المبلغ",
                callback_data=f"gift:cancel_confirm:{gift.id}",
            )])
        buttons.append([InlineKeyboardButton(text="📤 هداياي المرسلة", callback_data="gift:sent")])
    else:
        sender_name = (
            gift.sender.full_name
            or (f"@{gift.sender.username}" if gift.sender.username else "أحد المستخدمين")
        ) if gift.sender else "أحد المستخدمين"
        text = (
            f"🎁 <b>هدية #{gift.id}</b>\n\n"
            f"📦 المنتج: <b>{escape(product_name)}</b>\n"
            f"👤 من: <b>{escape(sender_name)}</b>\n"
            f"📊 الحالة: {status_label}"
        )
        buttons = []
        if gift.status == ProductGiftStatus.PENDING:
            buttons.append([InlineKeyboardButton(
                text="🎁 استلام الهدية",
                callback_data=f"gift:claim:{gift.id}",
                style="success",
            )])
        elif gift.status == ProductGiftStatus.CLAIMED:
            buttons.append([InlineKeyboardButton(
                text="📋 عرض الرمز الرقمي",
                callback_data=f"gift:reveal:{gift.id}",
            )])
        if gift.status != ProductGiftStatus.CANCELLED:
            buttons.append([InlineKeyboardButton(
                text="🛠 أواجه مشكلة في الهدية",
                callback_data=f"support:order:unified:{gift.unified_order_id}",
            )])
        buttons.append([InlineKeyboardButton(text="📥 هداياي الواردة", callback_data="gift:inbox")])
    buttons.append([InlineKeyboardButton(text="🔙 الهدايا", callback_data="gift:hub")])
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def _send_product_gift_value(callback: CallbackQuery, session, gift):
    item = await session.get(DigitalInventoryItem, gift.inventory_item_id)
    if item is None:
        await callback.message.answer("⚠️ تعذر العثور على رمز الهدية. أبلغ الدعم برقمها.")
        return
    try:
        value = InventoryService.decrypt_value(item.encrypted_value)
    except InventoryError:
        await callback.message.answer("⚠️ تعذر عرض الرمز الآن. أبلغ الدعم برقم الهدية.")
        return
    await callback.message.answer(
        f"🎁 رمز الهدية #{gift.id}:\n\n{value}",
        parse_mode=None,
    )


@router.callback_query(F.data.startswith("gift:view:"))
async def product_gift_view(callback: CallbackQuery, session, db_user):
    try:
        gift_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("⚠️ رقم الهدية غير صالح.", show_alert=True)
        return
    gift = await _get_product_gift(session, gift_id)
    if gift is None or db_user.id not in (gift.sender_user_id, gift.recipient_user_id):
        await callback.answer("⚠️ الهدية غير موجودة لهذا الحساب.", show_alert=True)
        return
    await callback.answer()
    await _render_product_gift_detail(callback, session, gift, db_user)


@router.callback_query(F.data.startswith("gift:claim:"))
async def product_gift_claim(callback: CallbackQuery, session, db_user):
    from services.product_gift_service import ProductGiftError, ProductGiftService

    try:
        gift_id = int(callback.data.rsplit(":", 1)[1])
        gift = await ProductGiftService.claim(session, gift_id, db_user.id)
    except (ValueError, ProductGiftError) as exc:
        await callback.answer(str(exc) or "⚠️ الهدية غير متاحة.", show_alert=True)
        return
    gift = await _get_product_gift(session, gift.id)
    await callback.answer("تم استلام الهدية.")
    await _render_product_gift_detail(callback, session, gift, db_user)
    await _send_product_gift_value(callback, session, gift)


@router.callback_query(F.data.startswith("gift:reveal:"))
async def product_gift_reveal(callback: CallbackQuery, session, db_user):
    try:
        gift_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer("⚠️ رقم الهدية غير صالح.", show_alert=True)
        return
    gift = await _get_product_gift(session, gift_id)
    if (
        gift is None
        or gift.recipient_user_id != db_user.id
        or gift.status != ProductGiftStatus.CLAIMED
    ):
        await callback.answer("⚠️ الرمز متاح للمستفيد بعد استلام الهدية فقط.", show_alert=True)
        return
    await callback.answer()
    await _send_product_gift_value(callback, session, gift)


@router.callback_query(F.data.startswith("gift:cancel_confirm:"))
async def product_gift_cancel_confirm(callback: CallbackQuery, session, db_user):
    from database.models import UnifiedOrder

    gift_id = int(callback.data.rsplit(":", 1)[1])
    gift = await _get_product_gift(session, gift_id)
    if gift is None or gift.sender_user_id != db_user.id or gift.status != ProductGiftStatus.PENDING:
        await callback.answer("⚠️ يمكن إلغاء هدية معلّقة أرسلتها أنت فقط.", show_alert=True)
        return
    order = await session.get(UnifiedOrder, gift.unified_order_id)
    await callback.answer()
    await callback.message.edit_text(
        f"هل تريد إلغاء الهدية #{gift.id}؟ سيُعاد مبلغ {order.price_usd if order else '—'}$ إلى رصيدك ويعود المنتج إلى المخزون.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ نعم، ألغِ الهدية", callback_data=f"gift:cancel:{gift.id}", style="danger")],
            [InlineKeyboardButton(text="↩️ تراجع", callback_data=f"gift:view:{gift.id}")],
        ]),
    )


@router.callback_query(F.data.startswith("gift:cancel:"))
async def product_gift_cancel(callback: CallbackQuery, session, db_user):
    from services.product_gift_service import ProductGiftError, ProductGiftService

    try:
        gift_id = int(callback.data.rsplit(":", 1)[1])
        await ProductGiftService.cancel(session, gift_id, db_user.id)
    except (ValueError, ProductGiftError) as exc:
        await callback.answer(str(exc) or "⚠️ تعذر إلغاء الهدية.", show_alert=True)
        return
    gift = await _get_product_gift(session, gift_id)
    await callback.answer("أُلغيت الهدية وأُعيد المبلغ.")
    await _render_product_gift_detail(callback, session, gift, db_user)


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
            f"🛍 <b>{p.name_ar}</b>\n\n{hint}\n\n"
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
        text = f"🛍 <b>{p.name_ar}</b>\n\nاختر الفئة ({len(opts)} فئة متاحة):"
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
        ref = ""
        if p.display_type.value == "per_1000":
            _c1000, _s1000, _m1000 = await price_for(session, p, "1000", db_user)
            ref = f"\n💵 السعر لكل 1000: <b>{_s1000}$</b>"
        text = (
            f"🛍 <b>{p.name_ar}</b>\n{ref}\n\n"
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
    # بدون كمية حرة: باقة ثابتة → الكمية = حجم الباقة (لا 1!)
    pack_qty = str(p.min_quantity) if p.min_quantity and p.min_quantity == p.max_quantity and p.min_quantity > 1 else "1"
    await state.update_data(store_qty=pack_qty)
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
        pname = "طلب مباشر"
        if o.product_id:
            prod = await session.get(Product, o.product_id)
            if prod:
                pname = prod.name_ar[:25]
        else:
            try:
                import json as _json

                _rd = _json.loads(o.result_data or "{}")
                _ps = await session.get(ProviderService, int(_rd.get("provider_service_ref", 0)))
                if _ps:
                    pname = _ps.name[:25]
            except Exception:
                pass
        st = status_ar.get(o.status.value, o.status.value)
        lines.append(f"\n🆔 #{o.id} | {pname}\n{st} | {o.price_usd}$ | {o.created_at.strftime('%Y-%m-%d')}")
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 المتجر", callback_data="store:home", style="success")],
        [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="back_to_main")],
    ]))
    await callback.answer()
