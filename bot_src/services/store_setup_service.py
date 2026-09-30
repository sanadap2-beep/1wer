"""
تجهيز أقسام المتجر (تُستخدم من أزرار لوحة الأدمن ومن سكربت seed_store).

- setup_hyper_section: ألعاب / تطبيقات / أرصدة (سيريتل+MTN فقط).
- setup_smm_section: الرشق — 8 تطبيقات × (متابعين/لايكات/مشاهدات) × (اقتصادي+مميز).
- كلها idempotent: تحدّث الموجود وتنشر الجديد فقط + فلتر ضد أسعار الغبار.
"""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import select

from database.models import (
    Category,
    CategoryType,
    Product,
    ProviderService,
    SubCategory,
)
from services.store_sync_service import (
    SMM_KINDS,
    ensure_smm_structure,
    existing_product_for_service,
    publish_product,
    refresh_published_price,
    suggest_smm_app,
    suggest_smm_kind,
)

SECTION_TYPES: dict[str, tuple[str, tuple[CategoryType, ...]]] = {
    "games": ("🎮 شحن الألعاب", (CategoryType.GAMES,)),
    "apps": ("📱 شحن التطبيقات", (CategoryType.APPS,)),
    "balances": ("💳 الرصيد", (CategoryType.BALANCES,)),
}


def _balance_wanted(sub_name: str) -> bool:
    n = (sub_name or "")
    up = n.upper()
    return (
        "سيريت" in n or "سيريتل" in n or "SYRIATEL" in up or up.strip() == "MTN"
    )


async def setup_hyper_section(
    session,
    provider_id: int,
    section: str,
    margin: Decimal,
    min_sell: Decimal = Decimal("0.05"),
) -> dict:
    """يجهز قسم HyperStore واحداً. يرجع إحصائيات {new, refreshed, skipped_dust, skipped}."""
    from services.dynamic_service import DynamicService
    from services.settings_service import SettingsService

    stats = {"new": 0, "refreshed": 0, "skipped_dust": 0, "skipped": 0, "title": SECTION_TYPES[section][0]}
    allowed = SECTION_TYPES[section][1]
    tree_map = json.loads(await SettingsService.get(f"store_tree_{provider_id}", "{}") or "{}")

    async def sub_for_ext(ext_id: str) -> SubCategory | None:
        node = tree_map.get(str(ext_id))
        if node and node.get("kind") == "sub":
            return await session.get(SubCategory, int(node["id"]))
        return None

    result = await session.execute(
        select(ProviderService).where(ProviderService.api_provider_id == provider_id)
    )
    for ps in list(result.scalars().all()):
        try:
            extra = json.loads(ps.raw_data or "{}")
        except Exception:
            extra = {}
        sub = await sub_for_ext(extra.get("hyper_cat", ""))
        if sub is None:
            stats["skipped"] += 1
            continue
        cat = await session.get(Category, sub.category_id)
        if cat is None or cat.type not in allowed:
            stats["skipped"] += 1
            continue
        if section == "balances" and not _balance_wanted(sub.name_ar or ""):
            stats["skipped"] += 1
            continue
        if not extra.get("quantity_options"):
            max_total = (
                ps.rate_usd * Decimal(max(1, ps.max_quantity))
                * (Decimal("100") + margin) / Decimal("100")
            )
            if max_total < min_sell:
                stats["skipped_dust"] += 1
                continue
        existing = await existing_product_for_service(session, ps.id)
        if existing:
            if await refresh_published_price(session, existing, margin):
                stats["refreshed"] += 1
            continue
        await publish_product(session, ps.id, sub.id, margin_percent=margin)
        stats["new"] += 1
    return stats


