"""
👑 خصومات التجار: طلب المستخدم + موافقة الأدمن (قناة أو لوحة) + إدارة الرتب.
"""

from datetime import datetime
from decimal import Decimal

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import desc, select

from database.models import TraderRequest, User
from filters.admin_filter import IsAdmin
from services import trader_service
from states.states import AdminTraderStates

router = Router(name="traders")
admin_router = Router(name="traders_admin")
admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())


# ── واجهة المستخدم ──

@router.callback_query(F.data == "trader:home")
async def trader_home(callback: CallbackQuery, session, db_user):
    tiers = await trader_service.get_tiers(session)
    mine = await trader_service.user_tier(session, db_user.id)
    pending = await trader_service.pending_request(session, db_user.id)
    lines = ["👑 <b>خصومات التجار</b>\n", "اشحن كثيراً؟ اطلب رتبة تاجر وخذ خصماً دائماً على كل طلب:\n"]
    rows: list[list[InlineKeyboardButton]] = []
    for tier in tiers:
        if tier.get("key") == "none":
            continue
        cur = " ✅ رتبتك" if tier.get("key") == mine.get("key") else ""
        lines.append(f"• <b>{tier.get('name')}</b> — خصم {tier.get('discount')}%{cur}")
        if tier.get("key") != mine.get("key"):
            rows.append([InlineKeyboardButton(
                text=f"📝 طلب رتبة {tier.get('name')}",
                callback_data=f"trader:apply:{tier.get('key')}", style="success")])
    if pending:
        lines.append(f"\n⏳ لديك طلب قيد المراجعة.")
    rows.append([InlineKeyboardButton(text="🔙 حسابي", callback_data="menu:account")])
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("trader:apply:"))
async def trader_apply(callback: CallbackQuery, session, db_user, bot):
    from services.notification_service import NotificationService

    key = callback.data.rsplit(":", 1)[1]
    try:
        req = await trader_service.create_request(session, db_user.id, key)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    tiers = {t.get("key"): t for t in await trader_service.get_tiers(session)}
    tier_name = tiers.get(key, {}).get("name", key)
    msg_id = await NotificationService(bot).notify_admin(
        f"👑 <b>طلب رتبة تاجر جديد #{req.id}</b>\n\n"
        f"👤 المستخدم: {db_user.full_name or '—'} (<code>{db_user.telegram_id}</code>)\n"
        f"🎖 الرتبة المطلوبة: <b>{tier_name}</b>\n"
        f"💰 إجمالي شحنه: {db_user.balance}$ | طلباته: {getattr(db_user, 'total_orders', 0)}\n\n"
        "وافق أو ارفض من هنا مباشرة:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ موافقة", callback_data=f"trader:ok:{req.id}", style="success"),
             InlineKeyboardButton(text="❌ رفض", callback_data=f"trader:no:{req.id}", style="danger")],
        ]),
        notification_type="users",
    )
    if msg_id:
        req.admin_chat_message_id = msg_id
        await session.commit()
    await callback.message.edit_text(
        f"📝 تم إرسال طلبك لرتبة <b>{tier_name}</b>.\nسنعلمك بقرار الإدارة قريباً."
    )
    await callback.answer("✅ أُرسل الطلب")


# ── قرار الأدمن (يعمل من القناة ومن اللوحة) ──

async def _decide(session, bot, req_id: int, admin_db_user, approve: bool) -> tuple[bool, str]:
    from services.notification_service import NotificationService

    req = await session.get(TraderRequest, req_id)
    if not req or req.status != "pending":
        return False, "⚠️ الطلب غير موجود أو تم البت فيه."
    user = await session.get(User, req.user_id)
    tiers = {t.get("key"): t for t in await trader_service.get_tiers(session)}
    tier_name = tiers.get(req.tier_key, {}).get("name", req.tier_key)
    req.status = "approved" if approve else "rejected"
    req.admin_id = admin_db_user.id
    req.processed_at = datetime.utcnow()
    if approve and user:
        await trader_service.set_user_tier(session, user.id, req.tier_key)
    await session.commit()
    notifier = NotificationService(bot)
    verdict = "✅ تمت الموافقة" if approve else "❌ تم الرفض"
    # تحديث رسالة القناة
    if req.admin_chat_message_id:
        from config import settings

        try:
            await bot.edit_message_text(
                chat_id=settings.ADMIN_NOTIFY_CHAT_ID,
                message_id=req.admin_chat_message_id,
                text=f"👑 طلب رتبة تاجر #{req.id} — <b>{verdict}</b>\n({tier_name})",
            )
        except Exception:
            pass
    if user:
        try:
            await notifier.notify_user(
                user.telegram_id,
                f"👑 طلب رتبة <b>{tier_name}</b>: <b>{verdict}</b>"
                + ("\n🎉 خصمك الدائم يطبق من الآن!" if approve else ""),
            )
        except Exception:
            pass
    return True, verdict


@admin_router.callback_query(F.data.startswith("trader:ok:"))
async def trader_approve(callback: CallbackQuery, session, db_user, bot):
    ok, msg = await _decide(session, bot, int(callback.data.rsplit(":", 1)[1]), db_user, True)
    await callback.answer(msg, show_alert=not ok)
    if ok:
        try:
            await callback.message.edit_text(callback.message.text + "\n\n✅ <b>تمت الموافقة</b>")
        except Exception:
            pass


