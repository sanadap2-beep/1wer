"""
تهيئة قاعدة البيانات عند أول تشغيل:
1) إنشاء كل الجداول.
2) زرع الإعدادات الافتراضية بالدولار.
3) تسجيل الأدمن من ADMIN_IDS.
4) صفوف مبدئية لحالة المزودين.
5) باقات نجوم افتراضية.
6) خدمات أرقام افتراضية.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import inspect, select, text

from config import settings
from database.engine import engine, async_session_maker
from database.migrations import run_migrations
from database.models import (
    Base,
    Setting,
    User,
    ProviderStatus,
    ProviderName,
    StarsPackage,
    NumberService,
)

DEFAULT_SETTINGS = {
    # ── مالي ──
    "default_profit_margin_percent": str(settings.DEFAULT_PROFIT_MARGIN_PERCENT),
    "large_transaction_threshold_usd": str(settings.LARGE_TRANSACTION_THRESHOLD_USD),
    "referral_bonus_usd": str(settings.REFERRAL_BONUS_USD),
    "referral_percent": str(settings.REFERRAL_PERCENT),
    "cashback_percent": str(settings.CASHBACK_PERCENT),
    "loyalty_points_per_usd": str(settings.LOYALTY_POINTS_PER_USD),
    "loyalty_daily_points": str(settings.LOYALTY_DAILY_POINTS),
    "loyalty_points_per_usd_redeem": str(settings.LOYALTY_POINTS_PER_USD_REDEEM),
    "loyalty_min_redeem_points": str(settings.LOYALTY_MIN_REDEEM_POINTS),
    "stars_rate_usd": str(settings.STARS_RATE_USD),
    "large_order_confirm_usd": str(settings.LARGE_ORDER_CONFIRM_USD),
    # ── سعر الصرف USD → SYP ──
    "usd_to_syp_rate": str(settings.DEFAULT_USD_TO_SYP_RATE),
    # ── أسعار صرف العرض اليومية USD → EUR / EGP ──
    "usd_to_eur_rate": "0.92",
    "usd_to_egp_rate": "48.5",
    # ── الحدود الدنيا لكل طريقة دفع ──
    "min_deposit_shamcash_usd": str(settings.MIN_DEPOSIT_SHAMCASH_USD),
    "min_deposit_usdt_usd": str(settings.MIN_DEPOSIT_USDT_USD),
    "min_deposit_stars_usd": str(settings.MIN_DEPOSIT_STARS_USD),
    "plisio_fee_percent": str(settings.PLISIO_FEE_PERCENT),
    "plisio_min_amount_usd": str(settings.PLISIO_MIN_AMOUNT_USD),
    "plisio_max_amount_usd": str(settings.PLISIO_MAX_AMOUNT_USD),
    # ── عناوين المحافظ اليدوية ──
    "shamcash_manual_address": settings.SHAMCASH_MANUAL_ADDRESS,
    "shamcash_manual_name": settings.SHAMCASH_MANUAL_NAME,
    "usdt_trc20_address": settings.USDT_TRC20_ADDRESS,
    "usdt_erc20_address": settings.USDT_ERC20_ADDRESS,
    "usdt_bep20_address": settings.USDT_BEP20_ADDRESS,
    # ── تفعيل/تعطيل طرق الدفع ──
    "payment_shamcash_manual_enabled": "true",
    "payment_stars_enabled": "true",
    "payment_usdt_manual_enabled": "true",
    "payment_shamcash_auto_enabled": "true",
    "payment_usdt_auto_enabled": "true",
    "payment_other_enabled": "true",
    # ── السحب ──
    "withdraw_min_usd": "1",
    "withdraw_shamcash_syp_enabled": "true",
    # ── شروحات طرق الدفع ──
    "payment_shamcash_manual_description": (
        "💵 <b>الشحن اليدوي عبر شام كاش</b>\n\n"
        "1️⃣ أدخل المبلغ المراد إيداعه بالدولار\n"
        "2️⃣ سيظهر لك عنوان المحفظة\n"
        "3️⃣ حوّل المبلغ من تطبيق شام كاش\n"
        "4️⃣ أرسل صورة إثبات التحويل\n"
        "5️⃣ أرسل رقم العملية\n"
        "6️⃣ انتظر موافقة الإدارة\n\n"
        "⏱ عادة تتم الموافقة خلال 5-15 دقيقة."
    ),
    "payment_usdt_manual_description": (
        "₮ <b>الشحن اليدوي عبر USDT</b>\n\n"
        "1️⃣ اختر الشبكة (TRC20 الأرخص)\n"
        "2️⃣ أدخل المبلغ بالدولار\n"
        "3️⃣ سيظهر لك عنوان المحفظة\n"
        "4️⃣ حوّل المبلغ\n"
        "5️⃣ أرسل صورة إثبات + رقم العملية (TX Hash)\n"
        "6️⃣ انتظر موافقة الإدارة\n\n"
        "⚠️ <b>تنبيه:</b> تأكد من اختيار الشبكة الصحيحة!\n"
        "الأموال المرسلة عبر شبكة خاطئة قد تُفقد نهائياً."
    ),
    "payment_shamcash_auto_description": (
        "💳 <b>الشحن الفوري عبر شام كاش (تلقائي)</b>\n\n"
        "1️⃣ اختر العملة (USD أو SYP)\n"
        "2️⃣ أدخل المبلغ\n"
        "3️⃣ سيظهر لك عنوان الاستلام مع QR Code\n"
        "4️⃣ حوّل المبلغ من تطبيق شام كاش\n"
        "5️⃣ أدخل رقم العملية\n"
        "6️⃣ سيتم التحقق تلقائياً وإضافة الرصيد فوراً\n\n"
        "⚡ <b>سريع وفوري - لا يحتاج انتظار الأدمن!</b>\n"
        "⏱ مهلة الفاتورة: 15 دقيقة"
    ),
    "payment_usdt_auto_description": (
        "₮ <b>الشحن الفوري عبر USDT (تلقائي)</b>\n\n"
        "1️⃣ أدخل المبلغ بالدولار\n"
        "2️⃣ سيظهر لك عنوان المحفظة\n"
        "3️⃣ حوّل المبلغ\n"
        "4️⃣ يتم فحص الدفع كل 15 ثانية\n"
        "5️⃣ عند وصول التحويل يُضاف الرصيد فوراً\n\n"
        "⚡ <b>لا حاجة لإدخال رقم العملية!</b>\n"
        "⏱ مهلة الفاتورة: 30 دقيقة"
    ),
    "payment_other_description": (
        "📞 <b>طرق دفع أخرى</b>\n\n"
        "إذا كنت تريد الدفع بطريقة غير متاحة حالياً "
        "(سيرياتل كاش، MTN كاش، تحويل بنكي، بايير، إلخ)\n\n"
        "تواصل مع الدعم الفني:\n"
        "{support_username}"
    ),
    # ── نظام الطلبات ──
    "order_timeout_minutes": str(settings.ORDER_TIMEOUT_MINUTES),
    "max_active_orders": str(settings.MAX_ACTIVE_ORDERS),
    "rate_limit_seconds": str(settings.RATE_LIMIT_SECONDS),
    "provider_low_balance_threshold": str(settings.PROVIDER_LOW_BALANCE_THRESHOLD),
    # ── إعدادات عامة ──
    "require_subscription_for_referral": (
        "true" if settings.REQUIRE_SUBSCRIPTION_FOR_REFERRAL else "false"
    ),
    "support_username": settings.SUPPORT_USERNAME,
    "payment_method_text": settings.PAYMENT_METHOD_TEXT,
    # ── الصيانة ──
    "maintenance_mode": "false",
    "maintenance_message": "⚙️ البوت تحت الصيانة حالياً، سيعود قريباً...",
    # ── القنوات ──
    "public_channel_id": str(settings.PUBLIC_CHANNEL_ID),
    "backup_channel_id": str(settings.BACKUP_CHANNEL_ID),
    # ── رسالة الترحيب ──
    "welcome_message": ("👋 أهلاً بك في البوت!\n\nاختر من القائمة للبدء."),
}

DEFAULT_STARS_PACKAGES = [
    {"stars_amount": 50, "usd_amount": "0.65", "label": "⭐ 50 نجمة", "sort_order": 1},
    {"stars_amount": 100, "usd_amount": "1.30", "label": "⭐ 100 نجمة", "sort_order": 2},
    {"stars_amount": 250, "usd_amount": "3.25", "label": "⭐ 250 نجمة", "sort_order": 3},
    {"stars_amount": 500, "usd_amount": "6.50", "label": "⭐ 500 نجمة", "sort_order": 4},
    {"stars_amount": 1000, "usd_amount": "13.00", "label": "⭐ 1000 نجمة", "sort_order": 5},
    {"stars_amount": 2500, "usd_amount": "32.50", "label": "⭐ 2500 نجمة", "sort_order": 6},
]

DEFAULT_NUMBER_SERVICES = [
    {
        "code": "whatsapp",
        "name_ar": "واتساب",
        "emoji": "💬",
        "fivesim_code": "whatsapp",
        "herosms_code": "wa",
        "sms_activate_code": "wa",
        "smshub_code": "whatsapp",
        "smspool_code": "whatsapp",
        "grizzly_code": "wa",
        "sort_order": 1,
    },
    {
        "code": "telegram",
        "name_ar": "تيليجرام",
        "emoji": "✈️",
        "fivesim_code": "telegram",
        "herosms_code": "tg",
        "sms_activate_code": "tg",
        "smshub_code": "telegram",
        "smspool_code": "telegram",
        "grizzly_code": "tg",
        "sort_order": 2,
    },
]


async def init_db() -> None:
    # Alembic is the source of truth for new schemas and future upgrades.
    # create_all remains as a compatibility fallback for legacy databases.
    await run_migrations()

    # ── إنشاء الجداول (legacy compatibility) ──
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # ترقية قاعدة بيانات قديمة بدون الحاجة لإسقاط بيانات المستخدمين.
        # create_all لا يضيف أعمدة جديدة إلى الجداول الموجودة.
        if conn.dialect.name == "sqlite":
            columns = await conn.run_sync(
                lambda sync_conn: {
                    column["name"] for column in inspect(sync_conn).get_columns("transactions")
                }
            )
            if "payment_reference" not in columns:
                await conn.execute(
                    text("ALTER TABLE transactions ADD COLUMN payment_reference VARCHAR(255)")
                )

            # المرجع الفريد يمنع مضاعفة رصيد دفعة واحدة عند تزامن
            # المراقب مع زر الفحص أو عند إعادة إرسال تحديث Telegram.
            await conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ix_transactions_payment_reference "
                    "ON transactions(payment_reference) "
                    "WHERE payment_reference IS NOT NULL"
                )
            )

            # حقول الولاء الجديدة تُضاف تلقائياً للقواعد القديمة.
            user_columns = await conn.run_sync(
                lambda sync_conn: {
                    column["name"] for column in inspect(sync_conn).get_columns("users")
                }
            )
            for name, definition in (
                ("loyalty_points", "INTEGER DEFAULT 0"),
                ("loyalty_streak", "INTEGER DEFAULT 0"),
                ("last_checkin_date", "DATE"),
                ("language_code", "VARCHAR(8) DEFAULT 'ar'"),
            ):
                if name not in user_columns:
                    await conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {definition}"))

            product_columns = await conn.run_sync(
                lambda sync_conn: {
                    column["name"] for column in inspect(sync_conn).get_columns("products")
                }
            )
            if "fulfillment_type" not in product_columns:
                await conn.execute(
                    text(
                        "ALTER TABLE products ADD COLUMN fulfillment_type VARCHAR(16) DEFAULT 'API'"
                    )
                )

            order_columns = await conn.run_sync(
                lambda sync_conn: {
                    column["name"] for column in inspect(sync_conn).get_columns("unified_orders")
                }
            )
            if "promotion_id" not in order_columns:
                await conn.execute(
                    text("ALTER TABLE unified_orders ADD COLUMN promotion_id INTEGER")
                )

            # ملفات الجلسات الجاهزة: ترقية قواعد جرّبت النسخة الأولى قبل دمجها.
            tg_tables = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
            if "tg_ready_items" in tg_tables:
                tg_ready_columns = await conn.run_sync(
                    lambda sync_conn: {
                        column["name"]
                        for column in inspect(sync_conn).get_columns("tg_ready_items")
                    }
                )
                if "files_json" not in tg_ready_columns:
                    await conn.execute(text("ALTER TABLE tg_ready_items ADD COLUMN files_json TEXT"))

    async with async_session_maker() as session:
        # ── زرع الإعدادات الافتراضية ──
        for key, value in DEFAULT_SETTINGS.items():
            existing = await session.get(Setting, key)
            if existing is None:
                session.add(Setting(key=key, value=value))

        # ── زرع قسمَي الذكاء الاصطناعي الافتراضيين (مرة واحدة، معطّلين حتى
        #    يضبط الأدمن مفتاح NanoGPT ويفعّلهما من اللوحة) ──
        if await session.get(Setting, "ai_sections_seeded") is None:
            from database.models import AiSection

            session.add_all([
                AiSection(
                    key="coding",
                    name_ar="برمجة بدون قيود",
                    description_ar=(
                        "اطلب أي كود أو سكربت أو أداة أو ملف كامل بأي لغة برمجة، "
                        "والنتيجة توصلك ملفاً جاهزاً للتحميل."
                    ),
                    kind="coding",
                    model="z-ai/glm-4.6",
                    cost_per_message_usd=Decimal("0.003"),
                    profit_multiplier=3.0,
                    enabled=False,
                    sort_order=10,
                ),
                AiSection(
                    key="chat",
                    name_ar="تحدث بدون قيود",
                    description_ar=(
                        "دردشة حرة مع ذكاء اصطناعي — اسأل عن أي شيء، تحدث بأي لغة، "
                        "والموديل يتذكر سياق محادثتك الحالية."
                    ),
                    kind="chat",
                    model="z-ai/glm-4.6",
                    cost_per_message_usd=Decimal("0.001"),
                    profit_multiplier=3.0,
                    enabled=False,
                    sort_order=20,
                ),
            ])
            session.add(Setting(key="ai_sections_seeded", value="true"))
            await session.commit()

        # ── تسجيل الأدمن ──
        for admin_tg_id in settings.admin_ids_list:
            result = await session.execute(select(User).where(User.telegram_id == admin_tg_id))
            user = result.scalar_one_or_none()
            if user is None:
                session.add(
                    User(
                        telegram_id=admin_tg_id,
                        is_admin=True,
                        is_activated=True,
                        full_name="Admin",
                    )
                )
            elif not user.is_admin:
                user.is_admin = True

        # ── زرع حالة المزودين ──
        for provider in ProviderName:
            existing = await session.get(ProviderStatus, provider)
            if existing is None:
                session.add(ProviderStatus(provider=provider, is_online=False))

        # ── زرع باقات النجوم الافتراضية ──
        result = await session.execute(select(StarsPackage))
        existing_packages = result.scalars().all()
        if not existing_packages:
            for pkg in DEFAULT_STARS_PACKAGES:
                from decimal import Decimal as D

                session.add(
                    StarsPackage(
                        stars_amount=pkg["stars_amount"],
                        usd_amount=D(pkg["usd_amount"]),
                        label=pkg["label"],
                        sort_order=pkg["sort_order"],
                        is_active=True,
                    )
                )

        # ── زرع قوالب الإشعارات الافتراضية ──
        from services.notification_center_service import NotificationCenterService

        await NotificationCenterService.seed_templates(session)

        # ── زرع خدمات الأرقام الافتراضية ──
        for svc in DEFAULT_NUMBER_SERVICES:
            result = await session.execute(
                select(NumberService).where(NumberService.code == svc["code"])
            )
            existing_svc = result.scalar_one_or_none()
            if existing_svc is None:
                session.add(
                    NumberService(
                        code=svc["code"],
                        name_ar=svc["name_ar"],
                        emoji=svc["emoji"],
                        fivesim_code=svc["fivesim_code"],
                        herosms_code=svc["herosms_code"],
                        sms_activate_code=svc["sms_activate_code"],
                        smshub_code=svc["smshub_code"],
                        smspool_code=svc.get("smspool_code"),
                        grizzly_code=svc.get("grizzly_code"),
                        sort_order=svc["sort_order"],
                        is_active=True,
                    )
                )
            else:
                if getattr(existing_svc, "smspool_code", None) is None and svc.get("smspool_code"):
                    # تعبئة رجعية: خدمات قديمة (واتساب/تيليجرام) بلا كود SMSPool
                    existing_svc.smspool_code = svc["smspool_code"]
                if getattr(existing_svc, "grizzly_code", None) is None and svc.get("grizzly_code"):
                    # تعبئة رجعية: خدمات قديمة بلا كود GrizzlySMS
                    existing_svc.grizzly_code = svc["grizzly_code"]

        await session.commit()