async def setup_smm_section(
    session,
    provider_id: int,
    margin: Decimal,
    min_sell: Decimal = Decimal("0.05"),
) -> dict:
    """يجهز قسم الرشق كاملاً. يرجع إحصائيات."""
    from services.dynamic_service import DynamicService

    stats = {"new": 0, "refreshed": 0, "skipped_dust": 0, "skipped": 0, "title": "📈 الرشق"}
    _cat, app_subs = await ensure_smm_structure(session)
    result = await session.execute(
        select(ProviderService).where(ProviderService.api_provider_id == provider_id)
    )
    smm_services = list(result.scalars().all())
    kind_ar = dict(SMM_KINDS)

    for app_sub in app_subs:
        app_kind, app_ar = app_sub.kind_key, app_sub.name_ar
        cands = [s for s in smm_services if suggest_smm_app(f"{s.category or ''} {s.name}") == app_kind]
        by_kind: dict[str, list] = {}
        for s in cands:
            k = suggest_smm_kind(f"{s.category or ''} {s.name}")
            if k in ("followers", "likes", "views"):
                by_kind.setdefault(k, []).append(s)
        if not by_kind:
            stats["skipped"] += 1
            continue
        for kind, items in by_kind.items():
            # 6 لكل نوع: 3 اقتصادي (الأرخص الموثوق فوق الأرضية) + 3 مميز (Refill أولاً)
            sane = [s for s in items if s.rate_usd >= Decimal("0.01") and int(s.min_quantity or 1) >= 1]
            sane.sort(key=lambda s: s.rate_usd)
            eco = sane[:3]
            refill = [s for s in sane if s.supports_refill]
            refill.sort(key=lambda s: s.rate_usd)
            pro = [s for s in refill if s not in eco][:3]
            if len(pro) < 3:
                rest = [s for s in reversed(sane) if s not in eco and s not in pro]
                pro += rest[:3 - len(pro)]
            picks = [("اقتصادي 💰", s) for s in eco] + [("مميز ⭐", s) for s in pro]
            rc = await session.execute(select(SubCategory).where(
                SubCategory.category_id == app_sub.category_id,
                SubCategory.kind_key == f"{app_kind}:{kind}",
            ))
            child = rc.scalar_one_or_none()
            if child is None:
                child = await DynamicService.create_sub_category(
                    session, category_id=app_sub.category_id,
                    name_ar=kind_ar.get(kind, kind), emoji="✨",
                    parent_sub_category_id=app_sub.id,
                    kind_key=f"{app_kind}:{kind}", sort_order=5,
                )
            for tag, svc in picks:
                existing = await existing_product_for_service(session, svc.id)
                if existing:
                    if await refresh_published_price(session, existing, margin):
                        stats["refreshed"] += 1
                    continue
                # الاسم: النوع + التطبيق + الفئة + لمحة من وصف المزود
                hint = (svc.name or "").strip()
                for drop in (app_sub.name_ar, kind_ar.get(kind, kind)):
                    hint = hint.replace(drop, "")
                hint = " ".join(hint.split())[:45]
                name = f"{kind_ar.get(kind, kind)} {app_ar} ({tag})"
                if hint:
                    name = f"{name} — {hint}"
                sell_1k = svc.rate_usd * (Decimal("100") + margin) / Decimal("100")
                if sell_1k >= Decimal("0.50"):
                    await publish_product(
                        session, svc.id, child.id, margin_percent=margin,
                        name_ar=name, min_quantity=max(int(svc.min_quantity or 1), 100),
                    )
                else:
                    pack = None
                    for cand in (1000, 2000, 5000, 10000, 25000, 50000, 100000, 500000):
                        if cand < int(svc.min_quantity or 1) or cand > int(svc.max_quantity or 0):
                            continue
                        if sell_1k * Decimal(cand) / Decimal("1000") >= min_sell:
                            pack = cand
                            break
                    if pack is None:
                        stats["skipped_dust"] += 1
                        continue
                    pack_price = (sell_1k * Decimal(pack) / Decimal("1000")).quantize(Decimal("0.0001"))
                    pack_cost = (svc.rate_usd * Decimal(pack) / Decimal("1000")).quantize(Decimal("0.0001"))
                    prod = await publish_product(
                        session, svc.id, child.id, margin_percent=margin,
                        name_ar=f"{name} — باقة {pack}", min_quantity=pack,
                    )
                    await DynamicService.update_product(
                        session, prod.id, max_quantity=pack, requires_quantity=False,
                        price_usd=pack_price, cost_price_usd=pack_cost,
                    )
                stats["new"] += 1
    return stats


def format_stats(stats: dict) -> str:
    return (
        f"✅ <b>اكتمل تجهيز {stats.get('title', 'القسم')}!</b>\n\n"
        f"🆕 منتجات جديدة: <b>{stats.get('new', 0)}</b>\n"
        f"♻️ أسعار حدثت: <b>{stats.get('refreshed', 0)}</b>\n"
        f"🗑 تخطي غبار: <b>{stats.get('skipped_dust', 0)}</b>"
    )
