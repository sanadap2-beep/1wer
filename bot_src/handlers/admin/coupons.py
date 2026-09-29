"""
🎟 إدارة الكوبونات وأكواد الحملات.

- إنشاء: الكود ← النوع والقيمة (20% أو 5) ← الحدود (استخدامات، أدنى طلب، أيام، مصدر).
- تفعيل/تعطيل/حذف + عرض الاستخدام.
"""

from decimal import Decimal

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from database.models import CampaignCode, Coupon
from filters.admin_filter import IsAdmin
from services import coupon_service
from states.states import AdminCouponStates

router = Router(name="admin_coupons")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def _lists_text(session) -> tuple[str, InlineKeyboardMarkup]:
    coupons = list((await session.execute(select(Coupon).order_by(Coupon.id.desc()).limit(15))).scalars().all())
    camps = list((await session.execute(select(CampaignCode).order_by(CampaignCode.id.desc()).limit(15))).scalars().all())
    lines = ["🎟 <b>الكوبونات والحملات</b>\n"]
    rows: list[list[InlineKeyboardButton]] = []
    if coupons:
        lines.append("<b>الكوبونات:</b>")
        for c in coupons:
            mark = "🟢" if c.is_active else "⚪"
            unit = "%" if c.discount_type == "percent" else "$"
            lines.append(f"{mark} <code>{c.code}</code> — {c.discount_value}{unit} ({c.used_count}/{c.max_uses})")
            rows.append([InlineKeyboardButton(text=f"{mark} {c.code}", callback_data=f"admin:coupon_view:coupon:{c.id}")])
    if camps:
        lines.append("\n<b>الحملات:</b>")
        for c in camps:
            mark = "🟢" if c.is_active else "⚪"
            unit = "%" if c.discount_type == "percent" else "$"
            lines.append(f"{mark} <code>{c.code}</code>{' [' + c.tracking + ']' if c.tracking else ''} — {c.discount_value}{unit} ({c.used_count}/{c.max_uses})")
            rows.append([InlineKeyboardButton(text=f"{mark} {c.code}", callback_data=f"admin:coupon_view:campaign:{c.id}")])
    if not coupons and not camps:
        lines.append("لا توجد أكواد بعد — أنشئ أول حملة لجلب الزبائن.")
    rows.append([InlineKeyboardButton(text="➕ كوبون جديد", callback_data="admin:coupon_add:coupon", style="success")])
    rows.append([InlineKeyboardButton(text="➕ حملة جديدة", callback_data="admin:coupon_add:campaign", style="success")])
    rows.append([InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "admin:coupons")
async def coupons_list(callback: CallbackQuery, session):
    text, kb = await _lists_text(session)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:coupon_view:"))
async def coupon_view(callback: CallbackQuery, session):
    _, _, kind, cid = callback.data.split(":")
    if kind == "campaign":
        row = await session.get(CampaignCode, int(cid))
    else:
        row = await session.get(Coupon, int(cid))
    if not row:
        await callback.answer("⚠️ غير موجود.", show_alert=True)
        return
    unit = "%" if row.discount_type == "percent" else "$"
    extra = f"\n📣 المصدر: {row.tracking}" if kind == "campaign" and row.tracking else ""
    exp = row.expires_at.strftime("%Y-%m-%d") if row.expires_at else "بلا نهاية"
    await callback.message.edit_text(
        f"🎟 <code>{row.code}</code>\n\n"
        f"الخصم: <b>{row.discount_value}{unit}</b> ({'نسبة' if row.discount_type == 'percent' else 'مبلغ ثابت'})\n"
        f"الاستخدام: {row.used_count}/{row.max_uses} | أدنى طلب: {row.min_order_usd}$\n"
        f"الصلاحية: {exp} | الحالة: {'🟢' if row.is_active else '⚪'}{extra}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="⏸ تعطيل" if row.is_active else "▶️ تفعيل",
                callback_data=f"admin:coupon_toggle:{kind}:{row.id}",
                style="danger" if row.is_active else "success")],
            [InlineKeyboardButton(text="🗑 حذف", callback_data=f"admin:coupon_del:{kind}:{row.id}", style="danger")],
            [InlineKeyboardButton(text="🔙 الكوبونات", callback_data="admin:coupons")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:coupon_add:"))
async def coupon_add_start(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.rsplit(":", 1)[1]
    await state.update_data(coupon_kind=kind)
    label = "حملة" if kind == "campaign" else "كوبون"
    await callback.message.edit_text(
        f"➕ <b>{label} جديد (1/3)</b>\n\nأرسل الكود (إنجليزي بدون مسافات، مثال: <code>WELCOME20</code>):"
    )
    await state.set_state(AdminCouponStates.waiting_code)
    await callback.answer()


@router.message(AdminCouponStates.waiting_code)
async def coupon_code_received(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper().replace(" ", "_")
    if not code or len(code) > 32 or not code.replace("_", "").replace("-", "").isalnum():
        await message.answer("⚠️ كود غير صالح — إنجليزي/أرقام فقط.")
        return
    await state.update_data(coupon_code=code)
    await message.answer("💵 <b>(2/3)</b> أرسل القيمة: نسبة مثل <code>20%</code> أو مبلغ ثابت مثل <code>5</code> (= 5$):")
    await state.set_state(AdminCouponStates.waiting_value)


@router.message(AdminCouponStates.waiting_value)
async def coupon_value_received(message: Message, state: FSMContext):
    raw = (message.text or "").strip().replace("%", "").replace("٫", ".")
    is_percent = "%" in (message.text or "")
    try:
        value = Decimal(raw)
    except Exception:
        await message.answer("⚠️ أرسل رقماً فقط.")
        return
    if value <= 0 or (is_percent and value > 100):
        await message.answer("⚠️ قيمة غير صالحة (النسبة حتى 100).")
        return
    await state.update_data(coupon_type="percent" if is_percent else "fixed", coupon_value=str(value))
    await message.answer(
        "⚙️ <b>(3/3)</b> أرسل الحدود بصيغة: <code>استخدامات أدنى_طلب أيام</code>\n"
        "مثال: <code>100 2 30</code> (100 استخدام، طلبات فوق 2$، 30 يوماً).\n"
        "أرسل <code>-</code> للافتراضي (100/0/30). للحملة أضف المصدر رابعاً: <code>100 0 30 tiktok</code>"
    )
    await state.set_state(AdminCouponStates.waiting_limits)


@router.message(AdminCouponStates.waiting_limits)
async def coupon_limits_received(message: Message, state: FSMContext, session):
    data = await state.get_data()
    raw = (message.text or "").strip()
    max_uses, min_order, days, tracking = 100, Decimal("0"), 30, ""
    if raw != "-":
        parts = raw.split()
        try:
            if len(parts) >= 1:
                max_uses = max(1, int(parts[0]))
            if len(parts) >= 2:
                min_order = Decimal(parts[1])
            if len(parts) >= 3:
                days = max(0, int(parts[2]))
            if len(parts) >= 4:
                tracking = parts[3][:64]
        except Exception:
            await message.answer("⚠️ صيغة غير صالحة — مثال: <code>100 2 30</code> أو <code>-</code>.")
            return
    try:
        row = await coupon_service.create_code(
            session, kind=data["coupon_kind"], created_by=message.from_user.id,
            code=data["coupon_code"], discount_type=data["coupon_type"],
            value=Decimal(data["coupon_value"]), max_uses=max_uses,
            min_order_usd=min_order, days_valid=days, tracking=tracking,
        )
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    except Exception:
        await message.answer("⚠️ هذا الكود موجود مسبقاً.")
        await state.clear()
        return
    await state.clear()
    unit = "%" if row.discount_type == "percent" else "$"
    await message.answer(
        f"✅ تم إنشاء الكود: <code>{row.code}</code> — خصم {row.discount_value}{unit}\n"
        f"شاركه مع الزبائن الآن 🎉",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎟 الكوبونات", callback_data="admin:coupons", style="success")]
        ]),
    )


@router.callback_query(F.data.startswith("admin:coupon_toggle:"))
async def coupon_toggle(callback: CallbackQuery, session):
    _, _, kind, cid = callback.data.split(":")
    row = await session.get(CampaignCode if kind == "campaign" else Coupon, int(cid))
    if row:
        row.is_active = not row.is_active
        await session.commit()
    await callback.answer("✅ تم.")
    await coupons_list(callback, session)


@router.callback_query(F.data.startswith("admin:coupon_del:"))
async def coupon_delete(callback: CallbackQuery, session):
    _, _, kind, cid = callback.data.split(":")
    row = await session.get(CampaignCode if kind == "campaign" else Coupon, int(cid))
    if row:
        await session.delete(row)
        await session.commit()
    await callback.answer("🗑 تم الحذف.")
    await coupons_list(callback, session)
