"""
إدارة مزودي المتجر (HyperStore للألعاب/البرامج/الرصيد + SMM V2 للرشق).

- إضافة مزود (النوع + الرابط + المفتاح) مع فحص فوري للاتصال والرصيد.
- فحص، مزامنة الكتالوج، تفعيل/تعطيل، حذف.
"""

import json
from datetime import datetime
from decimal import Decimal

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from database.models import ApiProvider, ApiProviderType, ApiProtocolType
from filters.admin_filter import IsAdmin
from services.dynamic_service import DynamicService
from states.states import AdminStoreStates

router = Router(name="admin_store_providers")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

HYPER_DEFAULT_URL = "https://api.hyper4store.com"
SMM_DEFAULT_URL = "https://smmprovider.co/api/v2"


def _providers_kb(providers: list[ApiProvider]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in providers:
        mark = "🟢" if p.is_active else "⚪"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {p.name} ({p.type.value})",
            callback_data=f"admin:store_prov:{p.id}",
        )])
    rows.append([InlineKeyboardButton(text="➕ إضافة مزود HyperStore", callback_data="admin:store_prov_add:hyper", style="success")])
    rows.append([InlineKeyboardButton(text="➕ إضافة مزود SMM", callback_data="admin:store_prov_add:smm", style="success")])
    rows.append([InlineKeyboardButton(text="🔙 لوحة الإدارة", callback_data="admin:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _provider_kb(provider_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_text = "⏸ تعطيل" if is_active else "▶️ تفعيل"
    toggle_style = "danger" if is_active else "success"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🩺 فحص الاتصال والرصيد", callback_data=f"admin:store_prov_test:{provider_id}", style="primary")],
        [InlineKeyboardButton(text="🔑 تعديل مفتاح API", callback_data=f"admin:store_prov_key_edit:{provider_id}")],
        [InlineKeyboardButton(text="🔄 مزامنة الكتالوج", callback_data=f"admin:store_prov_sync:{provider_id}", style="success")],
        [InlineKeyboardButton(text=toggle_text, callback_data=f"admin:store_prov_toggle:{provider_id}", style=toggle_style)],
        [InlineKeyboardButton(text="🗑 حذف", callback_data=f"admin:store_prov_del:{provider_id}", style="danger")],
        [InlineKeyboardButton(text="🔙 المزودون", callback_data="admin:store_providers")],
    ])


def _provider_text(p: ApiProvider) -> str:
    status = "🟢 مفعّل" if p.is_active else "⚪ معطّل"
    balance = f"{p.balance}$" if p.balance is not None else "—"
    return (
        f"🔌 <b>{p.name}</b>\n\n"
        f"النوع: <code>{p.type.value}</code> | البروتوكول: <code>{p.protocol_type.value}</code>\n"
        f"الحالة: {status}\n"
        f"💰 الرصيد: <b>{balance}</b> {p.currency}\n"
        f"🛠 الخدمات المسحوبة: <b>{p.total_services}</b>\n"
        f"🕐 آخر فحص: {p.last_checked_at.strftime('%Y-%m-%d %H:%M') if p.last_checked_at else '—'}\n"
        f"🕐 آخر مزامنة: {p.last_sync_at.strftime('%Y-%m-%d %H:%M') if p.last_sync_at else '—'}\n"
        + (f"⚠️ آخر خطأ: {p.last_error[:150]}\n" if p.last_error else "")
        + f"\nالرابط: <code>{p.api_url}</code>"
    )


@router.callback_query(F.data == "admin:store_providers")
async def providers_list(callback: CallbackQuery, session):
    providers = await DynamicService.get_all_providers(session)
    # إخفاء مزودي الأرقام القدامى إن وجدوا بهذا الجدول
    await callback.message.edit_text(
        "🔌 <b>مزودو المتجر</b>\n\nاختر مزوداً لإدارته أو أضف جديداً:",
        reply_markup=_providers_kb(providers),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:store_prov:"))
async def provider_view(callback: CallbackQuery, session):
    pid = int(callback.data.rsplit(":", 1)[1])
    p = await DynamicService.get_provider(session, pid)
    if not p:
        await callback.answer("⚠️ غير موجود.", show_alert=True)
        return
    await callback.message.edit_text(_provider_text(p), reply_markup=_provider_kb(p.id, p.is_active))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:store_prov_key_edit:"))
async def provider_key_edit_start(callback: CallbackQuery, state: FSMContext, session):
    provider_id = int(callback.data.rsplit(":", 1)[1])
    provider = await DynamicService.get_provider(session, provider_id)
    if not provider:
        await callback.answer("⚠️ المزود غير موجود.", show_alert=True)
        return

    await state.clear()
    await state.update_data(store_prov_key_provider_id=provider_id)
    await state.set_state(AdminStoreStates.waiting_provider_key_edit)
    await callback.message.edit_text(
        f"🔑 <b>تعديل مفتاح API — {provider.name}</b>\n\n"
        "أرسل المفتاح الجديد كنص. لن أعرضه بعد الحفظ.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ إلغاء", callback_data="admin:store_prov_key_edit_cancel", style="danger")]
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:store_prov_key_edit_cancel")
async def provider_key_edit_cancel(callback: CallbackQuery, state: FSMContext, session):
    await state.clear()
    await providers_list(callback, session)


@router.message(AdminStoreStates.waiting_provider_key_edit)
async def provider_key_edit_received(message: Message, state: FSMContext, session):
    api_key = (message.text or "").strip()
    if not api_key:
        await message.answer("⚠️ أرسل مفتاح API كنص.")
        return

    data = await state.get_data()
    provider_id = data.get("store_prov_key_provider_id")
    provider = await DynamicService.get_provider(session, provider_id) if provider_id else None
    if not provider:
        await state.clear()
        await message.answer("⚠️ تعذر العثور على المزود. افتح قائمة مزودي المتجر وحاول مجدداً.")
        return

    await DynamicService.update_provider(
        session,
        provider_id,
        api_key=api_key,
        last_checked_at=None,
        last_error=None,
    )
    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass

    status_message = await message.answer("⏳ تم حفظ المفتاح. جاري فحص الاتصال والرصيد...")
    ok, info = await _test_provider(session, provider_id)
    provider = await DynamicService.get_provider(session, provider_id)
    title = "✅ تم تحديث المفتاح" if ok else "⚠️ تم حفظ المفتاح لكن فشل فحص الاتصال"
    text = f"{title} للمزود <b>{provider.name}</b>.\n\n{info}\n\n" + _provider_text(provider)
    try:
        await status_message.edit_text(text, reply_markup=_provider_kb(provider.id, provider.is_active))
    except Exception:
        await message.answer(text, reply_markup=_provider_kb(provider.id, provider.is_active))


@router.callback_query(F.data.startswith("admin:store_prov_add:"))
async def provider_add_start(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.rsplit(":", 1)[1]  # hyper | smm
    await state.update_data(store_prov_kind=kind)
    default_url = HYPER_DEFAULT_URL if kind == "hyper" else SMM_DEFAULT_URL
    await state.update_data(store_prov_url=default_url)
    await callback.message.edit_text(
        f"➕ <b>إضافة مزود {'HyperStore (ألعاب/برامج/رصيد)' if kind == 'hyper' else 'SMM (رشق)'}</b>\n\n"
        f"الرابط الافتراضي: <code>{default_url}</code>\n\n"
        "أرسل اسماً للمزود (مثال: <code>المتجر الرئيسي</code>):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ إلغاء", callback_data="admin:store_providers", style="danger")]
        ]),
    )
    await state.set_state(AdminStoreStates.waiting_provider_name)
    await callback.answer()


