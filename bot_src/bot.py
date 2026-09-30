"""
الملف الرئيسي لتشغيل البوت.
"""

import asyncio
import logging

from aiogram import Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from services.html_guard import HtmlGuardedBot
from database.engine import async_session_maker
from database.seed import init_db

from middlewares.db_session import DbSessionMiddleware
from middlewares.user_middleware import UserMiddleware
from middlewares.subscription_middleware import SubscriptionMiddleware
from middlewares.state_reset_middleware import StateResetMiddleware
from middlewares.throttling import GlobalThrottlingMiddleware
from middlewares.error_middleware import ErrorReportingMiddleware, install_asyncio_exception_handler

from handlers import (
    start,
    support,
    account,
    referral,
    referral_guard,
    deposit,
    notifications,
    bot_info,
    numbers,
    store,
    cart,
    transfer,
    storefind,
    status,
    language,
    currency,
    reviews,
    watch,
    offers,
    traders,
    tg_ready as user_tg_ready,
    fallback,
)
from handlers.deposit_methods import router as deposit_methods_router
from handlers.deposit_credit import router as deposit_credit_router
from handlers.error_reports import router as error_reports_router
from handlers.admin import (
    panel as admin_panel,
    quick_setup as admin_quick_setup,
    store_providers as admin_store_providers,
    store_sections as admin_store_sections,
    store_setup as admin_store_setup,
    coupons as admin_coupons,
    broadcast as admin_broadcast,
    channels as admin_channels,
    countries as admin_countries,
    deposits as admin_deposits,
    users as admin_users,
    pricing as admin_pricing,
    providers as admin_providers,
    stats as admin_stats,
    settings as admin_settings,
    support as admin_support,
    audit as admin_audit,
    health as admin_health,
    number_services as admin_number_services,
    number_orders as admin_number_orders,
    notifications as admin_notifications,
    stars as admin_stars,
    bot_guide as admin_bot_guide,
    main_buttons as admin_main_buttons,
    multi_admin as admin_multi_admin,
    features as admin_features,
    ledger as admin_ledger,
    live_feed as admin_live_feed,
    tg_ready as admin_tg_ready,
)

from tasks.order_monitor import (
    check_pending_orders,
    update_provider_status,
    cleanup_balance_locks,
)
from tasks.store_monitor import check_store_orders_job
from tasks.invoice_monitor import check_pending_invoices
from tasks.backup_job import daily_backup
from services.feature_service import FeatureService
from services.bot_command_service import SentinelService
from services.observability import init_observability
from services.plisio_service import plisio_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
init_observability()

bot = HtmlGuardedBot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
storage = RedisStorage.from_url(settings.REDIS_URL) if settings.REDIS_URL else MemoryStorage()
dp = Dispatcher(storage=storage)


def register_middlewares():
    db_mw = DbSessionMiddleware()
    user_mw = UserMiddleware()
    state_reset_mw = StateResetMiddleware()
    throttle_mw = GlobalThrottlingMiddleware()
    sub_mw = SubscriptionMiddleware(bot)
    error_mw = ErrorReportingMiddleware()

    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(error_mw)
        observer.outer_middleware(db_mw)
        observer.outer_middleware(user_mw)
        observer.outer_middleware(state_reset_mw)
        observer.outer_middleware(throttle_mw)
        observer.outer_middleware(sub_mw)


