"""دعم فني تفاعلي عبر نظام تذاكر داخل البوت."""

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import desc, select

from database.models import (
    NumberOrder,
    ProductGift,
    ProductGiftStatus,
    SupportTicket,
    SupportTicketStatus,
    UnifiedOrder,
    User,
)
from keyboards.main_menu import back_to_main_kb
from keyboards.support import (
    admin_ticket_kb,
    support_cancel_kb,
    support_menu_kb,
    support_ticket_view_kb,
    support_tickets_kb,
)
from services.ai_support_service import AISupportService
from services.notification_service import NotificationService
from services.settings_service import SettingsService
from services.i18n_service import I18nService
from states.states import AiSupportStates, SupportTicketStates

router = Router(name="support")

_STATUS_LABELS = {
    SupportTicketStatus.OPEN: "🟢 مفتوحة",
    SupportTicketStatus.IN_PROGRESS: "🔄 قيد المتابعة",
    SupportTicketStatus.RESOLVED: "✅ محلولة",
    SupportTicketStatus.CLOSED: "⚪ مغلقة",
}


def _status_label(status) -> str:
    return _STATUS_LABELS.get(status, getattr(status, "value", str(status)))


@router.message(F.text == "🛠 الدعم الفني")
async def support_handler(message: Message, db_user=None):
    await _send_support(message, db_user)


@router.callback_query(F.data == "menu:support")
async def support_handler_cb(callback: CallbackQuery, db_user=None, state: FSMContext = None):
    if state is not None:
        await state.clear()
    await callback.answer()
    await _send_support(callback.message, db_user)


async def _send_support(message: Message, db_user=None):
    language = getattr(db_user, "language_code", "ar") or "ar"
    support_username = await SettingsService.get("support_username", "@support")
    await message.answer(
        I18nService.t("support_card", language, support=escape(support_username or "@support")),
        reply_markup=support_menu_kb(),
    )


@router.callback_query(F.data == "support:ai")
async def ai_support_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AiSupportStates.waiting_question)
    await callback.answer()
    await callback.message.edit_text(
        "🤖 <b>مساعدة فورية</b>\n\nاكتب سؤالك عن الشحن أو الطلبات أو الرصيد:",
        reply_markup=support_cancel_kb(),
    )


@router.message(AiSupportStates.waiting_question)
async def ai_support_question(message: Message, state: FSMContext):
    answer, needs_ticket = AISupportService.answer(message.text or "")
    await state.clear()
    await message.answer(
        f"🤖 {escape(answer)}",
        reply_markup=support_menu_kb(),
    )
    if needs_ticket:
        await message.answer(
            "يمكنك فتح تذكرة وسيصل سؤالك لفريق الدعم.",
            reply_markup=support_cancel_kb(),
        )


@router.callback_query(F.data == "support:new")
async def support_new(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "📝 <b>فتح تذكرة دعم</b>\n\n"
        "اكتب مشكلتك أو استفسارك بالتفصيل في رسالة واحدة (حتى 2000 حرف). "
        "يمكنك إرفاق صورة مع وصفها في التعليق:",
        reply_markup=support_cancel_kb(),
    )
    await state.set_state(SupportTicketStates.waiting_message)


@router.callback_query(F.data.startswith("support:order:"))
async def support_order_start(
    callback: CallbackQuery,
    state: FSMContext,
    session,
    db_user: User,
):
    parts = callback.data.split(":")
    if len(parts) != 4 or parts[2] not in ("number", "unified"):
        await callback.answer("⚠️ بيانات الطلب غير صالحة.", show_alert=True)
        return
    order_kind, raw_order_id = parts[2], parts[3]
    try:
        order_id = int(raw_order_id)
    except ValueError:
        await callback.answer("⚠️ بيانات الطلب غير صالحة.", show_alert=True)
        return

    if order_kind == "number":
        order = (
            await session.execute(
                select(NumberOrder).where(
                    NumberOrder.id == order_id,
                    NumberOrder.user_id == db_user.id,
                )
            )
        ).scalar_one_or_none()
        order_summary = (
            f"طلب رقم #{order.id} · {order.service} · {order.phone_number}"
            if order
            else None
        )
    else:
        order = (
            await session.execute(
                select(UnifiedOrder).where(
                    UnifiedOrder.id == order_id,
                    UnifiedOrder.user_id == db_user.id,
                )
            )
        ).scalar_one_or_none()
        if order is None:
            gift = (
                await session.execute(
                    select(ProductGift.id).where(
                        ProductGift.unified_order_id == order_id,
                        ProductGift.recipient_user_id == db_user.id,
                        ProductGift.status != ProductGiftStatus.CANCELLED,
                    )
                )
            ).scalar_one_or_none()
            if gift is not None:
                order = await session.get(UnifiedOrder, order_id)
        order_summary = f"الطلب الموحد #{order.id}" if order else None

    if order is None:
        await callback.answer("⚠️ الطلب غير موجود في حسابك.", show_alert=True)
        return

    await state.clear()
    await state.update_data(
        support_order_kind=order_kind,
        support_order_id=order_id,
    )
    await state.set_state(SupportTicketStates.waiting_message)
    await callback.answer()
    order_title = order_summary or f"الطلب #{order_id}"
    await callback.message.edit_text(
        f"📝 <b>تذكرة عن {escape(order_title)}</b>\n\n"
        "اكتب تفاصيل المشكلة (5 إلى 2000 حرف). يمكنك إرفاق صورة مع وصفها في التعليق:",
        reply_markup=support_cancel_kb(),
    )