@router.message(AdminStoreStates.waiting_provider_name)
async def provider_name_received(message: Message, state: FSMContext):
    await state.update_data(store_prov_name=message.text.strip()[:64])
    data = await state.get_data()
    await message.answer(
        f"الرابط الحالي: <code>{data.get('store_prov_url')}</code>\n\n"
        "أرسل رابط الـ API إذا تريد تغييره، أو أرسل <code>-</code> للإبقاء عليه:"
    )
    await state.set_state(AdminStoreStates.waiting_provider_url)


@router.message(AdminStoreStates.waiting_provider_url)
async def provider_url_received(message: Message, state: FSMContext):
    val = message.text.strip()
    if val != "-":
        await state.update_data(store_prov_url=val)
    await message.answer("🔑 أرسل مفتاح الـ API الآن:")
    await state.set_state(AdminStoreStates.waiting_provider_key)


@router.message(AdminStoreStates.waiting_provider_key)
async def provider_key_received(message: Message, state: FSMContext, session):
    data = await state.get_data()
    kind = data.get("store_prov_kind", "hyper")
    name = data.get("store_prov_name", "مزود")
    url = data.get("store_prov_url", HYPER_DEFAULT_URL)
    key = message.text.strip()
    if kind == "hyper":
        ptype, proto, config = ApiProviderType.STORE, ApiProtocolType.CUSTOM, json.dumps({"engine": "hyper_store"})
    else:
        ptype, proto, config = ApiProviderType.SMM, ApiProtocolType.SMM_V2, None
    provider = await DynamicService.create_provider(
        session, name=name, provider_type=ptype, api_url=url, api_key=key,
        protocol_type=proto, custom_config=config,
    )
    await state.clear()
    # فحص فوري
    status_msg = await message.answer("⏳ جاري فحص الاتصال...")
    ok, info = await _test_provider(session, provider.id)
    p = await DynamicService.get_provider(session, provider.id)
    text = f"✅ تمت إضافة المزود: <b>{name}</b>\n\n{info}\n\n" + _provider_text(p)
    try:
        await status_msg.edit_text(text, reply_markup=_provider_kb(p.id, p.is_active))
    except Exception:
        await message.answer(text, reply_markup=_provider_kb(p.id, p.is_active))


