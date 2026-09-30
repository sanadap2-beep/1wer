"""
⚡ معالج تجهيز أقسام المتجر — زر لكل قسم.

- 🎮 تجهيز قسم شحن الألعاب (كل الألعاب بفروعها الداخلية)
- 📱 تجهيز قسم شحن التطبيقات
- 💳 تجهيز قسم الأرصدة (سيريتل + MTN)
- 📈 تجهيز قسم الرشق (8 تطبيقات × خدمات × منتجات)

الضغطة → عرض النطاق → إدخال نسبة الربح → تجهيز كامل بالعربي مع الأسعار.
"""

from decimal import Decimal
from html import escape

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from database.models import ApiProvider, ApiProtocolType
from filters.admin_filter import IsAdmin
from services.dynamic_service import DynamicService
from services.settings_service import SettingsService
from states.states import AdminStoreSetupStates

router = Router(name="admin_store_setup")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

SECTIONS: dict[str, dict] = {
    "games": {
        "title": "🎮 تجهيز قسم شحن الألعاب",
        "desc": "كل الألعاب المسحوبة بفروعها الداخلية (PUBG بفئاتها، فري فاير...) — أسماء عربية + أسعار بعد هامشك.",
        "hyper": True,
    },
    "apps": {
        "title": "📱 تجهيز قسم شحن التطبيقات",
        "desc": "كل التطبيقات المسحوبة بفروعها — أسماء عربية + أسعار بعد هامشك.",
        "hyper": True,
    },
    "balances": {
        "title": "💳 تجهيز قسم الأرصدة",
        "desc": "سيريتل (54 فئة) + MTN + الكاش والفواتير — بفئاتها الثابتة وأسعارها.",
        "hyper": True,
    },
    "smm": {
        "title": "📈 تجهيز قسم الرشق",
        "desc": "8 تطبيقات (انستا/تيك توك/يوتيوب/تيليجرام/فيسبوك/واتساب/سناب/تويتر) — لكل تطبيق متابعين/لايكات/مشاهدات × (اقتصادي + مميز).",
        "hyper": False,
    },
}


async def _find_provider(session, hyper: bool) -> ApiProvider | None:
    providers = await DynamicService.get_all_providers(session)
    for p in providers:
        if not p.is_active:
            continue
        if hyper:
            from protocols.hyper_store import is_hyper_store_provider

            if is_hyper_store_provider(p):
                return p
        elif p.protocol_type == ApiProtocolType.SMM_V2:
            return p
    return None


@router.callback_query(F.data.startswith("admin:setup:"))
async def setup_start(callback: CallbackQuery, session, state: FSMContext):
    section = callback.data.rsplit(":", 1)[1]
    cfg = SECTIONS.get(section)
    if not cfg:
        await callback.answer("⚠️ قسم غير معروف.", show_alert=True)
        return
    provider = await _find_provider(session, cfg["hyper"])
    if provider is None:
        kind = "HyperStore" if cfg["hyper"] else "SMM"
        await callback.message.edit_text(
            f"{cfg['title']}\n\n⚠️ لا يوجد مزود {kind} مربوط ومفعّل.\n\n"
            "اربطه أولاً من: 🔌 مزودو المتجر ← إضافة مزود ← 🩺 فحص ← 🔄 مزامنة، ثم ارجع هنا.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔌 مزودو المتجر", callback_data="admin:store_providers", style="success")],
                [InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")],
            ]),
        )
        await callback.answer()
        return
    if not provider.total_services:
        await callback.message.edit_text(
            f"{cfg['title']}\n\n⚠️ كتالوج المزود فارغ — اعمل 🔄 مزامنة الكتالوج أولاً من صفحة المزود.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔌 مزودو المتجر", callback_data="admin:store_providers", style="success")],
                [InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")],
            ]),
        )
        await callback.answer()
        return
    margin = await SettingsService.get_decimal("default_profit_margin_percent", Decimal("50"))
    await state.update_data(setup_section=section)
    await callback.message.edit_text(
        f"{cfg['title']}\n\n{cfg['desc']}\n\n"
        f"🔌 المزود: <b>{provider.name}</b> ({provider.total_services} خدمة مسحوبة)\n"
        f"💵 الهامش المقترح: <b>{margin}%</b>\n\n"
        "أرسل نسبة الربح % لهذا القسم (مثال: <code>50</code>)، أو أرسل <code>-</code> للقبول بالمقترح:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ إلغاء", callback_data="admin:main", style="danger")]
        ]),
    )
    await state.set_state(AdminStoreSetupStates.waiting_margin)
    await callback.answer()