@admin_router.callback_query(F.data.startswith("trader:no:"))
async def trader_reject(callback: CallbackQuery, session, db_user, bot):
    ok, msg = await _decide(session, bot, int(callback.data.rsplit(":", 1)[1]), db_user, False)
    await callback.answer(msg, show_alert=not ok)
    if ok:
        try:
            await callback.message.edit_text(callback.message.text + "\n\n❌ <b>تم الرفض</b>")
        except Exception:
            pass


# ── إدارة من اللوحة ──

@admin_router.callback_query(F.data == "admin:traders")
async def traders_list(callback: CallbackQuery, session):
    result = await session.execute(select(TraderRequest).where(
        TraderRequest.status == "pending").order_by(desc(TraderRequest.id)).limit(20))
    rows_data = list(result.scalars().all())
    lines = ["👑 <b>طلبات التجار المعلقة</b>\n"]
    rows: list[list[InlineKeyboardButton]] = []
    for req in rows_data:
        user = await session.get(User, req.user_id)
        tiers = {t.get("key"): t for t in await trader_service.get_tiers(session)}
        lines.append(f"#{req.id} | {user.full_name if user else req.user_id} | {tiers.get(req.tier_key, {}).get('name', req.tier_key)}")
        rows.append([InlineKeyboardButton(text=f"#{req.id} — مراجعة", callback_data=f"admin:trader_view:{req.id}")])
    if not rows_data:
        lines.append("لا توجد طلبات معلقة 🎉")
    rows.append([InlineKeyboardButton(text="🎖 إدارة الرتب", callback_data="admin:trader_tiers", style="primary")])
    rows.append([InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")])
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:trader_view:"))
async def trader_view(callback: CallbackQuery, session):
    req = await session.get(TraderRequest, int(callback.data.rsplit(":", 1)[1]))
    if not req:
        await callback.answer("⚠️ غير موجود.", show_alert=True)
        return
    user = await session.get(User, req.user_id)
    tiers = {t.get("key"): t for t in await trader_service.get_tiers(session)}
    kb = [[InlineKeyboardButton(text="🔙 الطلبات", callback_data="admin:traders")]]
    if req.status == "pending":
        kb.insert(0, [InlineKeyboardButton(text="✅ موافقة", callback_data=f"trader:ok:{req.id}", style="success"),
                       InlineKeyboardButton(text="❌ رفض", callback_data=f"trader:no:{req.id}", style="danger")])
    await callback.message.edit_text(
        f"👑 طلب #{req.id} — <b>{req.status}</b>\n\n"
        f"👤 {user.full_name if user else '—'} (<code>{user.telegram_id if user else req.user_id}</code>)\n"
        f"🎖 الرتبة: {tiers.get(req.tier_key, {}).get('name', req.tier_key)}\n"
        f"💰 رصيده: {user.balance if user else '—'}$",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
    )
    await callback.answer()


@admin_router.callback_query(F.data == "admin:trader_tiers")
async def trader_tiers_list(callback: CallbackQuery, session):
    tiers = await trader_service.get_tiers(session)
    lines = ["🎖 <b>رتب التجار</b> (اضغط لتعديل النسبة):\n"]
    rows: list[list[InlineKeyboardButton]] = []
    for tier in tiers:
        if tier.get("key") == "none":
            continue
        lines.append(f"• {tier.get('name')} — خصم {tier.get('discount')}%")
        rows.append([InlineKeyboardButton(
            text=f"✏️ {tier.get('name')} ({tier.get('discount')}%)",
            callback_data=f"admin:trader_tier:{tier.get('key')}", style="primary")])
    rows.append([InlineKeyboardButton(text="🔙 الطلبات", callback_data="admin:traders")])
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:trader_tier:"))
async def trader_tier_edit_start(callback: CallbackQuery, state: FSMContext):
    key = callback.data.rsplit(":", 1)[1]
    await state.update_data(trader_tier_key=key)
    await callback.message.edit_text(f"أرسل نسبة الخصم الجديدة لرتبة <code>{key}</code> (0-100):")
    await state.set_state(AdminTraderStates.waiting_discount)
    await callback.answer()


@admin_router.message(AdminTraderStates.waiting_discount)
async def trader_tier_discount_received(message: Message, state: FSMContext, session):
    from decimal import Decimal as _D

    data = await state.get_data()
    try:
        value = _D((message.text or "").strip().replace("%", ""))
    except Exception:
        await message.answer("⚠️ رقم فقط.")
        return
    if not (0 <= value <= 100):
        await message.answer("⚠️ بين 0 و 100.")
        return
    tiers = await trader_service.get_tiers(session)
    for tier in tiers:
        if tier.get("key") == data.get("trader_tier_key"):
            tier["discount"] = str(value)
    await trader_service.set_tiers(session, tiers)
    await state.clear()
    await message.answer(f"✅ حُفظت نسبة {value}%", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎖 الرتب", callback_data="admin:trader_tiers", style="primary")]
    ]))
