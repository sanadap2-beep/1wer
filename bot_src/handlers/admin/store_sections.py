"""
إدارة أقسام المتجر: الأقسام الرئيسية والفرعية والمنتجات والنشر والهوامش.

- عرض شجري: قسم ← فروع ← فروع داخلية ← منتجات.
- نشر خدمة مزود كمنتج في أي فرع + هامش خاص.
- هوامش هرمية: منتج ← فرع ← قسم ← عام.
- إنشاء تلقائي: شجرة HyperStore + هيكل الرشق (8 تطبيقات).
"""

from decimal import Decimal

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select

from database.models import Category, CategoryType, Product, ProductStatus, ProviderService, SubCategory
from filters.admin_filter import IsAdmin
from services.dynamic_service import DynamicService
from states.states import AdminStoreStates

router = Router(name="admin_store_sections")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

PAGE_SIZE = 8
BACK_MAIN = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")]
])

CAT_TYPES: list[tuple[str, str]] = [
    ("رشق سوشيال 📈", "smm"),
    ("شحن ألعاب 🎮", "games"),
    ("شحن برامج 📱", "apps"),
    ("رصيد/شحن 💳", "balances"),
    ("بطاقات رقمية 💳", "cards"),
    ("اشتراكات 🔐", "subscriptions"),
    ("توثيق ✅", "verification"),
    ("أكواد 🎟", "codes"),
    ("مخصص 📁", "custom"),
]


# ── قوائم ──

