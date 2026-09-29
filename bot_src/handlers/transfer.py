"""
💱 تحويل الرصيد بين المستخدمين (بعمولة اختيارية من اللوحة).

التدفق: زر بحسابي ← آيدي المستلم ← المبلغ ← تأكيد يعرض الصافي والعمولة.
"""

from decimal import Decimal

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from database.models import User
from services.balance_service import BalanceService, InsufficientBalanceError
from services.notification_service import NotificationService
from services.settings_service import SettingsService


class TransferStates(StatesGroup):
    waiting_recipient = State()
    waiting_amount = State()


router = Router(name="transfer")


async def _fee_percent(session) -> Decimal:
    return await SettingsService.get_decimal("transfer_fee_percent", Decimal("0"))


async def _min_amount(session) -> Decimal:
    return await SettingsService.get_decimal("transfer_min_usd", Decimal("0.5"))


@router.callback_query(F.data == "transfer:start")
async def transfer_start(callback: CallbackQuery, state: FSMContext, session, db_user):
    if db_user.is_banned:
        await callback.answer("⚠️ حسابك محظور.", show_alert=True)
        return
    min_amount = await _min_amount(session)
    await callback.message.edit_text(
        f"💱 <b>تحويل الرصيد</b>\n\n💰 رصيدك: <b>{db_user.balance}$</b>\n"
        f"الحد الأدنى: <b>{min_amount}$</b>\n\n"
        "أرسل <b>آيدي تيليجرام الرقمي</b> للمستلم (مثال: <code>123456789</code>):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ إلغاء", callback_data="menu:account", style="danger")]
        ]),
    )
    await state.set_state(TransferStates.waiting_recipient)
    await callback.answer()


@router.message(TransferStates.waiting_recipient)
async def transfer_recipient(message: Message, state: FSMContext, session, db_user):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("⚠️ أرسل الآيدي الرقمي فقط.")
        return
    tg_id = int(raw)
    if tg_id == db_user.telegram_id:
        await message.answer("⚠️ لا يمكنك التحويل لنفسك.")
        return
    result = await session.execute(select(User).where(User.telegram_id == tg_id))
    recipient = result.scalar_one_or_none()
    if recipient is None:
        await message.answer("⚠️ هذا المستخدم غير مسجل بالبوت — اطلب منه يضغط /start أولاً.")
        return
    if recipient.is_banned:
        await message.answer("⚠️ هذا الحساب محظور.")
        return
    await state.update_data(transfer_to_id=recipient.id, transfer_to_tg=tg_id)
    min_amount = await SettingsService.get_decimal("transfer_min_usd", Decimal("0.5"))
    await message.answer(
        f"👤 المستلم: <code>{tg_id}</code>\n\nأرسل المبلغ بالدولار (أدنى {min_amount}$):"
    )
    await state.set_state(TransferStates.waiting_amount)


@router.message(TransferStates.waiting_amount)
async def transfer_amount(message: Message, state: FSMContext, session, db_user):
    data = await state.get_data()
    try:
        amount = Decimal((message.text or "").strip())
    except Exception:
        await message.answer("⚠️ أرسل رقماً فقط.")
        return
    min_amount = await SettingsService.get_decimal("transfer_min_usd", Decimal("0.5"))
    fee_pct = await SettingsService.get_decimal("transfer_fee_percent", Decimal("0"))
    if amount < min_amount:
        await message.answer(f"⚠️ أدنى تحويل {min_amount}$.")
        return
    if amount <= 0 or amount > Decimal("100000"):
        await message.answer("⚠️ مبلغ غير صالح.")
        return
    fee = (amount * fee_pct / Decimal("100")).quantize(Decimal("0.0001"))
    net = amount - fee
    if db_user.balance < amount:
        await message.answer(f"❌ رصيدك ({db_user.balance}$) لا يكفي ({amount}$).")
        return
    await state.update_data(transfer_amount=str(amount))
    await message.answer(
        "🧾 <b>تأكيد التحويل</b>\n\n"
        f"👤 إلى: <code>{data.get('transfer_to_tg')}</code>\n"
        f"💰 المبلغ: <b>{amount}$</b>\n"
        + (f"💸 العمولة ({fee_pct}%): {fee}$\n✅ يصل المستلم: <b>{net}$</b>\n" if fee > 0 else "") +
        "\nتأكيد نهائي؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ تأكيد التحويل", callback_data="transfer:confirm", style="primary")],
            [InlineKeyboardButton(text="❌ إلغاء", callback_data="menu:account", style="danger")],
        ]),
    )


@router.callback_query(F.data == "transfer:confirm")
async def transfer_confirm(callback: CallbackQuery, session, db_user, state: FSMContext, bot):
    from database.models import TransactionType

    data = await state.get_data()
    to_id, amount = int(data.get("transfer_to_id", 0)), Decimal(str(data.get("transfer_amount", "0")))
    if not to_id or amount <= 0:
        await callback.answer("⚠️ انتهت الجلسة.", show_alert=True)
        return
    fee_pct = await SettingsService.get_decimal("transfer_fee_percent", Decimal("0"))
    fee = (amount * fee_pct / Decimal("100")).quantize(Decimal("0.0001"))
    net = amount - fee
    await state.clear()
    try:
        _src, recipient, _tr = await BalanceService.transfer(session, db_user.id, to_id, net)
        if fee > 0:
            await BalanceService.deduct_balance(
                session, db_user.id, fee, TransactionType.TRANSFER_OUT,
                description=f"عمولة تحويل إلى {recipient.telegram_id}",
            )
    except InsufficientBalanceError:
        await callback.answer("❌ رصيد غير كافٍ.", show_alert=True)
        return
    except ValueError as exc:
        await callback.answer(str(exc)[:120], show_alert=True)
        return
    notifier = NotificationService(bot)
    await callback.message.edit_text(
        f"✅ تم التحويل: <b>{net}$</b> إلى <code>{recipient.telegram_id}</code>"
        + (f" (عمولة {fee}$)" if fee > 0 else "")
    )
    try:
        await notifier.notify_user(
            recipient.telegram_id,
            f"📥 <b>وصلك تحويل!</b>\n\n💰 المبلغ: <b>{net}$</b>\n👤 من: <code>{db_user.telegram_id}</code>",
        )
    except Exception:
        pass
    await callback.answer("✅ تم التحويل")
