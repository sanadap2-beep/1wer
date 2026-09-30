"""
تجهيز أقسام المتجر (تُستخدم من أزرار لوحة الأدمن ومن سكربت seed_store).

- setup_hyper_section: ألعاب / تطبيقات / أرصدة (سيريتل+MTN فقط).
- setup_smm_section: الرشق — 8 تطبيقات × (متابعين/لايكات/مشاهدات) × (اقتصادي+مميز).
- كلها idempotent: تحدّث الموجود وتنشر الجديد فقط + فلتر ضد أسعار الغبار.
"""

from __future__ import annotations

import json
from decimal import Decimal
from html import escape

from sqlalchemy import select

from database.models import (
    Category,
    CategoryType,
    Product,
    ProductStatus,
    ProviderService,
    ProviderServiceStatus,
    SubCategory,
)
from services.store_sync_service import (
    SMM_KINDS,
    ensure_smm_structure,
    existing_product_for_service,
    publish_product,
    refresh_published_price,
    suggest_smm_service_app,
    suggest_smm_kind,
)

SECTION_TYPES: dict[str, tuple[str, tuple[CategoryType, ...]]] = {
    "games": ("🎮 شحن الألعاب", (CategoryType.GAMES,)),
    "apps": ("📱 شحن البرامج والاشتراكات", (CategoryType.APPS,)),
    "balances": ("💳 الأرصدة", (CategoryType.BALANCES,)),
}

SMM_PACK_OPTIONS = (100, 250, 500, 750, 1000, 2000, 5000, 10000, 25000, 50000, 100000, 500000)


def _balance_wanted(sub_name: str) -> bool:
    n = (sub_name or "")
    up = n.upper()
    return (
        "سيريت" in n or "سيريتل" in n or "SYRIATEL" in up or up.strip() == "MTN"
    )


def _select_smm_tiers(
    items: list,
    floor: Decimal,
    margin: Decimal,
    min_sell: Decimal,
) -> tuple[list, list, int]:
    """يعيد حتى 3 اقتصادية و3 مميزة من خدمات المزود المؤهلة دون تكرار."""
    sane = [
        svc for svc in items
        if svc.rate_usd >= floor
        and int(svc.min_quantity or 1) >= 1
        and int(svc.max_quantity or 0) >= int(svc.min_quantity or 1)
        and (
            svc.rate_usd * (Decimal("100") + margin) / Decimal("100") >= Decimal("0.50")
            or any(
                int(svc.min_quantity or 1) <= quantity <= int(svc.max_quantity or 0)
                and svc.rate_usd * (Decimal("100") + margin) / Decimal("100")
                * Decimal(quantity) / Decimal("1000") >= min_sell
                for quantity in SMM_PACK_OPTIONS
            )
        )
    ]
    sane.sort(key=lambda svc: (svc.rate_usd, str(svc.external_service_id)))
    economic = sane[:3]
    economic_ids = {svc.id for svc in economic}
    refill = [svc for svc in sane if svc.supports_refill and svc.id not in economic_ids]
    premium = refill[:3]
    premium_ids = {svc.id for svc in premium}
    if len(premium) < 3:
        rest = [svc for svc in reversed(sane) if svc.id not in economic_ids | premium_ids]
        premium.extend(rest[: 3 - len(premium)])
    return economic, premium, len(sane)