@router.callback_query(F.data == "admin:store_cats")
async def cats_list(callback: CallbackQuery, session):
    result = await session.execute(select(Category).order_by(Category.sort_order, Category.id))
    cats = list(result.scalars().all())
    rows: list[list[InlineKeyboardButton]] = []
    for c in cats:
        mark = "🟢" if c.is_active else "⚪"
        margin = f" | {c.profit_margin_percent}%" if c.profit_margin_percent is not None else ""
        rows.append([InlineKeyboardButton(
            text=f"{mark} {c.emoji} {c.name_ar}{margin}",
            callback_data=f"admin:store_cat:{c.id}",
        )])
    rows.append([InlineKeyboardButton(text="➕ إضافة قسم", callback_data="admin:store_cat_add", style="success")])
    rows.append([InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")])
    await callback.message.edit_text(
        "📁 <b>أقسام المتجر</b>\n\nالنسبة بجانب الاسم = هامش القسم (فارغ = يرث العام).",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


async def _sub_counts(session, sub_ids: list[int]) -> dict[int, int]:
    if not sub_ids:
        return {}
    result = await session.execute(
        select(Product.sub_category_id, func.count(Product.id))
        .where(Product.sub_category_id.in_(sub_ids))
        .group_by(Product.sub_category_id)
    )
    return {row[0]: row[1] for row in result.all()}


@router.callback_query(F.data.startswith("admin:store_cat:"))
async def cat_view(callback: CallbackQuery, session):
    cid = int(callback.data.rsplit(":", 1)[1])
    cat = await DynamicService.get_category(session, cid)
    if not cat:
        await callback.answer("⚠️ غير موجود.", show_alert=True)
        return
    subs = await DynamicService.get_all_root_sub_categories(session, cid)
    counts = await _sub_counts(session, [s.id for s in subs])
    margin = f"{cat.profit_margin_percent}%" if cat.profit_margin_percent is not None else "يرث العام"
    lines = [
        f"{cat.emoji} <b>{cat.name_ar}</b>\n",
        f"النوع: <code>{cat.type.value}</code> | الحالة: {'🟢' if cat.is_active else '⚪'}",
        f"💵 الهامش: <b>{margin}</b>\n",
    ]
    rows: list[list[InlineKeyboardButton]] = []
    for s in subs:
        mark = "🟢" if s.is_active else "⚪"
        n = counts.get(s.id, 0)
        rows.append([InlineKeyboardButton(
            text=f"{mark} {s.emoji} {s.name_ar} ({n})",
            callback_data=f"admin:store_sub:{s.id}", style="success",
        )])
        lines.append(f"• {s.name_ar} — {n} منتج")
    rows.append([InlineKeyboardButton(text="➕ إضافة فرع", callback_data=f"admin:store_sub_add:{cid}:0", style="success")])
    rows.append([InlineKeyboardButton(text="💵 ضبط هامش القسم", callback_data=f"admin:store_margin:cat:{cid}", style="primary")])
    rows.append([InlineKeyboardButton(
        text="⏸ تعطيل" if cat.is_active else "▶️ تفعيل",
        callback_data=f"admin:store_cat_toggle:{cid}",
        style="danger" if cat.is_active else "success",
    )])
    rows.append([InlineKeyboardButton(text="🗑 حذف القسم", callback_data=f"admin:store_cat_del:{cid}", style="danger")])
    rows.append([InlineKeyboardButton(text="🔙 الأقسام", callback_data="admin:store_cats", style="success")])
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:store_sub:"))
async def sub_view(callback: CallbackQuery, session):
    sid = int(callback.data.rsplit(":", 1)[1])
    sub = await DynamicService.get_sub_category(session, sid)
    if not sub:
        await callback.answer("⚠️ غير موجود.", show_alert=True)
        return
    children = await DynamicService.get_all_child_sections(session, sid)
    products = sub.products or []
    margin = f"{sub.profit_margin_percent}%" if sub.profit_margin_percent is not None else "يرث القسم"
    lines = [
        f"{sub.emoji} <b>{sub.name_ar}</b>\n",
        f"الحالة: {'🟢' if sub.is_active else '⚪'} | 💵 الهامش: <b>{margin}</b>\n",
    ]
    rows: list[list[InlineKeyboardButton]] = []
    for ch in children:
        mark = "🟢" if ch.is_active else "⚪"
        rows.append([InlineKeyboardButton(
            text=f"📂 {mark} {ch.emoji} {ch.name_ar}",
            callback_data=f"admin:store_sub:{ch.id}", style="success",
        )])
    for p in products:
        mark = "🟢" if p.status.value == "active" else "⚪"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {p.name_ar[:30]} — {p.price_usd}$",
            callback_data=f"admin:store_prod:{p.id}", style="success",
        )])
        lines.append(f"• {p.name_ar} — {p.price_usd}$ (تكلفة {p.cost_price_usd}$)")
    if not children and not products:
        lines.append("فارغ — أضف فرعاً داخلياً أو انشر منتجاً هنا.")
    rows.append([InlineKeyboardButton(text="➕ فرع داخلي", callback_data=f"admin:store_sub_add:{sub.category_id}:{sub.id}", style="success")])
    rows.append([InlineKeyboardButton(text="📤 نشر منتج هنا", callback_data=f"admin:store_publish_to:{sub.id}", style="success")])
    rows.append([InlineKeyboardButton(text="💵 ضبط هامش الفرع", callback_data=f"admin:store_margin:sub:{sub.id}", style="primary")])
    rows.append([InlineKeyboardButton(
        text="⏸ تعطيل" if sub.is_active else "▶️ تفعيل",
        callback_data=f"admin:store_sub_toggle:{sub.id}",
        style="danger" if sub.is_active else "success",
    )])
    rows.append([InlineKeyboardButton(text="🗑 حذف الفرع", callback_data=f"admin:store_sub_del:{sub.id}", style="danger")])
    parent_cb = f"admin:store_sub:{sub.parent_sub_category_id}" if sub.parent_sub_category_id else f"admin:store_cat:{sub.category_id}"
    rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data=parent_cb)])
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:store_prod:"))
async def product_view(callback: CallbackQuery, session):
    pid = int(callback.data.rsplit(":", 1)[1])
    p = await DynamicService.get_product(session, pid)
    if not p:
        await callback.answer("⚠️ غير موجود.", show_alert=True)
        return
    from database.models import ProviderService as _PS
    from services.offer_service import offer_eligible

    ps = await session.get(_PS, p.provider_service_ref_id) if p.provider_service_ref_id else None
    eligible = await offer_eligible(p, ps)
    margin = f"{p.profit_margin_percent}%" if p.profit_margin_percent is not None else "يرث الفرع"
    flags = []
    if p.requires_link:
        flags.append("رابط")
    if p.requires_player_id:
        flags.append("Player ID")
    if p.requires_quantity:
        flags.append(f"كمية ({p.min_quantity}-{p.max_quantity})")
    prov = f"{p.api_provider.name} [{p.provider_service_id}]" if p.api_provider else "يدوي/بدون مزود"
    text = (
        f"🛍 <b>{p.name_ar}</b>\n\n"
        f"الحالة: {'🟢 مفعّل' if p.status.value == 'active' else '⚪ معطّل'}\n"
        f"💰 البيع: <b>{p.price_usd}$</b> | التكلفة: {p.cost_price_usd}$\n"
        f"💵 الهامش: <b>{margin}</b>\n"
        f"🔌 المزود: {prov}\n"
        f"📝 المطلوب: {' + '.join(flags) if flags else 'تأكيد فقط'}\n"
        f"🛒 مبيع: {p.total_sold}"
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 ضبط الهامش", callback_data=f"admin:store_margin:prod:{p.id}", style="primary")],
        *([[InlineKeyboardButton(text="🔥 تحويل لعرض مؤقت", callback_data=f"admin:offer_create:{p.id}", style="success")]] if eligible else []),
        [InlineKeyboardButton(
            text="⏸ تعطيل" if p.status.value == "active" else "▶️ تفعيل",
            callback_data=f"admin:store_prod_toggle:{p.id}",
            style="danger" if p.status.value == "active" else "success",
        )],
        [InlineKeyboardButton(text="🗑 حذف المنتج", callback_data=f"admin:store_prod_del:{p.id}", style="danger")],
        [InlineKeyboardButton(text="🔙 الفرع", callback_data=f"admin:store_sub:{p.sub_category_id}")],
    ]))
    await callback.answer()


