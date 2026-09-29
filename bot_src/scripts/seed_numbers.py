#!/usr/bin/env python3
"""تجهيز الأرقام بضربة واحدة: واتساب + تيليجرام × سيرفر لكل مزود.

ينشئ قسمي الأرقام، ويبقي سيرفراً واحداً لكل مزود مربوط داخل كل قسم
(الزبون يرى «سيرفر 1، سيرفر 2» فقط)، ويسحب الدول المتاحة مع التعريب،
ويضبط الهوامش — بما فيها الجلسات الجاهزة.

الاستخدام (على السيرفر بجانب bot.py بعد تجهيز .env):
  HEROSMS_API_KEY=... GRIZZLY_API_KEY=... python scripts/seed_numbers.py

ملاحظة: المفاتيح تُقرأ أيضاً من .env تلقائياً إن وُجدت فيه —
مررها هنا فقط إذا لم تضعها في .env بعد.

متغيرات اختيارية:
  MARGIN=50   نسبة الربح % للأرقام والجلسات

آمن لإعادة التشغيل: يوحّد السيرفرات ولا يكرر، ويحدّث الأسعار.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("seed_numbers")

# المفاتيح الممررة هنا تسبق .env (تُحقن قبل استيراد الإعدادات)
for _env_key in ("HEROSMS_API_KEY", "GRIZZLY_API_KEY"):
    if os.environ.get(_env_key):
        os.environ[_env_key] = os.environ[_env_key].strip()

MARGIN = Decimal(os.environ.get("MARGIN", "50"))

TARGET_PROVIDERS = ("herosms", "grizzly")
SERVICE_CODES = ("whatsapp", "telegram")


async def main() -> None:
    from sqlalchemy import select

    from database.seed import init_db
    from database.engine import async_session_maker
    from database.models import NumberService, ProviderName
    from providers.manager import provider_manager
    from services.country_localization_service import heal_countries
    from services.dynamic_service import DynamicService
    from services.number_server_service import NumberServerService
    from services.tg_ready_service import TgReadyService

    print("⏳ تهيئة قاعدة البيانات...")
    await init_db()

    available = {p.value for p in provider_manager.get_available_providers()}
    print(f"🔑 المزودون المربوطون: {sorted(available) or 'لا يوجد!'}")
    missing = [v for v in TARGET_PROVIDERS if v not in available]
    if missing:
        print(f"⚠️ بلا مفاتيح (سيرفراتها ستكون فارغة): {missing}")
        print("   أضفها في .env أو مررها مع الأمر ثم أعد التشغيل.")

    async with async_session_maker() as session:
        # ── 1) القسمان + أكوادهما ──
        from database.seed import DEFAULT_NUMBER_SERVICES

        wanted = {s["code"]: s for s in DEFAULT_NUMBER_SERVICES if s["code"] in SERVICE_CODES}
        for code, spec in wanted.items():
            svc = await DynamicService.get_number_service_by_code(session, code)
            if svc is None:
                svc = await DynamicService.create_number_service(
                    session, code=code, name_ar=spec["name_ar"], emoji=spec["emoji"],
                    fivesim_code=None, herosms_code=spec["herosms_code"],
                    sms_activate_code=None, smshub_code=None,
                    smspool_code=None, grizzly_code=spec["grizzly_code"],
                )
                print(f"➕ قسم جديد: {spec['name_ar']}")
            else:
                updates = {}
                if not svc.herosms_code:
                    updates["herosms_code"] = spec["herosms_code"]
                if not getattr(svc, "grizzly_code", None):
                    updates["grizzly_code"] = spec["grizzly_code"]
                if not svc.is_active:
                    updates["is_active"] = True
                if updates:
                    await DynamicService.update_number_service(session, svc.id, **updates)
                    print(f"♻️ حدثت أكواد قسم: {svc.name_ar}")

        # ── 2) سيرفر واحد لكل مزود داخل كل قسم ──
        for code in SERVICE_CODES:
            svc = await DynamicService.get_number_service_by_code(session, code)
            if svc is None:
                continue
            servers = await NumberServerService.list_servers(session, svc.id, active_only=False)
            by_provider: dict[str, list] = {}
            for s in servers:
                by_provider.setdefault(s.provider, []).append(s)
            for provider_value in TARGET_PROVIDERS:
                rows = by_provider.get(provider_value, [])
                if not rows:
                    created = await NumberServerService.create(
                        session, number_service_id=svc.id,
                        name_ar="سيرفر", provider=provider_value,
                        margin_percent=MARGIN, sort_order=10,
                    )
                    print(f"➕ سيرفر {provider_value} في {svc.name_ar}")
                    rows = [created]
                else:
                    # إبقاء الأول فقط + توحيد الهامش والتفعيل
                    for extra in rows[1:]:
                        await NumberServerService.delete(session, extra.id)
                        print(f"🗑 حذف سيرفر زائد ({provider_value}) في {svc.name_ar}")
                    await NumberServerService.update(
                        session, rows[0].id, is_active=True, margin_percent=MARGIN,
                    )
            # حذف سيرفرات مزودين خارج النطاق
            for provider_value, rows in by_provider.items():
                if provider_value not in TARGET_PROVIDERS:
                    for s in rows:
                        await NumberServerService.delete(session, s.id)
                        print(f"🗑 حذف سيرفر خارج النطاق ({provider_value}) في {svc.name_ar}")
            renamed = await NumberServerService.renumber(session, svc.id)
            if renamed:
                print(f"🔢 أُعيد ترقيم سيرفرات {svc.name_ar}")
            # تعليم أول سيرفر شغّالاً إن لم يوجد
            active = await NumberServerService.list_servers(session, svc.id, active_only=True)
            if active and not any(getattr(s, "is_working", False) for s in active):
                await NumberServerService.set_working(session, active[0].id, True, exclusive=True)
                print(f"🟢 عُلّم سيرفر 1 شغّالاً في {svc.name_ar}")

        # ── 3) سحب الدول من المزودين ──
        if "herosms" in available:
            print("🔄 سحب دول HeroSMS (واتساب + تيليجرام)...")
            from services.herosms_sync_service import sync_herosms_countries

            rep = await sync_herosms_countries(session, wanted_services=list(SERVICE_CODES), activate=True)
            print(f"   فُحص {rep.fetched_countries} دولة — فُعّل {rep.activated}")
        if "grizzly" in available:
            print("🔄 سحب دول GrizzlySMS (واتساب + تيليجرام)...")
            from services.country_sync_service import sync_grizzly_countries

            rep = await sync_grizzly_countries(session, wanted_services=list(SERVICE_CODES), activate=True)
            print(f"   فُحص {rep.fetched_countries} دولة — فُعّل {rep.activated}")
        healed = await heal_countries(session)
        print(f"🌍 عُرّبت {healed} دولة")

        # ── 4) هوامش الجلسات الجاهزة ──
        await TgReadyService.set_margin(session, MARGIN)
        print(f"📦 هامش الجلسات الجاهزة: {MARGIN}% (ارفع ملفاتها من اللوحة لاحقاً)")

        # ── 5) الأرصدة ──
        for provider_value in TARGET_PROVIDERS:
            try:
                bal = await provider_manager.get_balance(ProviderName(provider_value))
                print(f"💰 رصيد {provider_value}: {bal}$")
            except Exception as exc:
                print(f"⚠️ تعذر جلب رصيد {provider_value}: {str(exc)[:100]}")

    print("\n✅ اكتمل تجهيز الأرقام — شغّل البوت: python bot.py")


if __name__ == "__main__":
    asyncio.run(main())