def _instagram_follower_description(service, tier: str) -> str:
    """وصف عربي يوضح الفئة والحدود وخصائص خدمة المزود الفعلية."""
    if tier == "اقتصادي":
        tier_text = "خيار اقتصادي من خدمات المزود، مختار ضمن الأقل سعراً."
    elif service.supports_refill:
        tier_text = "خيار مميز، وخدمة المزود تدعم إعادة التعبئة."
    else:
        tier_text = "خيار مميز بسعر أعلى ضمن الخدمات المتاحة لدى المزود."
    refill_text = "متاحة" if service.supports_refill else "غير متاحة"
    description = (
        f"خدمة متابعين لحساب إنستغرام. {tier_text} "
        f"الكمية المسموحة: من {int(service.min_quantity or 1)} إلى "
        f"{int(service.max_quantity or 1)}. إعادة التعبئة {refill_text}."
    )
    provider_description = (service.description or "").strip()
    if provider_description:
        prefix = "\nتفاصيل المزود: "
        description += prefix
        budget = max(0, 295 - len(description))
        escaped_detail: list[str] = []
        used = 0
        for char in provider_description:
            safe_char = escape(char)
            if used + len(safe_char) > budget:
                break
            escaped_detail.append(safe_char)
            used += len(safe_char)
        description += "".join(escaped_detail)
    return description


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

    stats = {
        "new": 0, "refreshed": 0, "existing": 0, "relinked": 0,
        "skipped_dust": 0, "skipped": 0,
        "no_map": 0, "wrong_type": 0, "filtered": 0,
        "title": SECTION_TYPES[section][0],
    }
    allowed = SECTION_TYPES[section][1]
    tree_map = json.loads(await SettingsService.get(f"store_tree_{provider_id}", "{}") or "{}")
    from services.store_sync_service import activate_all_games, normalize_section_roots

    await normalize_section_roots(session)

    async def sub_for_ext(ext_id: str) -> SubCategory | None:
        node = tree_map.get(str(ext_id))
        if not node:
            return None
        if node.get("kind") == "sub":
            sub = await session.get(SubCategory, int(node["id"]))
            return sub
        if node.get("kind") == "cat":
            # منتجات على الجذر مباشرة → فرع "عام" تحته
            cat = await session.get(Category, int(node["id"]))
            if cat is None:
                return None
            from services.store_sync_service import _ensure_general_sub

            return await _ensure_general_sub(session, cat.id)
        return None

    async def sub_by_category_name(provider_cat: str) -> SubCategory | None:
        """احتياطي للخدمات القديمة بلا hyper_cat: مطابقة اسم تصنيف المزود لفرع محلي."""
        from services.store_sync_service import AR_TITLES

        wanted = (provider_cat or "").strip().lower()
        if not wanted:
            return None
        # مرادفات إنجليزية ← عربية من قاموس التعريب
        aliases = {wanted}
        for eng, ar in AR_TITLES.items():
            if eng in wanted or wanted in eng:
                aliases.add(ar.lower())
        result = await session.execute(select(SubCategory))
        best = None
        for sub in result.scalars().all():
            name = (sub.name_ar or "").strip().lower()
            if not name:
                continue
            if any(a == name or a in name or name in a for a in aliases):
                cat = await session.get(Category, sub.category_id)
                if cat is not None and cat.type in allowed:
                    if best is None or len(name) > len((best.name_ar or "")):
                        best = sub
        return best

    result = await session.execute(
        select(ProviderService).where(ProviderService.api_provider_id == provider_id)
    )
    for ps in list(result.scalars().all()):
        try:
            extra = json.loads(ps.raw_data or "{}")
        except Exception:
            extra = {}
        sub = await sub_for_ext(extra.get("hyper_cat", ""))
        category_hint = extra.get("category", "") or ps.category or ""
        if sub is not None:
            mapped_cat = await session.get(Category, sub.category_id)
            if mapped_cat is None or mapped_cat.type not in allowed:
                sub = None
        # كتالوجات HyperStore القديمة أو المعاد بناؤها قد تحمل ربط شجرة غير صالح.
        # جرّب اسم التصنيف قبل إسقاط الخدمة حتى لا تختفي الألعاب القابلة للتصنيف.
        if sub is None:
            sub = await sub_by_category_name(category_hint)
        if sub is None:
            stats["skipped"] += 1
            stats["no_map"] += 1
            continue
        cat = await session.get(Category, sub.category_id)
        if cat is None or cat.type not in allowed:
            stats["skipped"] += 1
            stats["wrong_type"] += 1
            continue
        if section == "balances" and not _balance_wanted(sub.name_ar or ""):
            stats["skipped"] += 1
            stats["filtered"] += 1
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
            if existing.sub_category_id != sub.id:
                await DynamicService.update_product(
                    session, existing.id, sub_category_id=sub.id
                )
                stats["relinked"] += 1
            if await refresh_published_price(session, existing, margin):
                stats["refreshed"] += 1
            else:
                stats["existing"] += 1
            continue
        await publish_product(session, ps.id, sub.id, margin_percent=margin)
        stats["new"] += 1
    if section == "games":
        games = await activate_all_games(session)
        stats["games_active"] = games.get("active", 0)
        stats["games_reactivated"] = games.get("reactivated", 0)
    return stats