# ── إضافة قسم/فرع ──

@router.callback_query(F.data == "admin:store_cat_add")
async def cat_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📁 أرسل اسم القسم الجديد بالعربي (مثال: <code>شحن ألعاب</code>):")
    await state.set_state(AdminStoreStates.waiting_category_name)
    await callback.answer()


@router.message(AdminStoreStates.waiting_category_name)
async def cat_name_received(message: Message, state: FSMContext):
    await state.update_data(store_cat_name=message.text.strip()[:64])
    rows = [[InlineKeyboardButton(text=label, callback_data=f"admin:store_cat_type:{code}", style="success")] for label, code in CAT_TYPES]
    await message.answer(
        "اختر نوع القسم (يحدد المزودين والأيقونة الافتراضية):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("admin:store_cat_type:"))
async def cat_type_received(callback: CallbackQuery, state: FSMContext, session):
    code = callback.data.rsplit(":", 1)[1]
    data = await state.get_data()
    name = data.get("store_cat_name", "قسم جديد")
    emoji = {"smm": "📈", "games": "🎮", "apps": "📱", "balances": "💳"}.get(code, "🛍")
    cat = await DynamicService.create_category(
        session, name_ar=name, emoji=emoji,
        category_type=CategoryType(code), sort_order=50,
    )
    await state.clear()
    await callback.answer("✅ تم إنشاء القسم.")
    # إعادة العرض
    result = await session.execute(select(Category).order_by(Category.sort_order, Category.id))
    cats = list(result.scalars().all())
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=f"{'🟢' if c.is_active else '⚪'} {c.emoji} {c.name_ar}", callback_data=f"admin:store_cat:{c.id}")]
        for c in cats
    ]
    rows.append([InlineKeyboardButton(text="➕ إضافة قسم", callback_data="admin:store_cat_add", style="success")])
    rows.append([InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")])
    await callback.message.edit_text("📁 <b>أقسام المتجر</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("admin:store_sub_add:"))
async def sub_add_start(callback: CallbackQuery, state: FSMContext):
    _, _, cid, parent = callback.data.split(":")
    await state.update_data(store_sub_cat=int(cid), store_sub_parent=int(parent))
    await callback.message.edit_text("📂 أرسل اسم الفرع الجديد (مثال: <code>PUBG</code> أو <code>سيريتل</code>):")
    await state.set_state(AdminStoreStates.waiting_sub_name)
    await callback.answer()


@router.message(AdminStoreStates.waiting_sub_name)
async def sub_name_received(message: Message, state: FSMContext, session):
    data = await state.get_data()
    parent = int(data.get("store_sub_parent", 0)) or None
    sub = await DynamicService.create_sub_category(
        session, category_id=int(data["store_sub_cat"]),
        name_ar=message.text.strip()[:64], emoji="🛍",
        parent_sub_category_id=parent, sort_order=10,
    )
    await state.clear()
    await message.answer(f"✅ تم إنشاء الفرع: <b>{sub.name_ar}</b>")
    # عرض الفرع الأب
    back_cb = f"admin:store_sub:{parent}" if parent else f"admin:store_cat:{sub.category_id}"
    await message.answer("اضغط رجوع للمتابعة:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 رجوع", callback_data=back_cb)]
    ]))


