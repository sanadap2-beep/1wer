"""
🚀 معالج الإعداد السريع للزبون (3 خطوات فقط).

الهدف: الزبون المبتدئ يربط المزودين ويحط نسبة ربح
ويكبس زر واحد فتنشأ الأقسام والسيرفرات والدول
(بالعربي + العلم) تلقائياً.

الخطوات:
1) ربط المزودين: فحص مفاتيح API من .env + شرح أين يحطها.
2) نسبة الربح: رقم واحد % يُحفظ كـ default_profit_margin_percent.
3) التشغيل التلقائي: إنشاء خدمات واتساب/تيليجرام + سيرفرات
   لكل مزود مربوط + سحب الدول من كل مزود + تعريب الأسماء.
"""

from decimal import Decimal

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from config import settings
from filters.admin_filter import IsAdmin
from services.settings_service import SettingsService
from states.states import QuickSetupStates

router = Router(name="admin_quick_setup")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

PROVIDER_ENV_KEYS = [
    ("5sim", "FIVESIM_API_KEY", settings.FIVESIM_API_KEY),
    ("HeroSMS", "HEROSMS_API_KEY", settings.HEROSMS_API_KEY),
    ("SMS-Activate", "SMS_ACTIVATE_API_KEY", settings.SMS_ACTIVATE_API_KEY),
    ("SMSHub", "SMSHUB_API_KEY", settings.SMSHUB_API_KEY),
    ("SMSPool", "SMSPOOL_API_KEY", settings.SMSPOOL_API_KEY),
    ("GrizzlySMS", "GRIZZLY_API_KEY", settings.GRIZZLY_API_KEY),
]


def _wizard_kb(step: str) -> InlineKeyboardMarkup:
    if step == "step1":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 تحديث فحص المزودين", callback_data="admin:quick_setup", style="primary")],
            [InlineKeyboardButton(text="2️⃣ التالي: نسبة الربح", callback_data="admin:quick_margin", style="success")],
            [InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")],
        ])
    if step == "step2":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="3️⃣ التالي: التشغيل التلقائي", callback_data="admin:quick_run", style="success")],
            [InlineKeyboardButton(text="⬅️ رجوع لفحص المزودين", callback_data="admin:quick_setup")],
            [InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 ابدأ التشغيل التلقائي الآن", callback_data="admin:quick_run_go", style="success")],
        [InlineKeyboardButton(text="⬅️ رجوع لنسبة الربح", callback_data="admin:quick_margin")],
        [InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")],
    ])


@router.callback_query(F.data == "admin:quick_setup")
async def quick_setup_home(callback: CallbackQuery):
    lines = ["🚀 <b>الإعداد السريع — خطوة 1/3: ربط المزودين</b>\n"]
    ok_count = 0
    for label, env_key, value in PROVIDER_ENV_KEYS:
        ok = bool(value)
        ok_count += ok
        lines.append(f"{'🟢' if ok else '🔴'} <b>{label}</b> — <code>{env_key}</code> {'مربوط ✅' if ok else 'فارغ ❌'}")

    lines += [
        "",
        f"المربوط حالياً: <b>{ok_count}/6</b>",
        "",
        "📝 <b>كيف تربط مزود؟</b>",
        "1) افتح ملف <code>.env</code> بجانب <code>bot.py</code>.",
        "2) الصق مفتاح API بجانب اسم المزود.",
        "3) أعد تشغيل البوت (<code>python bot.py</code> أو <code>docker compose restart bot</code>).",
        "4) ارجع لهنا واضغط 🔄 تحديث فحص المزودين.",
        "",
        "💡 يكفي مزود واحد للبدء، وكل ما أضفت مزوداً زاد المخزون ورخصت الأسعار.",
    ]
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=_wizard_kb("step1"))
    except Exception:
        await callback.message.answer("\n".join(lines), reply_markup=_wizard_kb("step1"))
    await callback.answer()