@router.message(SupportTicketStates.waiting_message)
async def support_message_received(
    message: Message,
    state: FSMContext,
    session,
    db_user: User,
    bot,
):
    ticket_message = (message.text or message.caption or "").strip()
    if len(ticket_message) < 5:
        await message.answer("⚠️ اكتب تفاصيل أكثر عن المشكلة، وأضف وصفاً مع الصورة إن أرفقتها.")
        return
    if len(ticket_message) > 2000:
        await message.answer("⚠️ الحد الأقصى للتذكرة 2000 حرف.")
        return

    data = await state.get_data()
    order_kind = data.get("support_order_kind")
    order_id = data.get("support_order_id")
    subject = (
        f"مشكلة في الطلب #{order_id}"
        if order_kind and order_id
        else ticket_message.splitlines()[0][:128]
    )
    ticket = SupportTicket(
        user_id=db_user.id,
        number_order_id=order_id if order_kind == "number" else None,
        unified_order_id=order_id if order_kind == "unified" else None,
        subject=subject or "طلب دعم",
        message=ticket_message,
        attachment_file_id=message.photo[-1].file_id if message.photo else None,
        status=SupportTicketStatus.OPEN,
    )
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)

    admin_text = (
        "🎫 <b>تذكرة دعم جديدة</b>\n\n"
        f"🆔 التذكرة: <b>#{ticket.id}</b>\n"
        f"👤 المستخدم: <code>{db_user.telegram_id}</code> "
        f"(@{escape(db_user.username or '-')})\n"
        f"📝 العنوان: <b>{escape(subject)}</b>\n"
        + (f"🔗 الطلب المرتبط: <b>{order_kind} #{order_id}</b>\n" if order_kind else "")
        + ("📎 أرفق المستخدم صورة دليل.\n" if ticket.attachment_file_id else "")
        + "\n"
        f"{escape(ticket_message)}"
    )
    notifier = NotificationService(bot)
    if ticket.attachment_file_id:
        admin_caption = (
            "🎫 <b>تذكرة دعم جديدة مع صورة</b>\n"
            f"🆔 التذكرة: <b>#{ticket.id}</b>\n"
            f"👤 المستخدم: <code>{db_user.telegram_id}</code> "
            f"(@{escape((db_user.username or '-')[:48])})\n"
            f"📝 العنوان: <b>{escape(subject[:80])}</b>\n"
            + (f"🔗 الطلب: <b>{order_kind} #{order_id}</b>" if order_kind else "")
        )
        photo_notification_id = await notifier.notify_admin_photo(
            ticket.attachment_file_id,
            admin_caption,
            reply_markup=admin_ticket_kb(ticket.id, "open"),
        )
        if photo_notification_id is None:
            await notifier.notify_admin(
                admin_text,
                reply_markup=admin_ticket_kb(ticket.id, "open"),
            )
    else:
        await notifier.notify_admin(
            admin_text,
            reply_markup=admin_ticket_kb(ticket.id, "open"),
        )

    await message.answer(
        "✅ <b>تم فتح تذكرة الدعم</b>\n\n"
        f"رقم التذكرة: <code>#{ticket.id}</code>\n"
        "سيصلك الرد هنا عند متابعته من فريق الدعم.",
        reply_markup=back_to_main_kb(),
    )
    await state.clear()


@router.callback_query(F.data == "support:list")
async def support_list(
    callback: CallbackQuery,
    session,
    db_user: User,
):
    result = await session.execute(
        select(SupportTicket)
        .where(SupportTicket.user_id == db_user.id)
        .order_by(desc(SupportTicket.created_at))
        .limit(20)
    )
    tickets = list(result.scalars().all())
    await callback.answer()
    if not tickets:
        await callback.message.edit_text(
            "📋 لا توجد لديك تذاكر دعم بعد.",
            reply_markup=support_menu_kb(),
        )
        return

    lines = ["📋 <b>تذاكري</b>\n"]
    for ticket in tickets:
        lines.append(
            f"#{ticket.id} · {_status_label(ticket.status)} · {escape(ticket.subject[:60])}"
        )
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=support_tickets_kb(tickets),
    )


@router.callback_query(F.data.startswith("support:ticket:"))
async def support_ticket_view(
    callback: CallbackQuery,
    session,
    db_user: User,
):
    ticket_id = int(callback.data.split(":")[2])
    result = await session.execute(
        select(SupportTicket).where(
            SupportTicket.id == ticket_id,
            SupportTicket.user_id == db_user.id,
        )
    )
    ticket = result.scalar_one_or_none()
    if ticket is None:
        await callback.answer("⚠️ التذكرة غير موجودة.", show_alert=True)
        return

    text = (
        f"🎫 <b>التذكرة #{ticket.id}</b>\n\n"
        f"📊 الحالة: {_status_label(ticket.status)}\n"
        f"📝 العنوان: <b>{escape(ticket.subject)}</b>\n"
        f"📅 التاريخ: {ticket.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"<b>رسالتك:</b>\n{escape(ticket.message)}"
    )
    if ticket.number_order_id is not None:
        text += f"\n\n🔗 الطلب المرتبط: رقم #{ticket.number_order_id}"
    elif ticket.unified_order_id is not None:
        text += f"\n\n🔗 الطلب المرتبط: #{ticket.unified_order_id}"
    if ticket.attachment_file_id:
        text += "\n📎 أرفقت صورة مع التذكرة."
    if ticket.admin_reply:
        text += f"\n\n<b>رد الدعم:</b>\n{escape(ticket.admin_reply)}"

    await callback.message.edit_text(
        text,
        reply_markup=support_ticket_view_kb(),
    )
    await callback.answer()