async def setup_smm_section(
    session,
    provider_id: int,
    margin: Decimal,
    min_sell: Decimal = Decimal("0.05"),
) -> dict:
    """يجهز قسم الرشق كاملاً. يرجع إحصائيات."""
    from services.dynamic_service import DynamicService

    stats = {
        "new": 0, "refreshed": 0, "existing": 0, "relinked": 0,
        "skipped_dust": 0, "skipped": 0, "title": "📈 الرشق",
        "instagram_followers_available": 0,
        "instagram_followers_selected": 0,
        "instagram_followers_deactivated": 0,
    }
    _cat, app_subs = await ensure_smm_structure(session)
    result = await session.execute(
        select(ProviderService).where(
            ProviderService.api_provider_id == provider_id,
            ProviderService.status == ProviderServiceStatus.ACTIVE,
        )
    )
    smm_services = list(result.scalars().all())
    kind_ar = dict(SMM_KINDS)
    instagram_follower_service_ids: set[int] = set()

    for app_sub in app_subs:
        app_kind, app_ar = app_sub.kind_key, app_sub.name_ar
        cands = [s for s in smm_services if suggest_smm_service_app(s) == app_kind]
        by_kind: dict[str, list] = {}
        for s in cands:
            k = suggest_smm_kind(f"{s.category or ''} {s.name} {s.description or ''}")
            if k in ("followers", "likes", "views"):
                by_kind.setdefault(k, []).append(s)
        if not by_kind:
            stats["skipped"] += 1
            continue
        for kind, items in by_kind.items():
            # 6 لكل نوع: 3 اقتصادي (الأرخص الموثوق فوق الأرضية) + 3 مميز (Refill أولاً)
            # أرضية ضد الخدمات الوهمية الرخيصة ($/ألف) — المشاهدات رخيصة بطبعها
            floors = {"followers": Decimal("0.01"), "likes": Decimal("0.10"), "views": Decimal("0.005")}
            floor = floors.get(kind, Decimal("0.01"))
            eco, pro, available = _select_smm_tiers(items, floor, margin, min_sell)
            is_instagram_followers = app_kind == "instagram" and kind == "followers"
            if is_instagram_followers:
                stats["instagram_followers_available"] = available
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
            tier_numbers = {"اقتصادي 💰": 0, "مميز ⭐": 0}
            product_index = 0
            for tag, svc in picks:
                if is_instagram_followers:
                    tier_name = tag.split()[0]
                    tier_numbers[tag] += 1
                    product_index += 1
                    product_name = f"متابعو إنستغرام — {tier_name} {tier_numbers[tag]}"
                    product_description = _instagram_follower_description(svc, tier_name)
                    product_sort_order = product_index * 10
                else:
                    product_name = None
                    product_description = None
                    product_sort_order = 0
                existing = await existing_product_for_service(session, svc.id)
                if existing:
                    was_relinked = existing.sub_category_id != child.id
                    updates = {}
                    if was_relinked:
                        updates["sub_category_id"] = child.id
                    if is_instagram_followers:
                        updates.update(
                            name_ar=product_name[:128],
                            description=product_description,
                            status=ProductStatus.ACTIVE,
                            sort_order=product_sort_order,
                        )
                    if updates:
                        await DynamicService.update_product(session, existing.id, **updates)
                        if was_relinked:
                            stats["relinked"] += 1
                    if await refresh_published_price(session, existing, margin):
                        stats["refreshed"] += 1
                    else:
                        stats["existing"] += 1
                    if is_instagram_followers:
                        instagram_follower_service_ids.add(svc.id)
                        stats["instagram_followers_selected"] += 1
                    continue
                # الاسم: النوع + التطبيق + الفئة + لمحة من وصف المزود
                hint = (svc.name or "").strip()
                for drop in (app_sub.name_ar, kind_ar.get(kind, kind)):
                    hint = hint.replace(drop, "")
                hint = " ".join(hint.split())[:45]
                name = product_name or f"{kind_ar.get(kind, kind)} {app_ar} ({tag})"
                if hint and not is_instagram_followers:
                    name = f"{name} — {hint}"
                sell_1k = svc.rate_usd * (Decimal("100") + margin) / Decimal("100")
                if sell_1k >= Decimal("0.50"):
                    await publish_product(
                        session, svc.id, child.id, margin_percent=margin,
                        name_ar=name,
                        min_quantity=max(
                            int(svc.min_quantity or 1),
                            min(100, int(svc.max_quantity)),
                        ),
                        description=product_description,
                        sort_order=product_sort_order,
                    )
                else:
                    pack = None
                    for cand in SMM_PACK_OPTIONS:
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
                        description=product_description,
                        sort_order=product_sort_order,
                    )
                    await DynamicService.update_product(
                        session, prod.id, max_quantity=pack, requires_quantity=False,
                        price_usd=pack_price, cost_price_usd=pack_cost,
                    )
                stats["new"] += 1
                if is_instagram_followers:
                    instagram_follower_service_ids.add(svc.id)
                    stats["instagram_followers_selected"] += 1
    # أوقف الخدمات القديمة أو المنتمية فعلياً لمنصة أخرى التي كانت منشورة
    # خطأً تحت متابعي إنستغرام. المنتجات المختارة من الكتالوج الحالي فقط تبقى ظاهرة.
    instagram_app = next((sub for sub in app_subs if sub.kind_key == "instagram"), None)
    if instagram_app is not None:
        follower_result = await session.execute(select(SubCategory).where(
            SubCategory.category_id == instagram_app.category_id,
            SubCategory.parent_sub_category_id == instagram_app.id,
            SubCategory.kind_key == "instagram:followers",
        ))
        follower_sub = follower_result.scalar_one_or_none()
        if follower_sub is not None:
            products_result = await session.execute(select(Product).where(
                Product.sub_category_id == follower_sub.id,
                Product.api_provider_id == provider_id,
                Product.provider_service_ref_id.is_not(None),
                Product.status == ProductStatus.ACTIVE,
            ))
            for product in products_result.scalars().all():
                if product.provider_service_ref_id not in instagram_follower_service_ids:
                    product.status = ProductStatus.INACTIVE
                    stats["instagram_followers_deactivated"] += 1
            if stats["instagram_followers_deactivated"]:
                await session.commit()
    return stats