@router.callback_query(F.data == "admin:quick_margin")
async def quick_margin_start(callback: CallbackQuery, state: FSMContext):
    current = await SettingsService.get_decimal("default_profit_margin_percent", Decimal("50"))
    try:
        await callback.message.edit_text(
            "💵 <b>الإعداد السريع — خطوة 2/3: نسبة الربح</b>\n\n"
            f"النسبة الحالية: <b>{current}%</b>\n\n"
            "أرسل رقم نسبة الربح التي تريدها على كل رقم (مثال: <code>50</code> يعني 50%).\n"
            "المسموح: من 0 إلى 500.\n\n"
            "💡 هذه النسبة العامة تُطبق على كل الخدمات، وتقدر بعدين تخصص نسبة "
            "لكل سيرفر أو دولة من: الأرقام ← تعديل الأسعار والهوامش.",
            reply_markup=_wizard_kb("step2"),
        )
    except Exception:
        await callback.message.answer(
            f"💵 النسبة الحالية: <b>{current}%</b>\nأرسل النسبة الجديدة (0-500):"
        )
    await state.set_state(QuickSetupStates.waiting_margin)
    await callback.answer()


@router.message(QuickSetupStates.waiting_margin)
async def quick_margin_received(message: Message, state: FSMContext, session):
    raw = (message.text or "").strip().replace("%", "").replace("٫", ".")
    try:
        value = Decimal(raw)
    except Exception:
        await message.answer("⚠️ أرسل رقماً فقط، مثال: <code>50</code>")
        return
    if value < 0 or value > 500:
        await message.answer("⚠️ النسبة يجب أن تكون بين 0 و 500.")
        return
    await SettingsService.set(session, "default_profit_margin_percent", str(value))
    await state.clear()
    await message.answer(
        f"✅ تم حفظ نسبة الربح: <b>{value}%</b>\n\n"
        "الخطوة الأخيرة: التشغيل التلقائي — ينشئ الأقسام والسيرفرات "
        "ويسحب الدول بالعربي + العلم من كل مزود مربوط.",
        reply_markup=_wizard_kb("step3"),
    )


