"""
مهمة متابعة طلبات المتجر: فحص دوري كل دقيقة.
"""

import logging

logger = logging.getLogger(__name__)

_tick = 0


async def check_store_orders_job(bot):
    global _tick
    _tick += 1
    from services.store_order_service import check_store_orders

    try:
        stats = await check_store_orders(bot)
        if stats.get("checked"):
            logger.info("طلبات المتجر: %s", stats)
    except Exception:
        logger.exception("فشل فحص طلبات المتجر")
    if _tick % 10 != 0:
        # العروض والتنبيهات كل ~10 دقائق تكفي
        return
    try:
        from database.engine import async_session_maker
        from services.offer_service import expire_due

        async with async_session_maker() as session:
            expired = await expire_due(session)
            if expired:
                logger.info("انتهت %s عروض مؤقتة", expired)
    except Exception:
        logger.exception("فشل إنهاء العروض المنتهية")
    try:
        from services.watch_service import WatchService

        sent = await WatchService.check_all(bot)
        if sent:
            logger.info("تنبيهات المنتجات المرسلة: %s", sent)
    except Exception:
        logger.exception("فشل فحص تنبيهات المنتجات")
