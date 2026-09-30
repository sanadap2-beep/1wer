"""
🔍 «ما لقيت لعبتك / برنامجك؟» — بحث شامل بكل خدمات المزود المسحوبة
(حتى غير المنشورة بالأقسام).

التدفق: زر بالقسم ← شرح + إدخال الاسم (عربي/إنجليزي) ← نتائج
← تفاصيل ← هدف ← كمية/فئة ← تأكيد ← طلب مباشر.
"""

from decimal import Decimal

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from database.models import ApiProvider, ApiProtocolType, Category, CategoryType, ProviderService
from services.store_order_service import FIND_MARGIN, direct_quote, place_direct_order, validate_target
from states.states import StoreFindStates

router = Router(name="storefind")

RESULT_LIMIT = 12

# عربي ↔ إنجليزي للبحث (توسيع التوكن)
AR_ALIASES: dict[str, list[str]] = {
    "ببجي": ["pubg"],
    "فري": ["free"],
    "فاير": ["fire"],
    "سيريتل": ["syriatel", "سيريتل", "سريتيل"],
    "امتي": ["mtn"],
    "شام": ["sham"],
    "انستا": ["instagram", "insta"],
    "انستقرام": ["instagram"],
    "تيك": ["tiktok", "tik"],
    "توك": ["tok"],
    "يوتيوب": ["youtube"],
    "تيليجرام": ["telegram"],
    "فيسبوك": ["facebook"],
    "واتساب": ["whatsapp"],
    "سناب": ["snap"],
    "تويتر": ["twitter"],
    "شدات": ["UC", "uc"],
    "رصيد": ["رصيد", "balance", "credit"],
    "متابعين": ["follower"],
    "لايكات": ["like"],
    "مشاهدات": ["view"],
}


async def _scope_providers(session, category_id: int) -> list[ApiProvider]:
    """مزودو نطاق البحث: حسب نوع القسم (رشق→SMM، الباقي→HyperStore)."""
    result = await session.execute(select(ApiProvider).where(ApiProvider.is_active.is_(True)))
    providers = list(result.scalars().all())
    if not category_id:
        return providers
    cat = await session.get(Category, category_id)
    if cat is None:
        return providers
    if cat.type == CategoryType.SMM:
        return [p for p in providers if p.protocol_type == ApiProtocolType.SMM_V2]
    from protocols.hyper_store import is_hyper_store_provider

    hypers = [p for p in providers if is_hyper_store_provider(p)]
    return hypers or providers


@router.callback_query(F.data.startswith("store:find:"))
async def find_start(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.rsplit(":", 1)[1])
    await state.update_data(find_cat=cid)
    back = f"store:cat:{cid}" if cid else "store:home"
    await callback.message.edit_text(
        "🔍 <b>ما لقيت لعبتك أو برنامجك؟</b>\n\n"
        "ابحث هنا بالعربي أو بالإنجليزي (مثال: <code>ببجي</code> / <code>PUBG</code> / <code>سيريتل</code>):\n\n"
        "تظهر لك خدمات إضافية من المزود، حتى لو لم تكن معروضة ضمن القوائم.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ إلغاء", callback_data=back, style="danger")]
        ]),
    )
    await state.set_state(StoreFindStates.waiting_query)
    await callback.answer()