# ── الهوامش ──

@router.callback_query(F.data.startswith("admin:store_margin:"))
async def margin_start(callback: CallbackQuery, state: FSMContext, session):
    _, _, kind, obj_id = callback.data.split(":")
    obj_id = int(obj_id)
    if kind == "cat":
        obj = await session.get(Category, obj_id)
        cur = obj.profit_margin_percent if obj else None
    elif kind == "sub":
        obj = await session.get(SubCategory, obj_id)
        cur = obj.profit_margin_percent if obj else None
    else:
        obj = await session.get(Product, obj_id)
        cur = obj.profit_margin_percent if obj else None
    await state.update_data(store_margin_kind=kind, store_margin_id=obj_id)
    await callback.message.edit_text(
        f"💵 الهامش الحالي: <b>{cur}%</b>" if cur is not None else "💵 الهامش الحالي: <b>يرث المستوى الأعلى</b>"
        + "\n\nأرسل النسبة الجديدة (0-500)، أو أرسل <code>-</code> للإرث (للأقسام/الفروع):"
    )
    await state.set_state(AdminStoreStates.waiting_margin)
    await callback.answer()


@router.message(AdminStoreStates.waiting_margin)
async def margin_received(message: Message, state: FSMContext, session):
    data = await state.get_data()
    kind, obj_id = data["store_margin_kind"], int(data["store_margin_id"])
    raw = message.text.strip().replace("%", "")
    value = None
    if raw != "-":
        try:
            value = Decimal(raw)
        except Exception:
            await message.answer("⚠️ أرسل رقماً فقط (مثال: <code>50</code>) أو <code>-</code>.")
            return
        if value < 0 or value > 500:
            await message.answer("⚠️ بين 0 و 500 فقط.")
            return
    if kind == "cat":
        await DynamicService.update_category(session, obj_id, profit_margin_percent=value)
        back = f"admin:store_cat:{obj_id}"
    elif kind == "sub":
        await DynamicService.update_sub_category(session, obj_id, profit_margin_percent=value)
        back = f"admin:store_sub:{obj_id}"
    else:
        await DynamicService.update_product(session, obj_id, profit_margin_percent=value, margin_manual=value is not None)
        if value is not None:
            # إعادة حساب السعر من التكلفة
            p = await session.get(Product, obj_id)
            if p:
                sell = (p.cost_price_usd * (Decimal("100") + value) / Decimal("100"))
                await DynamicService.update_product(session, obj_id, price_usd=sell)
        back = f"admin:store_prod:{obj_id}"
    await state.clear()
    await message.answer(
        "✅ تم الحفظ.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 رجوع", callback_data=back)]]),
    )


# ── تفعيل/حذف ──

