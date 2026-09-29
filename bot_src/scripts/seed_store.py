#!/usr/bin/env python3
"""التجهيز الشامل للمتجر بضربة واحدة (بدون لوحة أدمن).

ينشئ المزودين، يزامن الكتالوجات، يبني الأقسام، وينشر باقة منقاة
جاهزة للبيع: كل الألعاب + سيريتل/MTN + رشق (رخيص + جودة).

الاستخدام (على السيرفر بجانب bot.py بعد تجهيز .env):
  HYPERSTORE_API_KEY=... SMM_API_KEY=... python scripts/seed_store.py

متغيرات اختيارية:
  MARGIN=50        نسبة الربح % على كل المنتجات الجديدة
  MIN_SELL=0.05    تجاهل المنتجات ثابتة السعر الأرخص من هذا (ضد الغبار)
  HYPER_URL=https://api.hyper4store.com
  SMM_URL=https://smmprovider.co/api/v2

آمن لإعادة التشغيل: يحدّث الموجود ولا يكرر، وينشر الجديد فقط.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("seed_store")

MARGIN = Decimal(os.environ.get("MARGIN", "50"))
MIN_SELL = Decimal(os.environ.get("MIN_SELL", "0.05"))
HYPER_URL = os.environ.get("HYPER_URL", "https://api.hyper4store.com")
SMM_URL = os.environ.get("SMM_URL", "https://smmprovider.co/api/v2")


async def main() -> None:
    hyper_key = os.environ.get("HYPERSTORE_API_KEY", "").strip()
    smm_key = os.environ.get("SMM_API_KEY", "").strip()
    if not hyper_key or not smm_key:
        print("⚠️ ضع المفتاحين أولاً:")
        print("  HYPERSTORE_API_KEY=... SMM_API_KEY=... python scripts/seed_store.py")
        sys.exit(1)

    from sqlalchemy import select

    from database.seed import init_db
    from database.engine import async_session_maker
    from database.models import (
        ApiProvider, ApiProviderType, ApiProtocolType,
    )
    from services.dynamic_service import DynamicService
    from services.store_setup_service import (
        setup_hyper_section, setup_smm_section,
    )
    from services.store_sync_service import sync_provider

    print("⏳ تهيئة قاعدة البيانات...")
    await init_db()

    async with async_session_maker() as session:
        # ── 1) المزودان ──
        async def ensure_provider(ptype, name, url, key, proto, config):
            r = await session.execute(select(ApiProvider).where(ApiProvider.api_url == url))
            p = r.scalar_one_or_none()
            if p is None:
                p = await DynamicService.create_provider(
                    session, name=name, provider_type=ptype, api_url=url, api_key=key,
                    protocol_type=proto, custom_config=config,
                )
                print(f"➕ مزود جديد: {name}")
            else:
                p.api_key = key
                p.is_active = True
                await session.commit()
                print(f"♻️ مزود موجود: {p.name}")
            return p

        hyper = await ensure_provider(
            ApiProviderType.STORE, "المتجر الرئيسي (HyperStore)", HYPER_URL, hyper_key,
            ApiProtocolType.CUSTOM, json.dumps({"engine": "hyper_store"}),
        )
        smm = await ensure_provider(
            ApiProviderType.SMM, "لوحة الرشق (SMM)", SMM_URL, smm_key,
            ApiProtocolType.SMM_V2, None,
        )

        # ── 2) المزامنة ──
        print("🔄 مزامنة HyperStore (قد تأخذ دقيقة)...")
        rep_h = await sync_provider(session, hyper)
        print("  " + rep_h.summary().replace("\n", " | "))
        if rep_h.error:
            print("❌ توقف: فشلت مزامنة HyperStore")
            sys.exit(2)
        print("🔄 مزامنة SMM...")
        rep_s = await sync_provider(session, smm)
        print("  " + rep_s.summary().replace("\n", " | "))
        print(f"💰 الأرصدة: Hyper={hyper.balance}$ | SMM={smm.balance}$")

        # خريطة الشجرة: hyper_cat → sub محلي
        from services.settings_service import SettingsService

        tree_map = json.loads(await SettingsService.get(f"store_tree_{hyper.id}", "{}") or "{}")

        stats = {"new": 0, "refreshed": 0, "skipped_dust": 0, "skipped": 0}

        # ── 3) نشر HyperStore: ألعاب + تطبيقات + سيريتل/MTN فقط ──
        for section in ("games", "apps", "balances"):
            part = await setup_hyper_section(session, hyper.id, section, MARGIN, MIN_SELL)
            for key in ("new", "refreshed", "skipped_dust", "skipped"):
                stats[key] += part.get(key, 0)
            print(f"  {part['title']}: جديد {part['new']} | حدث {part['refreshed']} | غبار {part['skipped_dust']}")

        # ── 4) الرشق: لكل تطبيق (متابعين/لايكات/مشاهدات) × (اقتصادي + مميز) ──
        part = await setup_smm_section(session, smm.id, MARGIN, MIN_SELL)
        for key in ("new", "refreshed", "skipped_dust", "skipped"):
            stats[key] += part.get(key, 0)
        print(f"  {part['title']}: جديد {part['new']} | حدث {part['refreshed']} | غبار {part['skipped_dust']}")

        print("\n✅ اكتمل التجهيز:")
        print(f"  🆕 منتجات جديدة: {stats['new']}")
        print(f"  ♻️ أسعار حدثت: {stats['refreshed']}")
        print(f"  🗑 تخطي غبار: {stats['skipped_dust']} | تخطي خارج النطاق: {stats['skipped']}")
        print("\nالخطوة الأخيرة: اشحن رصيد المزودين ثم شغّل البوت (python bot.py)")


if __name__ == "__main__":
    asyncio.run(main())