def register_routers():
    # ── نسخة الأرقام فقط ──
    dp.include_router(start.router)
    dp.include_router(support.router)
    dp.include_router(account.router)
    dp.include_router(referral.router)
    dp.include_router(deposit.router)
    dp.include_router(deposit_methods_router)
    dp.include_router(deposit_credit_router)
    dp.include_router(notifications.router)
    dp.include_router(bot_info.router)
    dp.include_router(numbers.router)
    dp.include_router(store.router)
    dp.include_router(cart.router)
    dp.include_router(storefind.router)
    dp.include_router(transfer.router)
    dp.include_router(reviews.router)
    dp.include_router(watch.router)
    dp.include_router(offers.router)
    dp.include_router(traders.router)
    dp.include_router(traders.admin_router)
    dp.include_router(user_tg_ready.router)
    dp.include_router(status.router)
    dp.include_router(language.router)
    dp.include_router(currency.router)
    dp.include_router(referral_guard.router)

    # ── أدمن الأرقام فقط ──
    dp.include_router(admin_panel.router)
    dp.include_router(admin_quick_setup.router)
    dp.include_router(admin_store_providers.router)
    dp.include_router(admin_store_sections.router)
    dp.include_router(admin_store_setup.router)
    dp.include_router(admin_coupons.router)
    dp.include_router(admin_broadcast.router)
    dp.include_router(admin_channels.router)
    dp.include_router(admin_countries.router)
    dp.include_router(admin_deposits.router)
    dp.include_router(admin_users.router)
    dp.include_router(admin_pricing.router)
    dp.include_router(admin_providers.router)
    dp.include_router(admin_stats.router)
    dp.include_router(admin_ledger.router)
    dp.include_router(admin_settings.router)
    dp.include_router(admin_support.router)
    dp.include_router(admin_audit.router)
    dp.include_router(admin_health.router)
    dp.include_router(admin_number_services.router)
    dp.include_router(admin_number_orders.router)
    dp.include_router(admin_notifications.router)
    dp.include_router(admin_stars.router)
    dp.include_router(admin_bot_guide.router)
    dp.include_router(admin_main_buttons.router)
    dp.include_router(admin_multi_admin.router)
    dp.include_router(admin_features.router)
    dp.include_router(admin_live_feed.router)
    dp.include_router(admin_tg_ready.router)

    dp.include_router(error_reports_router)

    dp.include_router(fallback.router)


async def availability_board_cycle(bot):
    """التوفر المتقطع: تحديث لوحة الدول الجاهزة في القناة كل دورة."""
    if not await FeatureService.enabled("numbers_availability_board"):
        return
    from services.availability_board_service import AvailabilityBoardService

    try:
        await AvailabilityBoardService.post_board(bot)
    except Exception:
        logger.exception("فشل نشر لوحة التوفر المتقطع")


async def sentinel_cycle(bot):
    """الحارس الذاتي: يراقب معدل الأخطاء ويدخل الوضع الآمن عند الحاجة."""
    from database.engine import async_session_maker

    if not await SentinelService.enabled():
        return
    try:
        async with async_session_maker() as session:
            result = await SentinelService.check(session)
            action = result.get("action")

            if action == "engaged":
                disabled = result.get("disabled", [])
                logger.warning("الحارس أدخل البوت الوضع الآمن: %s", disabled)
                from services.notification_service import NotificationService

                bullets = "".join(f"• {key}\n" for key in disabled)
                await NotificationService(bot).notify_admin(
                    "🛡 <b>الحارس الذاتي فعّل الوضع الآمن</b>\n\n"
                    f"معدل الأخطاء: {result.get('error_rate')}\n"
                    f"عُطّلت {len(disabled)} ميزة خطرة:\n"
                    f"{bullets}\n"
                    "ستُعاد تلقائياً حين يستقر المعدل."
                )
            elif action == "disengaged":
                restored = result.get("restored", [])
                logger.info("الحارس أخرج البوت من الوضع الآمن.")
                from services.notification_service import NotificationService

                await NotificationService(bot).notify_admin(
                    "✅ <b>استقر الوضع — خرج البوت من الوضع الآمن</b>\n\n"
                    f"أُعيدت {len(restored)} ميزة."
                )
    except Exception:
        logger.exception("فشل دورة الحارس")