@router.callback_query(F.data.startswith("admin:store_cat_toggle:"))
async def cat_toggle(callback: CallbackQuery, session):
    cid = int(callback.data.rsplit(":", 1)[1])
    cat = await session.get(Category, cid)
    if cat:
        cat.is_active = not cat.is_active
        await session.commit()
        await callback.answer("✅ تم.")
        cat2 = await DynamicService.get_category(session, cid)
        subs = await DynamicService.get_all_root_sub_categories(session, cid)
        rows: list[list[InlineKeyboardButton]] = [
            [InlineKeyboardButton(text=f"{s.emoji} {s.name_ar}", callback_data=f"admin:store_sub:{s.id}")] for s in subs
        ]
        rows.append([InlineKeyboardButton(text="🔙 الأقسام", callback_data="admin:store_cats", style="success")])
        await callback.message.edit_text(f"{cat2.emoji} <b>{cat2.name_ar}</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    else:
        await callback.answer("⚠️ غير موجود.", show_alert=True)


@router.callback_query(F.data.startswith("admin:store_cat_del:"))
async def cat_delete(callback: CallbackQuery, session):
    cid = int(callback.data.rsplit(":", 1)[1])
    await DynamicService.delete_category(session, cid)
    await callback.answer("🗑 تم الحذف.")
    await cats_list(callback, session)


@router.callback_query(F.data.startswith("admin:store_sub_toggle:"))
async def sub_toggle(callback: CallbackQuery, session):
    sid = int(callback.data.rsplit(":", 1)[1])
    sub = await session.get(SubCategory, sid)
    if sub:
        sub.is_active = not sub.is_active
        await session.commit()
    await callback.answer("✅ تم.")
    await sub_view(callback, session)


@router.callback_query(F.data.startswith("admin:store_sub_del:"))
async def sub_delete(callback: CallbackQuery, session):
    sid = int(callback.data.rsplit(":", 1)[1])
    sub = await session.get(SubCategory, sid)
    parent_cb = "admin:store_cats"
    if sub:
        parent_cb = f"admin:store_sub:{sub.parent_sub_category_id}" if sub.parent_sub_category_id else f"admin:store_cat:{sub.category_id}"
    await DynamicService.delete_sub_category(session, sid)
    await callback.answer("🗑 تم الحذف.")
    await callback.message.edit_text("تم الحذف.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 رجوع", callback_data=parent_cb)]
    ]))


@router.callback_query(F.data.startswith("admin:store_prod_toggle:"))
async def product_toggle(callback: CallbackQuery, session):
    pid = int(callback.data.rsplit(":", 1)[1])
    p = await session.get(Product, pid)
    if p:
        p.status = ProductStatus.INACTIVE if p.status == ProductStatus.ACTIVE else ProductStatus.ACTIVE
        await session.commit()
    await callback.answer("✅ تم.")
    await product_view(callback, session)


@router.callback_query(F.data.startswith("admin:store_prod_del:"))
async def product_delete(callback: CallbackQuery, session):
    pid = int(callback.data.rsplit(":", 1)[1])
    p = await session.get(Product, pid)
    back = f"admin:store_sub:{p.sub_category_id}" if p else "admin:store_cats"
    await DynamicService.delete_product(session, pid)
    await callback.answer("🗑 تم الحذف.")
    await callback.message.edit_text("تم الحذف.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 رجوع", callback_data=back)]
    ]))


# ── النشر من المزود ──

@router.callback_query(F.data == "admin:store_publish")
async def publish_home(callback: CallbackQuery, session):
    providers = await DynamicService.get_all_providers(session)
    if not providers:
        await callback.message.edit_text(
            "⚠️ لا يوجد مزودون بعد. أضف مزوداً أولاً من 🔌 مزودو المتجر.",
            reply_markup=BACK_MAIN,
        )
        await callback.answer()
        return
    rows = [[InlineKeyboardButton(text=f"{p.name} ({p.total_services} خدمة)", callback_data=f"admin:store_pub_prov:{p.id}", style="success")] for p in providers]
    rows.append([InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")])
    await callback.message.edit_text(
        "📤 <b>نشر من المزود</b>\n\nاختر المزود ثم ابحث عن الخدمة (مثال: <code>سيريتل</code> أو <code>UC 60</code> أو <code>followers</code>):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:store_pub_prov:"))
async def publish_search_start(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.rsplit(":", 1)[1])
    await state.update_data(store_pub_provider=pid)
    # اقتراحات ذكية للـ SMM
    await callback.message.edit_text(
        "🔎 أرسل كلمة البحث (3 أحرف على الأقل):\n\n"
        "أمثلة: <code>سيريتل</code> / <code>MTN</code> / <code>PUBG</code> / <code>instagram followers</code>",
    )
    await state.set_state(AdminStoreStates.waiting_search)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:store_publish_to:"))
async def publish_to_preset(callback: CallbackQuery, session, state: FSMContext):
    sid = int(callback.data.rsplit(":", 1)[1])
    await state.update_data(store_pub_target_sub=sid)
    providers = await DynamicService.get_all_providers(session)
    rows = [[InlineKeyboardButton(text=f"{p.name} ({p.total_services})", callback_data=f"admin:store_pub_prov2:{p.id}", style="success")] for p in providers]
    rows.append([InlineKeyboardButton(text="🔙", callback_data=f"admin:store_sub:{sid}")])
    await callback.message.edit_text("🔌 اختر المزود للنشر المباشر في هذا الفرع:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:store_pub_prov2:"))