@router.message(StoreFindStates.waiting_query)
async def find_search(message: Message, state: FSMContext, session):
    data = await state.get_data()
    query = (message.text or "").strip()
    if len(query) < 2:
        await message.answer("⚠️ اكتب كلمتين على الأقل.")
        return
    providers = await _scope_providers(session, int(data.get("find_cat", 0) or 0))
    if not providers:
        await message.answer("⚠️ لا يوجد مزود مربوط لهذا القسم بعد.")
        await state.clear()
        return
    pids = [p.id for p in providers]
    result = await session.execute(select(ProviderService).where(
        ProviderService.api_provider_id.in_(pids)).order_by(ProviderService.id))
    tokens = [t.lower() for t in query.split() if len(t) >= 2]

    def _stems(t: str) -> list[str]:
        out = [t, *(a.lower() for a in AR_ALIASES.get(t, []))]
        for suf in ("ات", "ين", "ون", "ية"):
            if t.endswith(suf) and len(t) > len(suf) + 1:
                out.append(t[: -len(suf)])
        if t.endswith(("ة", "ه")) and len(t) > 2:
            out.append(t[:-1])
        return out

    variants = [_stems(t) for t in tokens]
    scored: list[tuple[int, ProviderService]] = []
    for ps in result.scalars().all():
        hay = f"{ps.name or ''} {ps.category or ''}".lower()
        if all(any(v in hay for v in var) for var in variants):
            score = 0 if (ps.name or "").lower().startswith(tokens[0]) else 1
            scored.append((score, ps))
    scored.sort(key=lambda x: x[0])
    hits = [ps for _, ps in scored[:RESULT_LIMIT]]
    if not hits:
        await message.answer(
            "😕 لا نتائج مطابقة.\nجرّب كلمة أقصر (مثال: <code>ببجي</code> بدل <code>ببجي موبايل شدات</code>) أو بالإنجليزية."
        )
        return
    lines = [f"🔍 نتائج <b>{query[:40]}</b> ({len(hits)}):\n"]
    rows: list[list[InlineKeyboardButton]] = []
    for ps in hits:
        try:
            _ps, _prov, _kind, _cost, sell, _opts = await direct_quote(session, ps.id, "1")
            price_txt = f"{sell}$"
        except ValueError:
            price_txt = "—"
        rows.append([InlineKeyboardButton(
            text=f"{ps.name[:38]} — {price_txt}", callback_data=f"store:found:{ps.id}", style="success")])
    rows.append([InlineKeyboardButton(text="🔎 بحث جديد", callback_data=f"store:find:{data.get('find_cat', 0)}")])
    await message.answer("\n".join(lines) + "\nاختر الخدمة لعرض تفاصيلها:",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await state.clear()


@router.callback_query(F.data.startswith("store:found:"))
async def find_detail(callback: CallbackQuery, session, state: FSMContext, db_user):
    ps_id = int(callback.data.rsplit(":", 1)[1])
    try:
        ps, provider, kind, _cost, sell, options = await direct_quote(session, ps_id, "1")
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await state.update_data(find_ps=ps_id, find_kind=kind)
    kind_names = {"phone": "📱 رقم هاتف (09)", "player": "🎮 Player ID", "link": "🔗 رابط", "none": "تأكيد فقط"}
    per = "لكل وحدة" if ps.price_type.value != "per_1000" else "لكل 1000"
    text = (
        f"🔍 <b>{ps.name[:80]}</b>\n\n"
        f"📂 التصنيف: {ps.category or '—'}\n"
        f"💵 السعر {per}: <b>{sell}$</b>\n"
        f"📝 المطلوب: {kind_names.get(kind, kind)}\n"
    )
    if options:
        text += f"📊 فئات ثابتة: {len(options)} خياراً\n"
    elif ps.requires_quantity:
        text += f"📊 الكمية: من {ps.min_quantity} إلى {ps.max_quantity}\n"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 شراء", callback_data=f"store:fbuy:{ps_id}", style="success")],
        [InlineKeyboardButton(text="🔙 رجوع للبحث", callback_data="store:find:0")],
    ]))
    await callback.answer()


@router.callback_query(F.data.startswith("store:fbuy:"))
async def find_buy(callback: CallbackQuery, session, state: FSMContext):
    ps_id = int(callback.data.rsplit(":", 1)[1])
    try:
        _ps, _prov, kind, _c, _s, _o = await direct_quote(session, ps_id, "1")
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await state.update_data(find_ps=ps_id, find_kind=kind)
    if kind != "none":
        hint = {"phone": "📱 أرسل الرقم (09xxxxxxxx):", "player": "🎮 أرسل Player ID:",
                "link": "🔗 أرسل الرابط:"}[kind]
        await callback.message.edit_text(
            f"{hint}\n\nأو اضغط إلغاء:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ إلغاء", callback_data=f"store:found:{ps_id}", style="danger")]
            ]),
        )
        await state.set_state(StoreFindStates.waiting_target)
    else:
        await state.update_data(find_target="", find_qty="1")
        await _find_confirm(callback.message, state, session, ps_id, edit=True)
    await callback.answer()