@router.callback_query(F.data == "admin:quick_run")
async def quick_run_preview(callback: CallbackQuery):
    from providers.manager import provider_manager

    configured = [p.value for p in provider_manager.get_available_providers()]
    margin = await SettingsService.get_decimal("default_profit_margin_percent", Decimal("50"))
    names = ", ".join(configured) if configured else "لا يوجد — اربط مزوداً أولاً!"
    try:
        await callback.message.edit_text(
            "⚙️ <b>الإعداد السريع — خطوة 3/3: التشغيل التلقائي</b>\n\n"
            f"🔌 المزودون المربوطون: <b>{names}</b>\n"
            f"💵 نسبة الربح: <b>{margin}%</b>\n\n"
            "عند الضغط سيقوم البوت تلقائياً بـ:\n"
            "1) إنشاء قسمي <b>واتساب + تيليجرام</b> إذا لم يكونا موجودين.\n"
            "2) إنشاء <b>سيرفر 1، سيرفر 2...</b> لكل مزود مربوط داخل كل قسم.\n"
            "3) سحب <b>الدول المتاحة</b> من كل مزود مربوط.\n"
            "4) تعريب أسماء الدول + العلم 🇸🇦🇪🇬 تلقائياً.\n"
            "5) تفعيل الدول التي فيها مخزون فقط.\n\n"
            "⏳ قد تستغرق العملية دقيقة — لا تضغط مرتين.",
            reply_markup=_wizard_kb("step3"),
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "admin:quick_run_go")
async def quick_run_go(callback: CallbackQuery, session):
    from providers.manager import provider_manager
    from services.dynamic_service import DynamicService
    from services.number_server_service import NumberServerService
    from services.country_localization_service import heal_countries

    configured = [p.value for p in provider_manager.get_available_providers()]
    if not configured:
        await callback.answer("⚠️ اربط مزوداً واحداً على الأقل أولاً!", show_alert=True)
        return

    await callback.answer("⏳ بدأ التشغيل التلقائي...")
    try:
        await callback.message.edit_text(
            "⏳ <b>جاري التشغيل التلقائي...</b>\n\n"
            "ينشئ الأقسام والسيرفرات ويسحب الدول — انتظر ولا تضغط شيئاً."
        )
    except Exception:
        pass

    report_lines: list[str] = []
    try:
        # 1) ضمان قسمي واتساب + تيليجرام (نفس أكواد seed.py)
        from database.seed import DEFAULT_NUMBER_SERVICES

        services_created = 0
        for svc in DEFAULT_NUMBER_SERVICES:
            existing = await DynamicService.get_number_service_by_code(session, svc["code"])
            if not existing:
                await DynamicService.create_number_service(
                    session=session,
                    code=svc["code"],
                    name_ar=svc["name_ar"],
                    emoji=svc["emoji"],
                    fivesim_code=svc["fivesim_code"],
                    herosms_code=svc["herosms_code"],
                    sms_activate_code=svc["sms_activate_code"],
                    smshub_code=svc["smshub_code"],
                    smspool_code=svc.get("smspool_code"),
                    grizzly_code=svc.get("grizzly_code"),
                )
                services_created += 1
        report_lines.append(f"📞 الأقسام: أُنشئ <b>{services_created}</b> جديد (واتساب/تيليجرام موجودة عادة).")

        # 2) سيرفرات لكل خدمة من المزودين المربوطين
        all_services = await DynamicService.get_all_number_services(session)
        servers_total = 0
        for svc in all_services:
            created = await NumberServerService.ensure_defaults(session, svc)
            # ensure_defaults ينشئ فقط إذا لا توجد سيرفرات؛ لو موجودة نبقيها
            servers_total += len(created)
        # إعادة الترقيم لأسماء محايدة (سيرفر 1، 2...)
        renamed = await NumberServerService.renumber_all(session)
        report_lines.append(f"🖥 السيرفرات: أُنشئ <b>{servers_total}</b> سيرفر جديد، وأُعيد ترقيم <b>{renamed}</b> خدمة.")

        # 3) سحب الدول من كل مزود مربوط (واتساب + تيليجرام)
        synced_total = 0
        activated_total = 0
        if settings.HEROSMS_API_KEY:
            try:
                from services.herosms_sync_service import sync_herosms_countries

                rep = await sync_herosms_countries(session, wanted_services=["whatsapp", "telegram"], activate=True)
                synced_total += rep.fetched_countries
                activated_total += rep.activated
                report_lines.append(f"🔄 HeroSMS: فُحص <b>{rep.fetched_countries}</b> دولة، فُعّل <b>{rep.activated}</b>.")
            except Exception as e:
                report_lines.append(f"⚠️ HeroSMS فشل: {str(e)[:100]}")
        if settings.FIVESIM_API_KEY:
            try:
                from services.country_sync_service import sync_fivesim_countries

                rep = await sync_fivesim_countries(session, wanted_services=["whatsapp", "telegram"], activate=True)
                synced_total += rep.fetched_countries
                activated_total += rep.activated
                report_lines.append(f"🔄 5sim: فُحص <b>{rep.fetched_countries}</b> دولة، فُعّل <b>{rep.activated}</b>.")
            except Exception as e:
                report_lines.append(f"⚠️ 5sim فشل: {str(e)[:100]}")
        if settings.GRIZZLY_API_KEY:
            try:
                from services.country_sync_service import sync_grizzly_countries

                rep = await sync_grizzly_countries(session, wanted_services=["whatsapp", "telegram"], activate=True)
                synced_total += rep.fetched_countries
                activated_total += rep.activated
                report_lines.append(f"🐻 Grizzly: فُحص <b>{rep.fetched_countries}</b> دولة، فُعّل <b>{rep.activated}</b>.")
            except Exception as e:
                report_lines.append(f"⚠️ Grizzly فشل: {str(e)[:100]}")

        # 4) تعريب نهائي للأسماء والأعلام
        healed = await heal_countries(session)
        report_lines.append(f"🌍 التعريب: عُرّبت <b>{healed}</b> دولة (اسم عربي + علم).")

        margin = await SettingsService.get_decimal("default_profit_margin_percent", Decimal("50"))
        text = (
            "✅ <b>اكتمل الإعداد السريع!</b>\n\n"
            + "\n".join(report_lines)
            + f"\n\n💵 نسبة الربح المطبقة: <b>{margin}%</b>\n"
            "📱 جرّب الآن من حساب مستخدم: 📱 شراء أرقام ← واتساب ← سيرفر ← دولة.\n\n"
            "لتخصيص أكثر: الأرقام ← إدارة خدمات الأرقام / إدارة الدول / تعديل الأسعار والهوامش."
        )
        try:
            await callback.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📞 إدارة خدمات الأرقام", callback_data="admin:number_services", style="success")],
                    [InlineKeyboardButton(text="🌍 إدارة الدول", callback_data="admin:countries", style="success")],
                    [InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")],
                ]),
            )
        except Exception:
            await callback.message.answer(text)
    except Exception as e:
        try:
            await callback.message.edit_text(
                f"❌ فشل التشغيل التلقائي: {str(e)[:300]}\n\nتحقق من مفاتيح API وحاول مجدداً.",
                reply_markup=_wizard_kb("step3"),
            )
        except Exception:
            await callback.message.answer(f"❌ فشل: {e}")