async def publish_search_direct(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.rsplit(":", 1)[1])
    await state.update_data(store_pub_provider=pid, store_pub_direct=True)
    await callback.message.edit_text("🔎 أرسل كلمة البحث:")
    await state.set_state(AdminStoreStates.waiting_search)
    await callback.answer()


@router.message(AdminStoreStates.waiting_search)
async def publish_search_results(message: Message, state: FSMContext, session):
    from sqlalchemy import or_ as sa_or

    data = await state.get_data()
    pid = int(data.get("store_pub_provider", 0))
    q = message.text.strip()
    if len(q) < 2:
        await message.answer("⚠️ كلمة قصيرة جداً.")
        return
    like = f"%{q}%"
    result = await session.execute(
        select(ProviderService).where(
            ProviderService.api_provider_id == pid,
            sa_or(ProviderService.name.ilike(like), ProviderService.category.ilike(like)),
        ).order_by(ProviderService.id).limit(30)
    )
    rows_data = list(result.scalars().all())
    if not rows_data:
        await message.answer("لا نتائج. جرّب كلمة أخرى.")
        return
    # المنتجات المنشورة مسبقاً
    pub_result = await session.execute(
        select(Product.provider_service_ref_id).where(Product.provider_service_ref_id.in_([r.id for r in rows_data]))
    )
    published = {r[0] for r in pub_result.all()}
    kb_rows: list[list[InlineKeyboardButton]] = []
    lines = [f"🔎 نتائج <b>{q}</b> ({len(rows_data)}):\n"]
    direct_sub = data.get("store_pub_target_sub") if data.get("store_pub_direct") else None
    for r in rows_data:
        mark = "✅" if r.id in published else "➕"
        cb = f"admin:store_pubdo:{r.id}:{direct_sub}" if direct_sub else f"admin:store_pub:{r.id}"
        kb_rows.append([InlineKeyboardButton(
            text=f"{mark} {r.name[:40]}",
            callback_data=cb, style="success",
        )])
    kb_rows.append([InlineKeyboardButton(text="🔙", callback_data="admin:store_publish")])
    await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await state.clear()


@router.callback_query(F.data.startswith("admin:store_pub:"))
async def publish_pick_sub(callback: CallbackQuery, session, state: FSMContext):
    ps_id = int(callback.data.rsplit(":", 1)[1])
    await state.update_data(store_pub_ps=ps_id)
    result = await session.execute(select(Category).order_by(Category.sort_order, Category.id))
    cats = list(result.scalars().all())
    rows = [[InlineKeyboardButton(text=f"{c.emoji} {c.name_ar}", callback_data=f"admin:store_pubcat:{ps_id}:{c.id}", style="success")] for c in cats]
    rows.append([InlineKeyboardButton(text="❌ إلغاء", callback_data="admin:store_publish")])
    await callback.message.edit_text("📁 اختر القسم الهدف:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:store_pubcat:"))
async def publish_pick_sub2(callback: CallbackQuery, session):
    _, _, ps_id, cid = callback.data.split(":")
    subs = await DynamicService.get_active_sub_categories(session, int(cid))
    if not subs:
        await callback.answer("هذا القسم بلا فروع — أنشئ فرعاً أولاً.", show_alert=True)
        return
    rows: list[list[InlineKeyboardButton]] = []
    for s in subs:
        prefix = "📂 " if s.parent_sub_category_id else ""
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{s.emoji} {s.name_ar}",
            callback_data=f"admin:store_pubdo:{ps_id}:{s.id}", style="success",
        )])
    rows.append([InlineKeyboardButton(text="🔙", callback_data=f"admin:store_pub:{ps_id}")])
    await callback.message.edit_text("📂 اختر الفرع الهدف:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:store_pubdo:"))