@router.message(StoreFindStates.waiting_target)
async def find_target_received(message: Message, state: FSMContext, session):
    data = await state.get_data()
    ok, value = validate_target(data.get("find_kind", "link"), message.text or "")
    if not ok:
        await message.answer(value)
        return
    await state.update_data(find_target=value)
    ps_id = int(data["find_ps"])
    ps = await session.get(ProviderService, ps_id)
    try:
        import json as _json

        options = (_json.loads(ps.raw_data or "{}") or {}).get("quantity_options") or []
    except Exception:
        options = []
    if options:
        shown = options[:20]
        rows, row = [], []
        for o in shown:
            try:
                _p, _v, _k, _c, sell, _x = await direct_quote(session, ps_id, o)
                row.append(InlineKeyboardButton(text=f"{o} = {sell}$", callback_data=f"store:fqty:{o}", style="success"))
            except ValueError:
                continue
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(text="❌ إلغاء", callback_data=f"store:found:{ps_id}", style="danger")])
        await message.answer(f"اختر الفئة ({len(options)}):",
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        return
    if ps.requires_quantity:
        await state.set_state(StoreFindStates.waiting_quantity)
        await message.answer(f"📊 أرسل الكمية (من {ps.min_quantity} إلى {ps.max_quantity}):")
        return
    await state.update_data(find_qty="1")
    await _find_confirm(message, state, session, ps_id, edit=False)


@router.callback_query(F.data.startswith("store:fqty:"))
async def find_qty_picked(callback: CallbackQuery, state: FSMContext, session):
    qty = callback.data.split(":", 2)[2]
    data = await state.get_data()
    await state.update_data(find_qty=qty)
    await _find_confirm(callback.message, state, session, int(data["find_ps"]), edit=True)
    await callback.answer()


@router.message(StoreFindStates.waiting_quantity)
async def find_quantity_received(message: Message, state: FSMContext, session):
    data = await state.get_data()
    ps = await session.get(ProviderService, int(data["find_ps"]))
    try:
        qty = int((message.text or "").strip())
    except (ValueError, TypeError):
        await message.answer("⚠️ رقم صحيح فقط.")
        return
    if qty < int(ps.min_quantity or 1) or qty > int(ps.max_quantity or 0):
        await message.answer(f"⚠️ بين {ps.min_quantity} و {ps.max_quantity}.")
        return
    await state.update_data(find_qty=str(qty))
    await _find_confirm(message, state, session, ps.id, edit=False)


async def _find_confirm(message, state, session, ps_id: int, edit: bool):
    from services.message_style import confirm_order, dual
    from services.settings_service import SettingsService

    data = await state.get_data()
    qty, target = data.get("find_qty", "1"), data.get("find_target", "")
    ps, _prov, kind, _cost, sell, _opts = await direct_quote(session, ps_id, qty)
    rate = await SettingsService.get_decimal("usd_to_syp_rate", Decimal("130"))
    kind_names = {"phone": "رقم", "player": "User ID", "link": "رابط", "none": "الهدف"}
    text = confirm_order(product=f"{ps.name[:60]} (بحث 🔍)", qty=qty,
                         target_label=kind_names.get(kind, "رابط"), target=target or "—",
                         before_dual=dual(sell, rate), after_dual=dual(sell, rate))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تأكيد الشراء", callback_data="store:fconfirm", style="primary")],
        [InlineKeyboardButton(text="❌ إلغاء", callback_data=f"store:found:{ps_id}", style="danger")],
    ])
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
        except Exception:
            await message.answer(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "store:fconfirm")
async def find_confirm(callback: CallbackQuery, session, db_user, state: FSMContext):
    data = await state.get_data()
    ps_id = int(data.get("find_ps", 0))
    if not ps_id:
        await callback.answer("⚠️ انتهت الجلسة.", show_alert=True)
        return
    await callback.answer("⏳ جاري التنفيذ...")
    order, msg = await place_direct_order(
        session, callback.bot, db_user, ps_id, data.get("find_target", ""), data.get("find_qty", "1"))
    await state.clear()
    if order is None:
        try:
            await callback.message.edit_text(msg)
        except Exception:
            await callback.message.answer(msg)
        return
    from services.message_style import SEP as _SEP

    try:
        await callback.message.edit_text(
            f"✅ تـم إرسـال طـلـبـك بـنـجـاح!\n{_SEP}\n\n"
            f"🆔 رقم الطلب: <code>{order.external_order_id or order.id}</code>\n"
            f"💰 المبلغ: <b>{order.price_usd}$</b>\n\nتابع حالته من 🧾 طلباتي.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧾 طلباتي", callback_data="store:myorders", style="primary")],
                [InlineKeyboardButton(text="🛍 المتجر", callback_data="store:home", style="success")],
            ]),
        )
    except Exception:
        await callback.message.answer("✅ تم إرسال طلبك!")
