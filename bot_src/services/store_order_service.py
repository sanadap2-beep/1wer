"""
طلبات المتجر: التحقق + التسعير + التنفيذ + المتابعة والاسترجاع.

- أنواع الهدف: phone (سيريتل/MTN — 09xxxxxxxx) / player / link / none.
- التسعير: تكلفة المزود × (1 + الهامش الهرمي: منتج ← فرع ← قسم ← عام).
- الفئات الثابتة (dropdown): تُمرر قيمة الفئة ككمية للمزود، وتُحفظ
  كنص في result_data (عمود quantity عددي — نخزن 1).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from database.models import (
    ApiProvider,
    Product,
    ProviderPriceType,
    ProviderService,
    SubCategory,
    TransactionType,
    UnifiedOrder,
    UnifiedOrderStatus,
)
from services.store_validators import normalize_phone, validate_target

logger = logging.getLogger(__name__)


def target_kind_of(product: Product, provider_service: ProviderService | None) -> str:
    """نوع الهدف للمنتج: phone | player | link | none."""
    if product.requires_player_id:
        return "player"
    if product.requires_link:
        return "link"
    if provider_service and provider_service.raw_data:
        try:
            extra = json.loads(provider_service.raw_data)
        except Exception:
            extra = {}
        kind = extra.get("target_kind")
        if kind in ("phone", "player", "link", "none"):
            return kind
    return "none"


def quantity_options_of(provider_service: ProviderService | None) -> list[str]:
    """خيارات الفئات الثابتة أو []."""
    if not provider_service or not provider_service.raw_data:
        return []
    try:
        return json.loads(provider_service.raw_data).get("quantity_options") or []
    except Exception:
        return []


async def resolve_margin(session, product: Product) -> Decimal:
    """الهامش الهرمي: منتج ← فرع ← قسم ← عام (50 افتراضي)."""
    from services.settings_service import SettingsService

    if product.profit_margin_percent is not None:
        return Decimal(str(product.profit_margin_percent))
    sub = await session.get(SubCategory, product.sub_category_id)
    if sub is not None:
        if sub.profit_margin_percent is not None:
            return Decimal(str(sub.profit_margin_percent))
        from database.models import Category

        cat = await session.get(Category, sub.category_id)
        if cat is not None and cat.profit_margin_percent is not None:
            return Decimal(str(cat.profit_margin_percent))
    return await SettingsService.get_decimal("default_profit_margin_percent", Decimal("50"))


def compute_prices(cost_usd: Decimal, margin: Decimal) -> tuple[Decimal, Decimal]:
    sell = (cost_usd * (Decimal("100") + margin) / Decimal("100")).quantize(Decimal("0.0001"))
    return cost_usd, sell


async def price_for(session, product: Product, qty: str, user=None) -> tuple[Decimal, Decimal, Decimal]:
    """(التكلفة، البيع، الهامش) لمنتج وكمية معينة — مع خصم التاجر إن وُجد مستخدم."""
    ps = None
    if product.provider_service_ref_id:
        ps = await session.get(ProviderService, product.provider_service_ref_id)
    margin = await resolve_margin(session, product)
    if ps is None:
        # منتج يدوي: سعره ثابت
        base_cost, base_sell = product.cost_price_usd, product.price_usd
        if user is not None:
            from services.trader_service import apply_discount, discount_for_user

            uid = user.id if hasattr(user, "id") else int(user)
            base_sell = apply_discount(base_sell, await discount_for_user(session, uid))
        return base_cost, base_sell, margin
    try:
        qty_dec = Decimal(str(qty))
    except (InvalidOperation, ValueError):
        qty_dec = Decimal("1")
    if ps.price_type == ProviderPriceType.PER_1000:
        cost = (ps.rate_usd * qty_dec / Decimal("1000"))
    else:
        cost = ps.rate_usd * qty_dec
    _cost, sell = compute_prices(cost, margin)
    # عرض مؤقت؟ السعر الثابت للعرض يتجاوز الهامش (وبدون خصم تاجر فوقه)
    try:
        from services.offer_service import active_offer_for_product

        offer = await active_offer_for_product(session, product)
        if offer is not None:
            return cost, offer.price_usd, margin
    except Exception:
        pass
    # خصم التاجر على سعر البيع
    if user is not None:
        try:
            from services.trader_service import apply_discount, discount_for_user

            uid = user.id if hasattr(user, "id") else int(user)
            sell = apply_discount(sell, await discount_for_user(session, uid))
        except Exception:
            pass
    return cost, sell, margin


async def place_store_order(
    session, bot, db_user, product_id: int, target: str, qty: str,
    coupon_kind: str | None = None, coupon_id: int | None = None,
) -> tuple[UnifiedOrder | None, str]:
    """ينفذ طلب متجر: خصم + إرسال للمزود + حفظ. يرجع (الطلب، رسالة)."""
    from sqlalchemy.orm import selectinload

    from services.balance_service import BalanceService
    from services.notification_service import NotificationService

    result = await session.execute(
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.api_provider), selectinload(Product.sub_category))
    )
    product = result.scalar_one_or_none()
    if product is None:
        return None, "⚠️ المنتج غير موجود."
    provider: ApiProvider | None = product.api_provider
    if provider is None or not provider.is_active:
        return None, "⚠️ هذا المنتج غير متوفر حالياً (لا مزود)."

    ps = None
    if product.provider_service_ref_id:
        ps = await session.get(ProviderService, product.provider_service_ref_id)
    kind = target_kind_of(product, ps)
    ok, target_or_err = validate_target(kind, target)
    if not ok:
        return None, target_or_err

    cost, sell, _margin = await price_for(session, product, qty, db_user)
    if sell <= 0:
        return None, "⚠️ سعر غير صالح."

    # الكوبون (يُعاد التحقق لحظياً لمنع التلاعب)
    discount = Decimal("0")
    coupon_code = ""
    if coupon_kind and coupon_id:
        from services import coupon_service as _coupons

        if coupon_kind == "campaign":
            from database.models import CampaignCode as _CC

            row = await session.get(_CC, coupon_id)
        else:
            from database.models import Coupon as _CP

            row = await session.get(_CP, coupon_id)
        if row is not None:
            ok, _r, disc, _m = await _coupons.validate(session, coupon_kind, row.code, db_user.id, sell)
            if ok:
                discount = disc
                coupon_code = row.code
    total = (sell - discount).quantize(Decimal("0.0001"))
    if total <= 0:
        total = Decimal("0.01")

    notifier = NotificationService(bot)
    # 1) الخصم
    try:
        await BalanceService.deduct_balance(
            session, db_user.id, total, TransactionType.PURCHASE,
            description=f"شراء: {product.name_ar}" + (f" (كوبون {coupon_code})" if coupon_code else ""),
            related_table="products", related_id=product.id, is_purchase=True,
        )
    except Exception as exc:
        from services.balance_service import InsufficientBalanceError

        if isinstance(exc, InsufficientBalanceError):
            return None, f"❌ رصيدك غير كافٍ. المطلوب <b>{total}$</b>."
        raise

    # 2) الإرسال للمزود
    from protocols.factory import ProtocolFactory

    try:
        protocol = ProtocolFactory.create_from_provider(provider)
        service_id = product.provider_service_id or (ps.external_service_id if ps else "")
        placed = await protocol.place_order(
            service_id=str(service_id), target=target_or_err, quantity=str(qty),
        )
    except Exception as exc:
        # استرجاع فوري عند فشل الإرسال
        await BalanceService.add_balance(
            session, db_user.id, total, TransactionType.REFUND,
            description=f"استرجاع فشل طلب: {product.name_ar}",
        )
        logger.exception("فشل إرسال طلب متجر للمزود")
        return None, f"❌ تعذّر تنفيذ الطلب لدى المزود.\nتم استرجاع <b>{total}$</b> لرصيدك.\n<code>{str(exc)[:150]}</code>"

    # 3) الحفظ
    external = (placed.raw.get("order_code") if isinstance(placed.raw, dict) else None) or placed.external_order_id
    try:
        qty_int = int(Decimal(str(qty))) if Decimal(str(qty)) == int(Decimal(str(qty))) else 1
    except Exception:
        qty_int = 1
    order = UnifiedOrder(
        user_id=db_user.id,
        product_id=product.id,
        api_provider_id=provider.id,
        external_order_id=str(external)[:64],
        target=target_or_err[:500] if target_or_err else None,
        quantity=qty_int,
        price_usd=total,
        cost_price_usd=cost,
        status=UnifiedOrderStatus.PROCESSING,
        status_message="تم الإرسال للمزود — قيد التنفيذ",
        result_data=json.dumps({
            "qty": str(qty), "provider_order_id": placed.external_order_id,
            "sell": str(sell), "coupon": coupon_code, "discount": str(discount),
        }, ensure_ascii=False),
    )
    session.add(order)
    await session.commit()
    if coupon_kind and coupon_id and discount > 0:
        from services import coupon_service as _coupons2

        await _coupons2.apply_use(session, coupon_kind, coupon_id, db_user.id, discount)

    from services.dynamic_service import DynamicService

    await DynamicService.increment_product_sold(session, product.id)
    from services.message_style import dual as _dual, order_created as _created
    from services.settings_service import SettingsService as _SS2

    _rate = await _SS2.get_decimal("usd_to_syp_rate", Decimal("130"))
    _tlabel = {"phone": "رقم", "player": "User ID", "link": "رابط"}.get(kind, "الهدف")
    _order_no = str(external) if external else f"#{order.id}"
    await notifier.notify_user(
        db_user.telegram_id,
        _created(product.name_ar, _dual(total, _rate), _tlabel, target_or_err or "—", _order_no),
    )
    return order, "ok"


async def check_store_orders(bot) -> dict:
    """يفحص طلبات المتجر المعلقة ويحدثها (استرجاع تلقائي عند الفشل)."""
    from database.engine import async_session_maker

    from protocols.factory import ProtocolFactory
    from services.balance_service import BalanceService
    from services.notification_service import NotificationService

    stats = {"checked": 0, "completed": 0, "failed": 0, "refunded": 0}
    notifier = NotificationService(bot)
    async with async_session_maker() as session:
        result = await session.execute(
            select(UnifiedOrder).where(
                UnifiedOrder.status.in_([UnifiedOrderStatus.PENDING, UnifiedOrderStatus.PROCESSING]),
                UnifiedOrder.api_provider_id.is_not(None),
            ).order_by(UnifiedOrder.id).limit(50)
        )
        orders = list(result.scalars().all())
        for order in orders:
            provider = await session.get(ApiProvider, order.api_provider_id)
            if provider is None or not provider.is_active or not order.external_order_id:
                continue
            try:
                protocol = ProtocolFactory.create_from_provider(provider)
                st = await protocol.check_order_status(order.external_order_id)
            except Exception:
                logger.exception("فشل فحص طلب متجر %s", order.id)
                continue
            stats["checked"] += 1
            if st.status == "completed":
                from database.models import User as _User

                order.status = UnifiedOrderStatus.COMPLETED
                order.completed_at = datetime.utcnow()
                order.status_message = "مكتمل ✅"
                if st.raw:
                    order.result_data = json.dumps(st.raw, ensure_ascii=False, default=str)[:4000]
                await session.commit()
                stats["completed"] += 1
                try:
                    _u = await session.get(_User, order.user_id)
                    if _u:
                        from services.message_style import elapsed_ar as _elapsed, order_completed as _completed

                        delivered = st.raw.get("delivered_data", "") if isinstance(st.raw, dict) else ""
                        _prod = await session.get(Product, order.product_id) if order.product_id else None
                        _pname = _prod.name_ar if _prod else f"طلب #{order.id}"
                        _tgt = order.target or "—"
                        _tlabel = "رابط"
                        if _tgt.startswith("09"):
                            _tlabel = "رقم"
                        elif _tgt and not _tgt.startswith("http") and len(_tgt) <= 64:
                            _tlabel = "User ID"
                        await notifier.notify_user(
                            _u.telegram_id,
                            _completed(
                                _pname, _tlabel, _tgt,
                                str(order.external_order_id or order.id),
                                _elapsed(order.created_at, order.completed_at or datetime.utcnow()),
                                delivered,
                            ),
                        )
                        # إثبات اجتماعي بالقناة العامة (بدون بيانات حساسة)
                        from services.settings_service import SettingsService as _SS

                        if await _SS.get_bool("social_proof_enabled", True):
                            prod = await session.get(Product, order.product_id) if order.product_id else None
                            try:
                                await notifier.notify_successful_unified_order(
                                    username=getattr(_u, "username", None),
                                    full_name=getattr(_u, "full_name", None),
                                    product_name=prod.name_ar[:60] if prod else f"طلب #{order.id}",
                                    price_usd=f"{order.price_usd}",
                                    order_id=order.id,
                                )
                            except Exception:
                                pass
                except Exception:
                    logger.exception("فشل إشعار اكتمال طلب %s", order.id)
            elif st.status in ("failed", "refunded"):
                order.status = UnifiedOrderStatus.FAILED if st.status == "failed" else UnifiedOrderStatus.REFUNDED
                order.status_message = "فشل لدى المزود — تم الاسترجاع" if st.status == "failed" else "مسترجع"
                await session.commit()
                stats["failed"] += 1
                # استرجاع
                try:
                    await BalanceService.add_balance(
                        session, order.user_id, order.price_usd, TransactionType.REFUND,
                        description=f"استرجاع طلب متجر #{order.id}",
                    )
                    stats["refunded"] += 1
                except Exception:
                    logger.exception("فشل استرجاع طلب %s", order.id)
                try:
                    from database.models import User

                    user = await session.get(User, order.user_id)
                    if user:
                        await notifier.notify_user(
                            user.telegram_id,
                            f"↩️ <b>فشل طلبك #{order.id}</b> لدى المزود.\nتم استرجاع <b>{order.price_usd}$</b> لرصيدك.",
                        )
                except Exception:
                    pass
            elif st.status == "partial":
                order.status = UnifiedOrderStatus.PARTIAL
                order.status_message = f"تنفيذ جزئي (المتبقي: {st.remains})"
                await session.commit()
    return stats