async def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    order_poll_seconds = max(
        3,
        await FeatureService.config_int(
            "instant_delivery", "poll_interval_seconds", 15
        ),
    )
    scheduler.add_job(
        check_pending_orders,
        "interval",
        seconds=order_poll_seconds,
        args=[bot],
    )

    scheduler.add_job(
        check_pending_invoices,
        "interval",
        seconds=max(5, settings.PLISIO_POLLING_INTERVAL_SECONDS),
        args=[bot],
    )

    scheduler.add_job(
        check_store_orders_job,
        "interval",
        seconds=60,
        args=[bot],
    )

    scheduler.add_job(
        update_provider_status,
        "interval",
        minutes=10,
        args=[bot],
    )

    scheduler.add_job(
        cleanup_balance_locks,
        "interval",
        minutes=5,
    )

    scheduler.add_job(
        daily_backup,
        "cron",
        hour=3,
        minute=0,
        args=[bot],
    )

    scheduler.add_job(
        availability_board_cycle,
        "interval",
        seconds=max(
            30,
            await FeatureService.config_int(
                "numbers_availability_board", "refresh_seconds", 60
            ),
        ),
        args=[bot],
    )

    scheduler.add_job(
        sentinel_cycle,
        "interval",
        minutes=5,
        args=[bot],
    )

    scheduler.start()
    return scheduler


async def main():
    logger.info("⏳ جاري تهيئة قاعدة البيانات...")
    await init_db()
    # ترقيات alembic تستدعي fileConfig من alembic.ini (root=WARN) فتمسح
    # إعداد السجلات — نعيد ضبطها هنا ليبقى INFO ظاهراً أثناء التشغيل.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )
    await FeatureService.sync_registry()
    await FeatureService.reload()
    # ترميم أسماء الدول الأجنبية (من المزود) إلى العربية + العلم الصحيح.
    # لا يلمس أكواد الربط مع المزودين إطلاقاً.
    try:
        from services.country_localization_service import heal_countries

        async with async_session_maker() as session:
            healed = await heal_countries(session)
            if healed:
                logger.info("🌍 عُرّبت %s دولة أجنبية.", healed)
    except Exception:
        logger.exception("فشل ترميم أسماء الدول")

    # ترقيم سيرفرات الأرقام: المستخدم يجب ألا يرى اسم المزود (5sim/HeroSMS...)
    # بل «سيرفر 1، سيرفر 2...». القواعد القديمة حفظت أسماء المزودين، فنعيد
    # ترقيمها مرة واحدة عند الإقلاع.
    try:
        from services.number_server_service import NumberServerService

        async with async_session_maker() as session:
            renamed = await NumberServerService.renumber_all(session)
            if renamed:
                logger.info("🖥 أُعيد ترقيم سيرفرات %s خدمة أرقام.", renamed)
    except Exception:
        logger.exception("فشل ترقيم سيرفرات الأرقام")

    logger.info(f"🔑 آيديات الأدمن: {settings.admin_ids_list}")
    logger.info("✅ قاعدة البيانات جاهزة.")

    register_middlewares()
    register_routers()
    install_asyncio_exception_handler(bot)
    scheduler = await start_scheduler()

    logger.info("🚀 البوت يعمل الآن...")
    try:
        # الشبكة نحو api.telegram.org قد تكون متقطعة (Connection reset).
        # نعيد المحاولة عدة مرات، وإن فشلت كلها نتابع للـ polling بدل أن يسقط البوت.
        for attempt in range(1, 6):
            try:
                await bot.delete_webhook(drop_pending_updates=True, request_timeout=20)
                break
            except Exception as exc:
                logger.warning("تعذّر حذف الـ webhook (محاولة %s/5): %s", attempt, exc)
                if attempt >= 5:
                    logger.warning("المتابعة إلى الـ polling بدون حذف الـ webhook.")
                    break
                await asyncio.sleep(3 * attempt)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await plisio_client.close()
        await bot.session.close()
        if hasattr(storage, "close"):
            await storage.close()
        logger.info("🛑 البوت توقف.")


if __name__ == "__main__":
    asyncio.run(main())