async def publish_do(callback: CallbackQuery, session, state: FSMContext):
    from services.store_sync_service import publish_product
    from services.settings_service import SettingsService

    _, _, ps_id, sid = callback.data.split(":")
    margin = await SettingsService.get_decimal("default_profit_margin_percent", Decimal("50"))
    try:
        product = await publish_product(session, int(ps_id), int(sid), margin_percent=margin)
    except Exception as exc:
        await callback.answer(f"فشل النشر: {str(exc)[:100]}", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        f"✅ تم النشر: <b>{product.name_ar}</b>\n\n"
        f"💰 البيع: {product.price_usd}$ (تكلفة {product.cost_price_usd}$ + هامش {margin}%)\n"
        f"المنتج ظاهر الآن للزبائن في الفرع.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👁 عرض المنتج", callback_data=f"admin:store_prod:{product.id}", style="primary")],
            [InlineKeyboardButton(text="📂 الفرع", callback_data=f"admin:store_sub:{sid}")],
        ]),
    )
    await callback.answer()


# ── إنشاء تلقائي ──

@router.callback_query(F.data == "admin:store_flush")
async def store_flush_ask(callback: CallbackQuery, session):
    from sqlalchemy import func as _func

    from database.models import Category as _Cat, Product as _Prod

    cats = int((await session.execute(select(_func.count(_Cat.id)))).scalar_one() or 0)
    prods = int((await session.execute(select(_func.count(_Prod.id)))).scalar_one() or 0)
    await callback.message.edit_text(
        "🧹 <b>تفريغ المتجر</b>\n\n"
        f"سيحذف: <b>{cats} قسماً</b> بفروعها + <b>{prods} منتجاً</b>.\n"
        "• الأرقام لا تُمس أبداً.\n"
        "• المزودون وخدماتهم المسحوبة تبقى (سحب جديد بعد التفريغ).\n"
        "• لا رجوع بعد الحذف!\n\n"
        "متأكد؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧹 نعم، فرّغ كلشي", callback_data="admin:store_flush_go", style="danger")],
            [InlineKeyboardButton(text="❌ تراجع", callback_data="admin:main")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:store_flush_go")
async def store_flush_go(callback: CallbackQuery, session):
    from services.store_sync_service import flush_store

    await callback.answer("⏳ جاري التفريغ...")
    stats = await flush_store(session)
    await callback.message.edit_text(
        "✅ <b>تم التفريغ!</b>\n\n"
        f"🗑 أقسام محذوفة: <b>{stats['cats']}</b>\n"
        f"🗑 منتجات محذوفة: <b>{stats['products']}</b>\n\n"
        "الخطوة التالية: مزامنة المزودين ثم أزرار التجهيز الأربعة لسحب نظيف.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔌 مزودو المتجر", callback_data="admin:store_providers", style="success")],
            [InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")],
        ]),
    )


@router.callback_query(F.data == "admin:store_autotree")
async def autotree_home(callback: CallbackQuery, session):
    providers = await DynamicService.get_all_providers(session)
    rows = [[InlineKeyboardButton(text=f"🌳 {p.name}", callback_data=f"admin:store_prov_sync:{p.id}", style="success")] for p in providers]
    rows.append([InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")])
    await callback.message.edit_text(
        "🌳 <b>إنشاء الأقسام من المزود</b>\n\n"
        "لـ HyperStore: تُبنى شجرة الأقسام والفروع كاملة من المزود (الألعاب/التطبيقات/الأرصدة...).\n"
        "اختر المزود لبدء المزامنة:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:store_smm_setup")
async def smm_setup(callback: CallbackQuery, session):
    from services.store_sync_service import ensure_smm_structure

    cat, subs = await ensure_smm_structure(session)
    names = "، ".join(f"{s.emoji} {s.name_ar}" for s in subs)
    await callback.message.edit_text(
        f"⚡ <b>تم تجهيز هيكل الرشق</b>\n\nالقسم: {cat.emoji} {cat.name_ar}\n\n{names}\n\n"
        "الخطوة التالية: زامن مزود الـ SMM ثم انشر الخدمات من 📤 نشر من المزود.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 نشر من المزود", callback_data="admin:store_publish", style="success")],
            [InlineKeyboardButton(text="📁 الأقسام", callback_data="admin:store_cats", style="success")],
        ]),
    )
    await callback.answer()