async def _test_provider(session, provider_id: int) -> tuple[bool, str]:
    from protocols.factory import ProtocolFactory

    p = await DynamicService.get_provider(session, provider_id)
    if not p:
        return False, "⚠️ المزود غير موجود."
    try:
        protocol = ProtocolFactory.create_from_provider(p)
        await protocol.test_connection()
        balance = await protocol.get_balance()
        await DynamicService.update_provider(
            session, p.id, balance=balance.amount, currency=balance.currency,
            last_checked_at=datetime.utcnow(), last_error=None,
        )
        low = ""
        if balance.amount < (p.low_balance_threshold or Decimal("10")):
            low = " ⚠️ <b>رصيد منخفض!</b> اشحن حسابك عند المزود."
        return True, f"🟢 الاتصال ناجح.\n💰 الرصيد: <b>{balance.amount}$</b> {balance.currency}.{low}"
    except Exception as exc:
        err = str(exc)[:200]
        await DynamicService.update_provider(
            session, p.id, last_checked_at=datetime.utcnow(), last_error=err,
        )
        return False, f"🔴 فشل الفحص: {err}"


@router.callback_query(F.data.startswith("admin:store_prov_test:"))
async def provider_test(callback: CallbackQuery, session):
    pid = int(callback.data.rsplit(":", 1)[1])
    await callback.answer("⏳ جاري الفحص...")
    ok, info = await _test_provider(session, pid)
    p = await DynamicService.get_provider(session, pid)
    try:
        await callback.message.edit_text(info + "\n\n" + _provider_text(p), reply_markup=_provider_kb(p.id, p.is_active))
    except Exception:
        await callback.message.answer(info)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:store_prov_sync:"))
async def provider_sync(callback: CallbackQuery, session):
    from services.store_sync_service import sync_provider

    pid = int(callback.data.rsplit(":", 1)[1])
    p = await DynamicService.get_provider(session, pid)
    if not p:
        await callback.answer("⚠️ غير موجود.", show_alert=True)
        return
    await callback.answer("⏳ بدأت المزامنة... قد تستغرق دقيقة.")
    try:
        await callback.message.edit_text(f"⏳ <b>جاري مزامنة {p.name}...</b>\n\nلا تضغط شيئاً حتى تكتمل.")
    except Exception:
        pass
    report = await sync_provider(session, p)
    try:
        await callback.message.edit_text(
            report.summary() + "\n\nالخطوة التالية: 📤 نشر من المزود لعرض الخدمات للزبائن.",
            reply_markup=_provider_kb(p.id, p.is_active),
        )
    except Exception:
        await callback.message.answer(report.summary())


@router.callback_query(F.data.startswith("admin:store_prov_toggle:"))
async def provider_toggle(callback: CallbackQuery, session):
    pid = int(callback.data.rsplit(":", 1)[1])
    p = await DynamicService.get_provider(session, pid)
    if not p:
        await callback.answer("⚠️ غير موجود.", show_alert=True)
        return
    await DynamicService.update_provider(session, pid, is_active=not p.is_active)
    p = await DynamicService.get_provider(session, pid)
    await callback.message.edit_text(_provider_text(p), reply_markup=_provider_kb(p.id, p.is_active))
    await callback.answer("✅ تم التحديث.")


@router.callback_query(F.data.startswith("admin:store_prov_del:"))
async def provider_delete(callback: CallbackQuery, session):
    pid = int(callback.data.rsplit(":", 1)[1])
    if "confirm" not in callback.data:
        await callback.message.edit_text(
            "⚠️ <b>تأكيد الحذف؟</b>\n\nسيُحذف المزود مع كل خدماته المسحوبة. المنتجات المنشورة تبقى لكن بدون مزود.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗑 نعم، احذف", callback_data=f"admin:store_prov_del:{pid}:confirm", style="danger")],
                [InlineKeyboardButton(text="❌ تراجع", callback_data=f"admin:store_prov:{pid}")],
            ]),
        )
        await callback.answer()
        return
    # فك ارتباط المنتجات أولاً
    from sqlalchemy import update as sa_update
    from database.models import Product

    await session.execute(
        sa_update(Product).where(Product.api_provider_id == pid).values(api_provider_id=None)
    )
    await session.commit()
    await DynamicService.delete_provider(session, pid)
    await callback.answer("🗑 تم الحذف.")
    providers = await DynamicService.get_all_providers(session)
    await callback.message.edit_text(
        "🔌 <b>مزودو المتجر</b>\n\nاختر مزوداً لإدارته أو أضف جديداً:",
        reply_markup=_providers_kb(providers),
    )