@router.message(AdminStoreSetupStates.waiting_margin)
async def setup_margin_received(message: Message, state: FSMContext, session):
    from services.store_setup_service import (
        format_stats, setup_hyper_section, setup_smm_section,
    )

    data = await state.get_data()
    section = data.get("setup_section", "")
    cfg = SECTIONS.get(section)
    if not cfg:
        await state.clear()
        await message.answer("⚠️ انتهت الجلسة — ابدأ من جديد.")
        return
    raw = message.text.strip().replace("%", "")
    if raw == "-":
        margin = await SettingsService.get_decimal("default_profit_margin_percent", Decimal("50"))
    else:
        try:
            margin = Decimal(raw)
        except Exception:
            await message.answer("⚠️ أرسل رقماً فقط (مثال: <code>50</code>) أو <code>-</code>.")
            return
        if margin < 0 or margin > 500:
            await message.answer("⚠️ بين 0 و 500 فقط.")
            return
    await state.clear()
    provider = await _find_provider(session, cfg["hyper"])
    if provider is None:
        await message.answer("⚠️ المزود غير متوفر حالياً.")
        return
    status = await message.answer(
        f"⏳ <b>جاري تجهيز {cfg['title']}...</b>\n\n"
        f"بهامش {margin}%. سيتم تحديث كتالوج المزود أولاً؛ لا تضغط شيئاً حتى ينتهي."
    )
    try:
        if cfg["hyper"]:
            from services.store_sync_service import sync_provider

            sync_report = await sync_provider(session, provider)
            if sync_report.error:
                text = (
                    f"❌ <b>تعذرت مزامنة كتالوج {escape(provider.name)}</b>\n\n"
                    f"<code>{escape(sync_report.error[:250])}</code>\n\n"
                    "لم أتابع نشر المنتجات حتى لا أترك القسم ناقصاً. افحص اتصال المزود ثم أعد المحاولة."
                )
                raise RuntimeError(text)
            if not sync_report.total_services:
                text = (
                    f"⚠️ <b>لم يُرجع مزود {escape(provider.name)} أي خدمة.</b>\n\n"
                    "لم أتابع تجهيز القسم. افحص اتصال المزود والكتالوج ثم أعد المحاولة."
                )
                raise RuntimeError(text)

            await status.edit_text(
                f"✅ تم تحديث الكتالوج ({sync_report.total_services} خدمة).\n"
                f"⏳ جاري تجهيز {cfg['title']} بهامش {margin}%..."
            )
            stats = await setup_hyper_section(session, provider.id, section, margin)
        else:
            stats = await setup_smm_section(session, provider.id, margin)
        text = format_stats(stats)
        ready_count = sum(
            int(stats.get(key, 0) or 0)
            for key in ("new", "refreshed", "existing", "relinked")
        )
        if ready_count:
            text += "\n\n✅ القسم يحتوي الآن على منتجات منشورة."
        else:
            text += "\n\n⚠️ لم يُنشأ أو يُحدّث أي منتج؛ القسم غير جاهز للبيع بعد."
            if stats.get("no_map"):
                text += (
                    f"\nما زالت {stats['no_map']} خدمة بلا ربط تصنيفي بعد مزامنة الكتالوج. "
                    "راجع تصنيفات المزود أو تواصل مع دعم المزود."
                )
    except Exception as exc:
        error_text = str(exc)
        if error_text.startswith(("❌", "⚠️")):
            text = error_text
        else:
            text = f"❌ فشل التجهيز: <code>{escape(error_text[:250])}</code>"
    try:
        await status.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔌 صفحة المزود", callback_data=f"admin:store_prov:{provider.id}")],
            [InlineKeyboardButton(text="📁 أقسام المتجر", callback_data="admin:store_cats", style="success")],
            [InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")],
        ]))
    except Exception:
        await message.answer(text)
