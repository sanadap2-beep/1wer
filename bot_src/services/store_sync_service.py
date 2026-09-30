"""
مزامنة كتالوج المتجر من المزودين (HyperStore + SMM).

- HyperStore: يمشي شجرة الأقسام (/categories + /content) ويعكسها
  Category/SubCategory، ويسحب المنتجات كـ ProviderService مع
  حفظ الحقول (fields) وخيارات الفئات (dropdown) ونوع الهدف
  داخل raw_data — كلشي ديناميكي بدون كود لكل منتج.
- SMM (smm_v2): يسحب قائمة الخدمات كـ ProviderService.

خريطة الشجرة تُحفظ في SettingsService (JSON) — لا حاجة لهجرة قاعدة بيانات.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from database.models import (
    ApiProvider,
    ApiProviderType,
    Category,
    CategoryType,
    Product,
    ProviderService,
    ProviderServiceStatus,
    ProviderPriceType,
    SubCategory,
)

logger = logging.getLogger(__name__)


# ── أقسام المتجر الأربعة فقط ──

# الأنواع المعروضة داخل المتجر (4 أقسام فقط)
STORE_VISIBLE_TYPES = (CategoryType.GAMES, CategoryType.APPS, CategoryType.SMM, CategoryType.BALANCES)


async def hide_unwanted_store_categories(session) -> int:
    """يعطّل كل أقسام المتجر خارج الأقسام الأربعة (الأرقام تبقى).

    الإخفاء لا الحذف — يمكن إعادة التفعيل من اللوحة.
    """
    result = await session.execute(select(Category))
    n = 0
    for cat in result.scalars().all():
        if cat.type in (CategoryType.NUMBERS,) + STORE_VISIBLE_TYPES:
            continue
        if cat.is_active:
            cat.is_active = False
            n += 1
    if n:
        await session.commit()
    return n

_HYPER_TYPE_KEYWORDS: list[tuple[str, CategoryType, str]] = [
    ("العاب", CategoryType.GAMES, "🎮"),
    ("games", CategoryType.GAMES, "🎮"),
    ("تطبيقات", CategoryType.APPS, "📱"),
    ("apps", CategoryType.APPS, "📱"),
    ("برامج", CategoryType.APPS, "📱"),
    ("ارصدة", CategoryType.BALANCES, "💳"),
    ("أرصدة", CategoryType.BALANCES, "💳"),
    ("رصيد", CategoryType.BALANCES, "💳"),
    ("شام كاش", CategoryType.BALANCES, "💳"),
    ("بطاقات", CategoryType.CARDS, "💳"),
    ("اشتراك", CategoryType.SUBSCRIPTIONS, "🔐"),
    ("توثيق", CategoryType.VERIFICATION, "✅"),
    ("اكواد", CategoryType.CODES, "🎟"),
    ("أكواد", CategoryType.CODES, "🎟"),
]


def hyper_category_type(name: str) -> tuple[CategoryType, str]:
    """(النوع، الإيموجي) لقسم HyperStore حسب اسمه العربي."""
    lowered = (name or "").strip().lower()
    for keyword, ctype, emoji in _HYPER_TYPE_KEYWORDS:
        if keyword in lowered:
            return ctype, emoji
    return CategoryType.CUSTOM, "🛍"


# ── تعريب عناوين الفروع الإنجليزية ──

AR_TITLES: dict[str, str] = {
    "pubg mobile": "ببجي موبايل",
    "pubg global auto": "ببجي عالمي تلقائي",
    "pubg memberships": "عضويات ببجي",
    "pubg new state": "ببجي نيو ستيت",
    "pubg syria": "ببجي سوريا",
    "free fire": "فري فاير",
    "mobile legend": "موبايل ليجند",
    "jawaker": "جواكر",
    "8ball pool": "بلياردو 8",
    "delta force": "دلتا فورس",
    "blood strike": "بلود سترايك",
    "efootball": "إي فوتبول",
    "brawl stars": "براول ستارز",
    "clash of clans": "كلاش أوف كلانس",
    "كلاش اوف كلانس": "كلاش أوف كلانس",
    "arena breakout": "أرينا بريك آوت",
    "age of empires mobile": "عصر الإمبراطوريات",
    "mixu": "ميكسو",
    "momo live": "مومو لايف",
    "yalla live": "يلا لايف",
    "syriatel": "سيريتل",
    "alfa": "ألفا",
    "touch": "تاتش",
    "ludo club": "لودو كلوب",
    "لودو clud": "لودو كلوب",
    "yalla ludo": "يلا لودو",
    "honor of king": "أونر أوف كينغ",
    "genshin impact": "قنشن إمباكت",
    "genshen impact": "قنشن إمباكت",
    "honkai : star rail": "هونكاي ستار ريل",
    "whiteout survival": "وايت أوت سرفايفل",
    "stumble guys": "ستامبل جايز",
    "super sus": "سوبر ساس",
    "farlight84": "فارلايت 84",
    "brawl stars": "براول ستارز",
    "mobile legend": "موبايل ليجند",
    "8ball pool": "بلياردو",
    "free fire": "فري فاير",
    "pubg mobile": "ببجي موبايل",
    "itunes": "آيتونز",
    "google play": "جوجل بلاي",
    "play station": "بلايستيشن",
    "steam": "ستيم",
    "x box": "إكس بوكس",
    "amazon": "أمازون",
    "razer gold": "ريزر جولد",
}


def _has_arabic(text: str) -> bool:
    return any("؀" <= c <= "ۿ" for c in (text or ""))


def localize_title(name: str) -> str:
    """اسم عربي للعرض: من القاموس، أو الأصل إن كان عربياً، أو الأصل كما هو."""
    name = (name or "").strip()
    if not name:
        return "قسم"
    if _has_arabic(name):
        return name[:64]
    return AR_TITLES.get(name.lower(), name[:64])


# ── الأقسام الأربعة الثابتة + أشهر 20 لعبة بسوريا ──

SECTION_ROOT_NAMES: dict[CategoryType, tuple[str, str]] = {
    CategoryType.GAMES: ("شحن الألعاب", "🎮"),
    CategoryType.APPS: ("شحن البرامج", "📱"),
    CategoryType.BALANCES: ("الأرصدة", "💳"),
    CategoryType.SMM: ("الرشق", "📈"),
}

# كلمات مطابقة لأشهر 20 لعبة (بالترتيب) — الباقي يُخفى (قابل للتفعيل يدوياً)
TOP_GAMES_ORDER: list[str] = [
    "pubg mobile", "free fire", "jawaker", "efootball", "mobile legend",
    "brawl stars", "clash", "8ball", "yalla ludo", "ludo",
    "delta force", "blood strike", "honor of king", "genshin", "genshen",
    "honkai", "whiteout", "stumble", "super sus", "farlight", "arena breakout",
]

ORIGINAL_ROOT_NAMES = {
    "الألعاب", "الالعاب", "التطبيقات", "قسم الأرصدة", "قسم الارصدة",
    "رشق سوشيال ميديا", "رشق",
}


async def normalize_section_roots(session) -> int:
    """يوحد أسماء الأقسام الأربعة (إنشاءً وتحديثاً للأسماء الأصلية فقط)."""
    from services.dynamic_service import DynamicService

    changed = 0
    result = await session.execute(select(Category))
    for cat in result.scalars().all():
        wanted = SECTION_ROOT_NAMES.get(cat.type)
        if not wanted:
            continue
        if cat.name_ar != wanted[0] and (cat.name_ar in ORIGINAL_ROOT_NAMES or not _has_arabic(cat.name_ar or "")):
            cat.name_ar = wanted[0]
            cat.emoji = wanted[1]
            changed += 1
    if changed:
        await session.commit()
    # قسم الرشق إن لم يوجد
    smm = await session.execute(select(Category).where(Category.type == CategoryType.SMM))
    if smm.scalar_one_or_none() is None:
        await DynamicService.create_category(
            session, name_ar="الرشق", emoji="📈",
            category_type=CategoryType.SMM, sort_order=1,
        )
        changed += 1
    return changed


async def prioritize_top_games(session) -> dict:
    """يُبقي أشهر 20 لعبة مرتبة ويخفي الباقي (عكسي من اللوحة)."""
    result = await session.execute(select(Category).where(Category.type == CategoryType.GAMES))
    cats = list(result.scalars().all())
    stats = {"kept": 0, "hidden": 0}
    for cat in cats:
        subs_result = await session.execute(select(SubCategory).where(
            SubCategory.category_id == cat.id,
            SubCategory.parent_sub_category_id.is_(None)))
        subs = list(subs_result.scalars().all())
        ranked: list[tuple[int, SubCategory]] = []
        used: set[int] = set()
        for idx, keyword in enumerate(TOP_GAMES_ORDER):
            for sub in subs:
                if sub.id in used:
                    continue
                if keyword in (sub.name_ar or "").lower():
                    ranked.append((idx, sub))
                    used.add(sub.id)
                    break
        for order, (idx, sub) in enumerate(sorted(ranked)):
            sub.sort_order = (order + 1) * 10
            if not sub.is_active:
                sub.is_active = True
            stats["kept"] += 1
        for sub in subs:
            if sub.id not in used and sub.is_active:
                sub.is_active = False
                stats["hidden"] += 1
        await session.commit()
    return stats


async def flush_store(session, delete_services: bool = False) -> dict:
    """🧹 تفريغ المتجر: حذف الأقسام/الفروع/المنتجات (الأرقام تُمسّ أبداً).

    - يحذف كل Category ما عدا NUMBERS (مع cascade للفروع والمنتجات).
    - يمسح خرائط الشجرة store_tree_*.
    - delete_services=True يحذف أيضاً خدمات المزود المسحوبة (سحب جديد بعدها).
    """
    from services.settings_service import SettingsService

    stats = {"cats": 0, "products": 0, "services": 0}
    result = await session.execute(select(Category))
    for cat in list(result.scalars().all()):
        if cat.type == CategoryType.NUMBERS:
            continue
        prod_result = await session.execute(
            select(Product).join(SubCategory, Product.sub_category_id == SubCategory.id).where(
                SubCategory.category_id == cat.id)
        )
        stats["products"] += len(list(prod_result.scalars().all()))
        await session.delete(cat)
        stats["cats"] += 1
    await session.commit()
    # مسح خرائط الشجرة
    all_settings = await SettingsService.get_all()
    for key in list(all_settings.keys()):
        if key.startswith("store_tree_"):
            await SettingsService.set(session, key, "{}")
    if delete_services:
        svc_result = await session.execute(select(ProviderService))
        for row in list(svc_result.scalars().all()):
            await session.delete(row)
            stats["services"] += 1
        await session.commit()
    return stats

SMM_APPS: list[tuple[str, str, str, list[str]]] = [
    # (الاسم العربي، الإيموجي، kind_key، كلمات المطابقة)
    ("انستقرام", "📸", "instagram", ["instagram", "insta", "ig ", " ig", "انستا"]),
    ("تيك توك", "🎵", "tiktok", ["tiktok", "tik tok", "تيك توك"]),
    ("يوتيوب", "▶️", "youtube", ["youtube", "youtu", "يوتيوب"]),
    ("تيليجرام", "✈️", "telegram", ["telegram", "تيليجرام", "تليجرام"]),
    ("فيسبوك", "👥", "facebook", ["facebook", "fb ", " فيس"]),
    ("واتساب", "💬", "whatsapp", ["whatsapp", "wts", "واتساب", "واتس اب"]),
    ("سناب شات", "👻", "snapchat", ["snapchat", "snap", "سناب"]),
    ("تويتر", "🐦", "twitter", ["twitter", " x ", "تويتر", "اكس"]),
]

SMM_KINDS: list[tuple[str, str]] = [
    ("followers", "متابعين"),
    ("likes", "لايكات"),
    ("views", "مشاهدات"),
    ("comments", "تعليقات"),
    ("shares", "مشاركات"),
    ("members", "أعضاء"),
    ("reactions", "تفاعلات"),
]


def suggest_smm_app(text: str) -> str | None:
    """kind_key التطبيق المقترح لخدمة SMM حسب اسمها/تصنيفها."""
    lowered = (text or "").lower()
    for _name_ar, _emoji, kind, keywords in SMM_APPS:
        if any(k in lowered for k in keywords):
            return kind
    return None


def suggest_smm_kind(text: str) -> str | None:
    """نوع الخدمة المقترح (متابعين/لايكات/...) حسب الاسم."""
    lowered = (text or "").lower()
    if "follower" in lowered or "member" in lowered or "subscriber" in lowered or "متابع" in lowered:
        return "followers"
    if "like" in lowered or "reaction" in lowered or "لايك" in lowered:
        return "likes"
    if "view" in lowered or "impression" in lowered or "reach" in lowered or "مشاهد" in lowered:
        return "views"
    if "comment" in lowered or "تعليق" in lowered:
        return "comments"
    if "share" in lowered or "repost" in lowered or "مشارك" in lowered:
        return "shares"
    return None


# ── تقارير ──

@dataclass
class StoreSyncReport:
    provider_name: str = ""
    categories_added: int = 0
    categories_updated: int = 0
    subs_added: int = 0
    subs_updated: int = 0
    services_added: int = 0
    services_updated: int = 0
    total_services: int = 0
    failed: int = 0
    error: str = ""

    def summary(self) -> str:
        if self.error:
            return f"❌ فشل سحب {self.provider_name}: {self.error}"
        return (
            f"✅ <b>اكتمل سحب {self.provider_name}</b>\n\n"
            f"📁 أقسام جديدة: <b>{self.categories_added}</b> (محدثة: {self.categories_updated})\n"
            f"📂 فروع جديدة: <b>{self.subs_added}</b> (محدثة: {self.subs_updated})\n"
            f"🛠 خدمات جديدة: <b>{self.services_added}</b> (محدثة: {self.services_updated})\n"
            f"📊 الإجمالي عند المزود: <b>{self.total_services}</b>"
        )


# ── أدوات مساعدة ──

def _tree_map_key(provider_id: int) -> str:
    return f"store_tree_{provider_id}"


async def _load_tree_map(session, provider_id: int) -> dict:
    from services.settings_service import SettingsService

    raw = await SettingsService.get(_tree_map_key(provider_id), "{}")
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


async def _save_tree_map(session, provider_id: int, mapping: dict) -> None:
    from services.settings_service import SettingsService

    await SettingsService.set(session, _tree_map_key(provider_id), json.dumps(mapping, ensure_ascii=False))


def _protocol_for(provider: ApiProvider):
    from protocols.factory import ProtocolFactory

    return ProtocolFactory.create_from_provider(provider)


def _service_extra(provider_type: str, svc) -> dict:
    """بيانات إضافية تُحفظ في raw_data (فئات dropdown + نوع الهدف)."""
    extra: dict = {
        "category": svc.category,
        "service_type": svc.service_type,
        "requires_link": svc.requires_link,
        "requires_quantity": svc.requires_quantity,
        "requires_player_id": svc.requires_player_id,
    }
    raw = svc.raw or {}
    if isinstance(raw, dict):
        if raw.get("_target_kind"):
            extra["target_kind"] = raw["_target_kind"]
        if raw.get("_quantity_options"):
            extra["quantity_options"] = raw["_quantity_options"]
        # حقول المزود الخام (للعرض والتشخيص)
        fields = raw.get("fields") or raw.get("input_type")
        if isinstance(fields, list):
            slim = []
            for f in fields:
                if isinstance(f, dict):
                    slim.append({
                        "key": f.get("key"),
                        "label": f.get("label") or f.get("provider_key"),
                        "type": f.get("type"),
                        "advanced": f.get("advanced") if isinstance(f.get("advanced"), dict) else None,
                    })
            extra["fields"] = slim
        if raw.get("required_fields"):
            extra["required_fields"] = raw["required_fields"]
    return extra


async def upsert_provider_service(
    session,
    provider: ApiProvider,
    svc,
    price_type: ProviderPriceType,
    report: StoreSyncReport,
) -> ProviderService:
    result = await session.execute(
        select(ProviderService).where(
            ProviderService.api_provider_id == provider.id,
            ProviderService.external_service_id == str(svc.external_id),
        )
    )
    existing = result.scalar_one_or_none()
    rate = Decimal(str(svc.rate or 0))
    rate_usd = (rate * (provider.rate_to_usd or Decimal("1")))
    raw_json = json.dumps(_service_extra(provider.type.value if hasattr(provider.type, "value") else str(provider.type), svc), ensure_ascii=False)
    if existing:
        existing.name = svc.name[:500]
        existing.category = (svc.category or "")[:255] or existing.category
        existing.service_type = (svc.service_type or "")[:64] or existing.service_type
        existing.rate = rate
        existing.rate_usd = rate_usd
        existing.min_quantity = int(svc.min_quantity or 1)
        existing.max_quantity = int(svc.max_quantity or 1000000)
        existing.requires_link = bool(svc.requires_link)
        existing.requires_quantity = bool(svc.requires_quantity)
        existing.requires_player_id = bool(svc.requires_player_id)
        existing.supports_refill = bool(svc.supports_refill)
        existing.supports_cancel = bool(svc.supports_cancel)
        existing.raw_data = raw_json
        report.services_updated += 1
        await session.commit()
        return existing
    row = ProviderService(
        api_provider_id=provider.id,
        external_service_id=str(svc.external_id),
        name=svc.name[:500],
        category=(svc.category or "")[:255],
        service_type=(svc.service_type or "")[:64],
        rate=rate,
        rate_usd=rate_usd,
        price_type=price_type,
        min_quantity=int(svc.min_quantity or 1),
        max_quantity=int(svc.max_quantity or 1000000),
        requires_link=bool(svc.requires_link),
        requires_quantity=bool(svc.requires_quantity),
        requires_player_id=bool(svc.requires_player_id),
        supports_refill=bool(svc.supports_refill),
        supports_cancel=bool(svc.supports_cancel),
        status=ProviderServiceStatus.ACTIVE,
        raw_data=raw_json,
    )
    session.add(row)
    report.services_added += 1
    await session.commit()
    return row


# ── مزامنة HyperStore (شجرة + منتجات) ──

async def sync_hyperstore(session, provider: ApiProvider) -> StoreSyncReport:
    report = StoreSyncReport(provider_name=provider.name)
    protocol = _protocol_for(provider)
    try:
        # 1) الأقسام الجذرية
        try:
            roots = await protocol.get_categories()
        except Exception:
            roots = []
        if not roots:
            # احتياطي: /content/0
            data = await protocol._request("GET", "/content/0")
            payload = data.get("data") if isinstance(data.get("data"), dict) else data
            cats = payload.get("categories", []) if isinstance(payload, dict) else []
            roots = cats if isinstance(cats, list) else []
        tree_map = await _load_tree_map(session, provider.id)

        # 2) BFS على الشجرة
        queue: list[tuple[dict, int | None, int | None]] = [
            (c, None, None) for c in roots if isinstance(c, dict)
        ]
        seen_cats: set[str] = set()
        order = 0
        while queue:
            node, local_parent_cat, local_parent_sub = queue.pop(0)
            ext_id = str(node.get("id", ""))
            name = str(node.get("name", "") or f"قسم {ext_id}").strip()
            if not ext_id or ext_id in seen_cats:
                continue
            seen_cats.add(ext_id)
            try:
                content = await protocol._request("GET", f"/content/{ext_id}")
            except Exception:
                logger.exception("فشل جلب محتوى قسم %s", ext_id)
                report.failed += 1
                continue
            payload = content.get("data") if isinstance(content.get("data"), dict) else content
            if not isinstance(payload, dict):
                payload = content if isinstance(content, dict) else {}
            children = payload.get("categories", []) or []
            products = payload.get("products", []) or []

            if local_parent_cat is None and local_parent_sub is None:
                # قسم جذري → Category (الأقسام الأربعة فقط — الباقي يُتجاهل)
                ctype, emoji = hyper_category_type(name)
                if ctype not in (CategoryType.GAMES, CategoryType.APPS, CategoryType.BALANCES):
                    continue
                mapped = tree_map.get(ext_id)
                cat = None
                if mapped and mapped.get("kind") == "cat":
                    cat = await session.get(Category, int(mapped["id"]))
                if cat is None:
                    # بحث بالاسم لتفادي التكرار
                    existing = await session.execute(
                        select(Category).where(Category.name_ar == name[:64])
                    )
                    cat = existing.scalar_one_or_none()
                if cat is None:
                    from services.dynamic_service import DynamicService

                    fixed = SECTION_ROOT_NAMES.get(ctype)
                    cat = await DynamicService.create_category(
                        session, name_ar=fixed[0] if fixed else name[:64],
                        emoji=fixed[1] if fixed else emoji,
                        category_type=ctype, sort_order=order,
                    )
                    report.categories_added += 1
                else:
                    # لا نمس تعديل الأدمن — نطبع الاسم الثابت للأسماء الأصلية فقط
                    fixed = SECTION_ROOT_NAMES.get(ctype)
                    if fixed and cat.name_ar in ORIGINAL_ROOT_NAMES:
                        cat.name_ar, cat.emoji = fixed
                        await session.commit()
                    report.categories_updated += 1
                tree_map[ext_id] = {"kind": "cat", "id": cat.id}
                await _save_tree_map(session, provider.id, tree_map)
                for child in children:
                    if isinstance(child, dict):
                        queue.append((child, cat.id, None))
                # منتجات على الجذر مباشرة → فرع "عام"
                if products:
                    general = await _ensure_general_sub(session, cat.id)
                    for p in products:
                        await _store_hyper_product(session, provider, protocol, p, general.id, report, hyper_cat_ext=ext_id)
            else:
                # قسم فرعي → SubCategory
                mapped = tree_map.get(ext_id)
                sub = None
                if mapped and mapped.get("kind") == "sub":
                    sub = await session.get(SubCategory, int(mapped["id"]))
                if sub is None:
                    from services.dynamic_service import DynamicService

                    parent_cat = local_parent_cat
                    if parent_cat is None and local_parent_sub is not None:
                        parent_row = await session.get(SubCategory, local_parent_sub)
                        parent_cat = parent_row.category_id if parent_row else None
                    # الاسم معرّب عند الإنشاء
                    sub = await DynamicService.create_sub_category(
                        session, category_id=int(parent_cat or 0),
                        name_ar=localize_title(name), emoji="📁",
                        parent_sub_category_id=local_parent_sub,
                        sort_order=order,
                    )
                    report.subs_added += 1
                else:
                    # لا نمس تعديل الأدمن العربي — نعرّب الأجنبي فقط
                    if not _has_arabic(sub.name_ar or ""):
                        sub.name_ar = localize_title(name)
                        await session.commit()
                    report.subs_updated += 1
                tree_map[ext_id] = {"kind": "sub", "id": sub.id}
                await _save_tree_map(session, provider.id, tree_map)
                for child in children:
                    if isinstance(child, dict):
                        queue.append((child, None, sub.id))
                for p in products:
                    await _store_hyper_product(session, provider, protocol, p, sub.id, report, hyper_cat_ext=ext_id)
            order += 10

        provider.last_sync_at = datetime.utcnow()
        provider.last_error = None
        await session.commit()
        try:
            hidden = await hide_unwanted_store_categories(session)
            if hidden:
                logger.info("أُخفي %s قسماً خارج الأقسام الأربعة.", hidden)
        except Exception:
            pass
    except Exception as exc:
        logger.exception("فشل مزامنة HyperStore")
        report.error = str(exc)[:200]
        provider.last_error = report.error
        await session.commit()
    # إجمالي الخدمات
    total = await session.execute(
        select(ProviderService).where(ProviderService.api_provider_id == provider.id)
    )
    report.total_services = len(list(total.scalars().all()))
    provider.total_services = report.total_services
    await session.commit()
    return report


async def _ensure_general_sub(session, category_id: int) -> SubCategory:
    result = await session.execute(
        select(SubCategory).where(
            SubCategory.category_id == category_id,
            SubCategory.parent_sub_category_id.is_(None),
            SubCategory.name_ar == "عام",
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    from services.dynamic_service import DynamicService

    return await DynamicService.create_sub_category(
        session, category_id=category_id, name_ar="عام", emoji="📁", sort_order=999,
    )


async def _store_hyper_product(
    session, provider, protocol, item: dict, sub_id: int, report: StoreSyncReport,
    hyper_cat_ext: str | None = None,
) -> None:
    try:
        svc = protocol._parse_service(item)
    except Exception:
        report.failed += 1
        return
    if svc is None:
        return
    row = await upsert_provider_service(session, provider, svc, ProviderPriceType.PER_ITEM, report)
    if hyper_cat_ext:
        try:
            extra = json.loads(row.raw_data or "{}")
            if extra.get("hyper_cat") != hyper_cat_ext:
                extra["hyper_cat"] = hyper_cat_ext
                row.raw_data = json.dumps(extra, ensure_ascii=False)
                await session.commit()
        except Exception:
            pass


# ── مزامنة SMM ──

async def sync_smm(session, provider: ApiProvider) -> StoreSyncReport:
    report = StoreSyncReport(provider_name=provider.name)
    protocol = _protocol_for(provider)
    try:
        services = await protocol.get_services()
        for svc in services:
            try:
                await upsert_provider_service(session, provider, svc, ProviderPriceType.PER_1000, report)
            except Exception:
                logger.exception("فشل حفظ خدمة SMM %s", svc.external_id)
                report.failed += 1
        provider.last_sync_at = datetime.utcnow()
        provider.last_error = None
        await session.commit()
    except Exception as exc:
        logger.exception("فشل مزامنة SMM")
        report.error = str(exc)[:200]
        provider.last_error = report.error
        await session.commit()
    total = await session.execute(
        select(ProviderService).where(ProviderService.api_provider_id == provider.id)
    )
    report.total_services = len(list(total.scalars().all()))
    provider.total_services = report.total_services
    await session.commit()
    return report


async def sync_provider(session, provider: ApiProvider) -> StoreSyncReport:
    """يختار المزامنة المناسبة حسب بروتوكول المزود + يحدث الرصيد."""
    from protocols.hyper_store import is_hyper_store_provider

    if is_hyper_store_provider(provider):
        report = await sync_hyperstore(session, provider)
    else:
        report = await sync_smm(session, provider)
    try:
        protocol = _protocol_for(provider)
        balance = await protocol.get_balance()
        provider.balance = balance.amount
        provider.currency = balance.currency
        await session.commit()
    except Exception:
        pass
    return report


# ── تجهيز هيكل الرشق (8 تطبيقات) ──

async def ensure_smm_structure(session) -> tuple[Category, list[SubCategory]]:
    """ينشئ قسم الرشق + 8 تطبيقات إن لم توجد. يرجع (القسم، الفروع)."""
    from services.dynamic_service import DynamicService

    result = await session.execute(
        select(Category).where(Category.type == CategoryType.SMM)
    )
    cat = result.scalar_one_or_none()
    if cat is None:
        cat = await DynamicService.create_category(
            session, name_ar="الرشق", emoji="📈",
            category_type=CategoryType.SMM, sort_order=1,
        )
    elif cat.name_ar != "الرشق":
        cat.name_ar = "الرشق"
        cat.emoji = "📈"
        await session.commit()
    subs: list[SubCategory] = []
    for i, (name_ar, emoji, kind, _keywords) in enumerate(SMM_APPS):
        existing = await session.execute(
            select(SubCategory).where(
                SubCategory.category_id == cat.id,
                SubCategory.kind_key == kind,
            )
        )
        sub = existing.scalar_one_or_none()
        if sub is None:
            sub = await DynamicService.create_sub_category(
                session, category_id=cat.id, name_ar=name_ar, emoji=emoji,
                kind_key=kind, sort_order=(i + 1) * 10,
            )
        subs.append(sub)
    return cat, subs


# ── النشر: من خدمة مزود إلى منتج ──

async def existing_product_for_service(session, provider_service_id: int) -> Product | None:
    """المنتج المنشور مسبقاً لهذه الخدمة (لمنع التكرار عند إعادة التشغيل)."""
    result = await session.execute(
        select(Product).where(Product.provider_service_ref_id == provider_service_id)
    )
    return result.scalar_one_or_none()


async def refresh_published_price(
    session,
    product: Product,
    default_margin: Decimal,
) -> bool:
    """يحدث سعر منتج منشور من تكلفة مزوده الحالية (يتخطى اليدوي).

    يرجع True إذا حُدّث السعر.
    """
    from services.dynamic_service import DynamicService

    ps = None
    if product.provider_service_ref_id:
        ps = await session.get(ProviderService, product.provider_service_ref_id)
    if ps is None:
        return False
    if product.margin_manual and product.profit_margin_percent is not None:
        margin = Decimal(str(product.profit_margin_percent))
    else:
        margin = default_margin
    cost = ps.rate_usd
    sell = (cost * (Decimal("100") + margin) / Decimal("100")).quantize(Decimal("0.0001"))
    if sell != product.price_usd or cost != product.cost_price_usd:
        await DynamicService.update_product(
            session, product.id, price_usd=sell, cost_price_usd=cost
        )
        return True
    return False

async def publish_product(
    session,
    provider_service_id: int,
    sub_category_id: int,
    margin_percent: Decimal | None = None,
    name_ar: str | None = None,
    min_quantity: int | None = None,
) -> Product:
    """ينشر خدمة مزود كمنتج قابل للشراء في فرع معين."""
    from services.dynamic_service import DynamicService

    ps = await session.get(ProviderService, provider_service_id)
    if ps is None:
        raise ValueError("خدمة المزود غير موجودة")
    provider = await session.get(ApiProvider, ps.api_provider_id)
    extra = {}
    try:
        extra = json.loads(ps.raw_data or "{}")
    except Exception:
        extra = {}
    target_kind = extra.get("target_kind", "link")
    requires_link = target_kind == "link"
    requires_player = target_kind == "player" or bool(ps.requires_player_id)
    # الهاتف (سيريتل/MTN) يُعامل كهدف نصي خاص بدون رابط
    requires_quantity = bool(ps.requires_quantity)
    cost = ps.rate_usd
    margin = margin_percent if margin_percent is not None else Decimal("50")
    sell = (cost * (Decimal("100") + margin) / Decimal("100"))
    # للفئات الثابتة (dropdown): السعر يُحسب عند اختيار الفئة — نخزن سعر الوحدة
    # الوصف: من المزود، أو مولّد من بيانات الخدمة (مهم لخدمات SMM بلا وصف)
    desc = (ps.description or "").strip()
    if not desc:
        bits = [ps.name]
        if ps.category:
            bits.append(f"التصنيف: {ps.category}")
        bits.append(f"الحدود: {ps.min_quantity}-{ps.max_quantity}")
        if ps.supports_refill:
            bits.append("♻️ يدعم إعادة التعبئة")
        desc = " | ".join(bits)
    product = await DynamicService.create_product(
        session,
        sub_category_id=sub_category_id,
        name_ar=(name_ar or ps.name_ar or ps.name)[:128],
        price_usd=sell,
        cost_price_usd=cost,
        api_provider_id=ps.api_provider_id,
        provider_service_id=ps.external_service_id,
        provider_service_ref_id=ps.id,
        description=desc[:500],
        min_quantity=min_quantity if min_quantity is not None else 1,
        max_quantity=1 if extra.get("quantity_options") else max(1, ps.max_quantity),
        requires_player_id=requires_player,
        requires_link=requires_link,
        requires_quantity=requires_quantity and not extra.get("quantity_options"),
    )
    if margin_percent is not None:
        product.profit_margin_percent = margin_percent
        await session.commit()
    return product