def format_stats(stats: dict) -> str:
    lines = [
        f"📋 <b>نتيجة تجهيز {stats.get('title', 'القسم')}</b>\n",
        f"🆕 منتجات جديدة: <b>{stats.get('new', 0)}</b>",
        f"♻️ أسعار حدثت: <b>{stats.get('refreshed', 0)}</b>",
        f"🗑 تخطي غبار: <b>{stats.get('skipped_dust', 0)}</b>",
    ]
    if stats.get("existing"):
        lines.append(f"📦 منتجات موجودة دون تغيير: <b>{stats['existing']}</b>")
    if stats.get("relinked"):
        lines.append(f"🔗 منتجات أُعيد ربطها بفرعها الصحيح: <b>{stats['relinked']}</b>")
    if "instagram_followers_selected" in stats:
        selected = int(stats.get("instagram_followers_selected", 0) or 0)
        available = int(stats.get("instagram_followers_available", 0) or 0)
        lines.append(
            f"📸 متابعو إنستغرام: <b>{selected}/6</b> منتجاً من "
            f"<b>{available}</b> خدمة مؤهلة موجودة بكتالوج المزود"
        )
        if selected < 6:
            lines.append(
                "⚠️ المزود لا يوفّر حالياً ست خدمات متابعين مؤهلة؛ "
                "لم أضف خدمات بديلة من فيسبوك أو تيليجرام."
            )
        if stats.get("instagram_followers_deactivated"):
            lines.append(
                f"🧹 أُخفيت خدمات قديمة من هذا القسم: "
                f"<b>{stats['instagram_followers_deactivated']}</b>"
            )
    if stats.get("games_active") is not None:
        lines.append(
            f"🎮 فروع الألعاب المفعّلة: <b>{stats['games_active']}</b> "
            f"(أُعيد تفعيل {stats.get('games_reactivated', 0)} فرعاً كانت مخفية)"
        )
    skipped = int(stats.get("skipped", 0) or 0)
    if skipped:
        lines.append(f"⏭ متخطاة لأسباب أخرى: <b>{skipped}</b>")
        details = []
        if stats.get("no_map"):
            details.append(f"بلا ربط شجرة: {stats['no_map']}")
        if stats.get("wrong_type"):
            details.append(f"خارج القسم: {stats['wrong_type']}")
        if stats.get("filtered"):
            details.append(f"مصفاة (غير سيريتل/MTN): {stats['filtered']}")
        if details:
            lines.append(f"<i>({ '، '.join(details) })</i>")
        if int(stats.get("no_map", 0) or 0) > 10:
            lines.append(
                "\n⚠️ تعذر ربط خدمات كثيرة بفروع القسم. راجع تصنيفاتها في كتالوج المزود."
            )
    return "\n".join(lines)
