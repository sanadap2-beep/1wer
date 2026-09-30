"""
كل أزرار لوحة الأدمن.
"""

from aiogram.types import InlineKeyboardMarkup, WebAppInfo, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings


# ══════════════ اللوحة الرئيسية ══════════════


ADMIN_TABS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "numbers": (
        "📱 الأرقام والجلسات 🔥",
        [
            ("🚀 الإعداد السريع (3 خطوات)", "admin:quick_setup"),
            ("📞 إدارة خدمات الأرقام", "admin:number_services"),
            ("قسم ارقام تلجرام جاهزة (رفع ملف)", "admin:tg_ready"),
            ("📞 طلبات الأرقام", "admin:number_orders"),
            ("🌍 إدارة الدول", "admin:countries"),
            ("🌐 مزودو الأرقام", "admin:providers"),
            ("📊 جودة مزودي الأرقام", "admin:number_provider_quality"),
            ("💵 تعديل الأسعار والهوامش", "admin:pricing"),
            ("📡 قناة التوفر المتقطع", "admin:nsvc_avail"),
        ],
    ),
    "finance": (
        "💰 المالية 🔥",
        [
            ("💳 طلبات الشحن", "admin:deposits"),
            ("📒 جرد الحسابات", "admin:ledger"),
            ("📊 إحصائيات البوت", "admin:stats"),
            ("⭐ إدارة باقات النجوم", "admin:stars"),
        ],
    ),
    "users": (
        "👥 المستخدمون والتسويق",
        [
            ("👥 إدارة المستخدمين", "admin:users"),
            ("👑 طلبات التجار", "admin:traders"),
            ("🎟 الكوبونات والحملات", "admin:coupons"),
            ("📢 إذاعة جماعية", "admin:broadcast"),
            ("📌 الاشتراك الإجباري", "admin:channels"),
            ("🎫 تذاكر الدعم", "admin:tickets"),
            ("🔔 إدارة الإشعارات", "admin:notifications"),
        ],
    ),
    "store": (
        "🛍 المتجر (رشق/ألعاب/برامج/رصيد)",
        [
            ("🎮 تجهيز قسم شحن الألعاب", "admin:setup:games"),
            ("📱 تجهيز اشتراكات التطبيقات", "admin:setup:apps"),
            ("💳 تجهيز قسم الأرصدة", "admin:setup:balances"),
            ("📈 تجهيز قسم الرشق", "admin:setup:smm"),
            ("🔌 مزودو المتجر", "admin:store_providers"),
            ("📁 أقسام المتجر", "admin:store_cats"),
            ("📤 نشر من المزود", "admin:store_publish"),
            ("🌳 إنشاء الأقسام من المزود", "admin:store_autotree"),
            ("⚡ تجهيز أقسام الرشق", "admin:store_smm_setup"),
            ("🧹 تفريغ المتجر", "admin:store_flush"),
        ],
    ),
    "system": (
        "⚙️ النظام",
        [
            ("🩺 صحة النظام", "admin:health"),
            ("⚙️ الإعدادات العامة", "admin:settings"),
            ("🔧 وضع الصيانة", "admin:maintenance"),
            ("🎛 أزرار الواجهة", "admin:main_buttons"),
            ("🧩 مركز الإضافات", "admin:features"),
            ("📡 مباشر البوت", "admin:live_feed"),
            ("👨‍💼 إدارة الأدمنية", "admin:multi_admin"),
            ("📜 سجل الإدارة", "admin:audit"),
        ],
    ),
}


def admin_main_kb() -> InlineKeyboardMarkup:
    """Compact admin home: four tabs instead of a 40-button wall."""
    b = InlineKeyboardBuilder()
    b.button(text="🆕 آخر التحديثات والإضافات", callback_data="admin:changelog")
    b.button(text="📘 شرح البوت", callback_data="admin:guide")
    for key, (title, _items) in ADMIN_TABS.items():
        b.button(text=title, callback_data=f"admin:tab:{key}")
    if settings.ADMIN_WEBAPP_URL:
        b.button(
            text="🌐 لوحة الويب",
            web_app=WebAppInfo(url=settings.ADMIN_WEBAPP_URL),
        )
    # اختصارات مراقبة لا تعيد ازدحام اللوحة، لكنها تحفظ الوصول السريع
    # لأكثر شاشتين يحتاجهما الأدمن يومياً.
    b.button(text="📱 خدمات الأرقام", callback_data="admin:number_services")
    b.button(text="قسم ارقام تلجرام جاهزة", callback_data="admin:tg_ready")
    b.adjust(2)
    return b.as_markup()


def admin_tab_kb(tab: str) -> InlineKeyboardMarkup:
    """Keyboard for one of the four admin tabs."""
    from keyboards.style_utils import style_for_callback

    b = InlineKeyboardBuilder()
    _title, items = ADMIN_TABS.get(tab, ADMIN_TABS["finance"])
    for label, callback_data in items:
        _style = style_for_callback(callback_data, label)
        if _style:
            b.button(text=label, callback_data=callback_data, style=_style)
        else:
            b.button(text=label, callback_data=callback_data)
    b.button(text="🔙 لوحة الإدارة", callback_data="admin:main")
    b.adjust(2, 2, 2, 2, 2, 2, 2, 1)
    return b.as_markup()


def admin_deposits_kb(
    deposits,
    page: int = 0,
    total_pages: int = 1,
) -> InlineKeyboardMarkup:
    """قائمة طلبات الشحن للأدمن."""
    b = InlineKeyboardBuilder()
    for deposit in deposits:
        status = getattr(deposit.status, "value", deposit.status)
        b.button(
            text=f"#{deposit.id} {deposit.amount_usd}$ · {status}",
            callback_data=f"admin:deposit_view:{deposit.id}", style="primary",
        )
    if page > 0:
        b.button(
            text="◀️ السابق",
            callback_data=f"admin:deposits:{page - 1}",
        )
    if page < total_pages - 1:
        b.button(
            text="التالي ▶️",
            callback_data=f"admin:deposits:{page + 1}",
        )
    b.button(text="🔙 لوحة الإدارة", callback_data="admin:main")
    b.adjust(1, 2, 1)
    return b.as_markup()


def admin_deposit_view_kb(deposit_id: int, pending: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if pending:
        b.button(text="✅ قبول وإضافة الرصيد", callback_data=f"deposit_accept:{deposit_id}", style="primary")
        b.button(text="❌ رفض الطلب", callback_data=f"deposit_reject:{deposit_id}", style="danger")
    b.button(text="🔙 طلبات الشحن", callback_data="admin:deposits")
    b.adjust(2, 1)
    return b.as_markup()


def admin_number_orders_kb(
    orders,
    page: int = 0,
    total_pages: int = 1,
) -> InlineKeyboardMarkup:
    """قائمة طلبات أرقام SMS للأدمن."""
    b = InlineKeyboardBuilder()
    for order in orders:
        b.button(
            text=f"#{order.id} {order.phone_number} · {order.status.value}",
            callback_data=f"admin:num_order_view:{order.id}", style="primary",
        )
    if page > 0:
        b.button(
            text="◀️ السابق",
            callback_data=f"admin:number_orders:{page - 1}",
        )
    if page < total_pages - 1:
        b.button(
            text="التالي ▶️",
            callback_data=f"admin:number_orders:{page + 1}",
        )
    b.button(text="🔙 اللوحة الرئيسية", callback_data="admin:main")
    b.adjust(1, 2, 1)
    return b.as_markup()


def admin_number_order_detail_kb(order) -> InlineKeyboardMarkup:
    """أزرار إدارة طلب رقم واحد."""
    b = InlineKeyboardBuilder()
    status = getattr(order.status, "value", order.status)
    if status == "pending":
        b.button(
            text="❌ إلغاء واسترجاع الرصيد",
            callback_data=f"admin:num_order_refund_ask:{order.id}", style="danger",
        )
    b.button(text="🔙 طلبات الأرقام", callback_data="admin:number_orders")
    b.button(text="🏠 اللوحة الرئيسية", callback_data="admin:main")
    b.adjust(1)
    return b.as_markup()


def admin_number_order_refund_confirm_kb(order_id: int) -> InlineKeyboardMarkup:
    """تأكيد استرجاع طلب رقم."""
    b = InlineKeyboardBuilder()
    b.button(
        text="✅ نعم، استرجع الرصيد",
        callback_data=f"admin:num_order_refund:{order_id}", style="danger",
    )
    b.button(
        text="❌ إلغاء",
        callback_data=f"admin:num_order_view:{order_id}", style="primary",
    )
    b.adjust(1)
    return b.as_markup()


def admin_health_kb() -> InlineKeyboardMarkup:
    """أزرار مراقبة صحة النظام."""
    b = InlineKeyboardBuilder()
    b.button(text="🔄 تحديث الفحص", callback_data="admin:health:refresh")
    b.button(text="🔙 لوحة الإدارة", callback_data="admin:main")
    b.adjust(1)
    return b.as_markup()


def admin_audit_kb(page: int = 0, has_next: bool = False) -> InlineKeyboardMarkup:
    """أزرار سجل تعديلات الإدارة."""
    b = InlineKeyboardBuilder()
    if page > 0:
        b.button(text="◀️ السابق", callback_data=f"admin:audit:{page - 1}")
    if has_next:
        b.button(text="التالي ▶️", callback_data=f"admin:audit:{page + 1}")
    b.button(text="🔙 لوحة الإدارة", callback_data="admin:main")
    b.adjust(2, 1)
    return b.as_markup()


def admin_back_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔙 رجوع للوحة الرئيسية", callback_data="admin:main")
    return b.as_markup()


# ══════════════ الصيانة ══════════════


def admin_maintenance_kb(is_active: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if is_active:
        b.button(text="🟢 إيقاف الصيانة", callback_data="admin:maintenance_off")
    else:
        b.button(text="🔴 تفعيل الصيانة", callback_data="admin:maintenance_on", style="danger")
    b.button(text="📝 تعديل رسالة الصيانة", callback_data="admin:maintenance_msg")
    b.button(text="🔙 رجوع", callback_data="admin:main")
    b.adjust(1)
    return b.as_markup()


# ══════════════ الأقسام ══════════════


# ══════════════ الأقسام الفرعية ══════════════


# ══════════════ المنتجات ══════════════


# ══════════════ مزودو API ══════════════


# ══════════════ باقات النجوم ══════════════


def admin_stars_kb(packages) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for pkg in packages:
        status = "🟢" if pkg.is_active else "⚪"
        b.button(
            text=f"{status} {pkg.label} = {pkg.usd_amount}$",
            callback_data=f"admin:star_view:{pkg.id}",
        )
    b.button(text="➕ إضافة باقة", callback_data="admin:star_add", style="success")
    b.button(text="🔙 رجوع", callback_data="admin:main")
    b.adjust(1)
    return b.as_markup()


def admin_star_detail_kb(package) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if package.is_active:
        b.button(text="⚪ تعطيل", callback_data=f"admin:star_toggle:{package.id}")
    else:
        b.button(text="🟢 تفعيل", callback_data=f"admin:star_toggle:{package.id}")
    b.button(text="🗑 حذف", callback_data=f"admin:star_delete:{package.id}", style="danger")
    b.button(text="🔙 رجوع", callback_data="admin:stars")
    b.adjust(1)
    return b.as_markup()


# ══════════════ الكوبونات ══════════════


# ══════════════ أكواد الحملات (campaign_codes) ══════════════


# ══════════════ طلبات «اشحن لأهلك» (topup_gift) ══════════════


# ══════════════ الأدمنية ══════════════


def admin_multi_admin_kb(admins) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for admin in admins:
        b.button(
            text=f"👤 {admin.full_name or admin.telegram_id} (@{admin.username or '-'})",
            callback_data=f"admin:madmin_view:{admin.id}",
        )
    b.button(text="➕ إضافة أدمن", callback_data="admin:madmin_add", style="success")
    b.button(text="🔙 رجوع", callback_data="admin:main")
    b.adjust(1)
    return b.as_markup()


def admin_madmin_detail_kb(admin_user, is_primary: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if not is_primary:
        b.button(text="🗑 إزالة الأدمنية", callback_data=f"admin:madmin_remove:{admin_user.id}", style="danger")
    b.button(text="🔙 رجوع", callback_data="admin:multi_admin")
    b.adjust(1)
    return b.as_markup()


# ══════════════ خدمات الأرقام ══════════════


def admin_number_services_kb(services) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for svc in services:
        status = "🟢" if svc.is_active else "⚪"
        b.button(
            text=f"{status} {svc.emoji} {svc.name_ar}",
            callback_data=f"admin:nsvc_view:{svc.id}",
        )
    b.button(text="➕ إضافة خدمة أرقام", callback_data="admin:nsvc_add", style="success")
    b.button(text="📡 قناة التوفر المتقطع", callback_data="admin:nsvc_avail")
    b.button(text="🔙 رجوع", callback_data="admin:main")
    b.adjust(1)
    return b.as_markup()


def admin_nsvc_avail_kb(
    rotate_stable: bool = True,
    auto_repost: bool = True,
    restock_push: bool = False,
) -> InlineKeyboardMarkup:
    """أزرار ضبط قناة التوفر المتقطع."""
    b = InlineKeyboardBuilder()
    b.button(text="📡 ضبط قناة التوفر", callback_data="admin:nsvc_avail_channel")
    b.button(text="🔢 عدد الدول المعروضة", callback_data="admin:nsvc_avail_topn")
    b.button(text="🌍 الدول النادرة المراقبة", callback_data="admin:nsvc_avail_watchlist")
    b.button(text="📱 اختيار الخدمة", callback_data="admin:nsvc_avail_services")
    b.button(
        text=("🔀 الترتيب الدوّار: مفعّل" if rotate_stable else "⏸ الترتيب الدوّار: معطّل"),
        callback_data="admin:nsvc_avail_rotate",
    )
    b.button(
        text=("🔔 إعادة النشر التلقائي: مفعّل" if auto_repost else "🔕 إعادة النشر التلقائي: معطّل"),
        callback_data="admin:nsvc_avail_autorepost",
    )
    b.button(
        text="⏱ كل كم دورة إعادة النشر",
        callback_data="admin:nsvc_avail_repostevery",
    )
    b.button(
        text=("🔥 إشعار فوري عند الرجوع: مفعّل" if restock_push else "🔥 إشعار فوري عند الرجوع: معطّل"),
        callback_data="admin:nsvc_avail_restockpush",
    )
    b.button(text="🚀 تحديث اللوحة الآن", callback_data="admin:nsvc_avail_post", style="success")
    b.button(text="🔝 إعادة نشرها كرسالة جديدة", callback_data="admin:nsvc_avail_repost", style="success")
    b.button(text="♻️ مسح حالة المقارنة", callback_data="admin:nsvc_avail_reset", style="danger")
    b.button(text="🧩 مركز الإضافات (تفعيل/إيقاف + النص)", callback_data="admin:features")
    b.button(text="🔙 رجوع", callback_data="admin:number_services")
    b.adjust(1)
    return b.as_markup()


def admin_nsvc_avail_services_kb(services) -> InlineKeyboardMarkup:
    """اختيار خدمة الأرقام التي ستُبنى لها اللوحة."""
    b = InlineKeyboardBuilder()
    for svc in services:
        b.button(
            text=f"{svc.emoji} {svc.name_ar}",
            callback_data=f"admin:nsvc_avail_svc:{svc.code}",
        )
    b.button(text="🔙 رجوع", callback_data="admin:nsvc_avail")
    b.adjust(1)
    return b.as_markup()


def admin_nsvc_detail_kb(service) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if service.is_active:
        b.button(text="⚪ تعطيل", callback_data=f"admin:nsvc_toggle:{service.id}")
    else:
        b.button(text="🟢 تفعيل", callback_data=f"admin:nsvc_toggle:{service.id}")
    b.button(
        text="⚙️ السيرفرات/المزودين التابعين",
        callback_data=f"admin:nsvc_servers:{service.id}",
        style="primary",
    )
    if getattr(service, "code", "") == "telegram":
        b.button(
            text="قسم ارقام تلجرام جاهزة (رفع ملف)",
            callback_data="admin:tg_ready",
            style="success",
        )
    b.button(text="📝 تعديل الاسم", callback_data=f"admin:nsvc_edit_name:{service.id}")
    b.button(text="🗑 حذف", callback_data=f"admin:nsvc_delete:{service.id}", style="danger")
    b.button(text="🔙 رجوع", callback_data="admin:number_services")
    b.adjust(1)
    return b.as_markup()


def admin_nsvc_servers_kb(service_id: int, servers, public_names=None) -> InlineKeyboardMarkup:
    """قائمة سيرفرات خدمة أرقام.

    الأدمن وحده يرى المزود الحقيقي بجانب الاسم المحايد الذي يراه المستخدم:
    ``🟢 سيرفر 2 · herosms`` — والنقطة الخضراء تعني «معلَّم كشغّال».
    """
    from services.number_server_service import public_server_name

    b = InlineKeyboardBuilder()
    public_names = public_names or {}
    for index, server in enumerate(servers, start=1):
        state = "🟢" if server.is_active else "⚪"
        working = " 🟢شغّال" if getattr(server, "is_working", False) else ""
        shown = public_names.get(server.id) or public_server_name(index)
        b.button(
            text=f"{state} {shown}{working} · {server.provider}",
            callback_data=f"admin:nsvc_server:{server.id}",
        )
    b.button(text="➕ إضافة سيرفر", callback_data=f"admin:nsvc_server_add:{service_id}", style="success")
    b.button(
        text="🤖 إنشاء سيرفر لكل مزود مضبوط تلقائياً",
        callback_data=f"admin:nsvc_server_auto:{service_id}",
        style="success",
    )
    b.button(
        text="🔢 إعادة ترقيم الأسماء (سيرفر 1، 2، 3...)",
        callback_data=f"admin:nsvc_server_renumber:{service_id}",
        style="primary",
    )
    b.button(text="🔙 رجوع", callback_data=f"admin:nsvc_view:{service_id}")
    b.adjust(1)
    return b.as_markup()


def admin_nsvc_server_detail_kb(service_id: int, server) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if getattr(server, "is_working", False):
        b.button(
            text="⚫ إزالة النقطة الخضراء (لا يعمل)",
            callback_data=f"admin:nsvc_server_working:{server.id}",
            style="danger",
        )
    else:
        b.button(
            text="🟢 علّمه كسيرفر يعمل الآن",
            callback_data=f"admin:nsvc_server_working:{server.id}",
            style="success",
        )
    if server.is_active:
        b.button(text="⚪ تعطيل السيرفر", callback_data=f"admin:nsvc_server_toggle:{server.id}")
    else:
        b.button(text="🟢 تفعيل السيرفر", callback_data=f"admin:nsvc_server_toggle:{server.id}")
    b.button(text="🔁 تغيير المزود", callback_data=f"admin:nsvc_server_edit_provider:{server.id}")
    b.button(text="💰 نسبة الربح", callback_data=f"admin:nsvc_server_edit_margin:{server.id}", style="primary")
    b.button(text="🗑 حذف السيرفر", callback_data=f"admin:nsvc_server_delete:{server.id}", style="danger")
    b.button(text="🔙 السيرفرات", callback_data=f"admin:nsvc_servers:{service_id}")
    b.adjust(1)
    return b.as_markup()


def admin_nsvc_choose_provider_kb(service_id: int, server_id: int | None = None, show_back: bool = True) -> InlineKeyboardMarkup:
    """اختيار المزود المرتبط بالسيرفر."""
    from database.models import ProviderName

    b = InlineKeyboardBuilder()
    for provider in ProviderName:
        b.button(text=f"{provider.value}", callback_data=f"admin:nsvc_server_provider:{server_id or 0}:{provider.value}")
    if show_back:
        back = f"admin:nsvc_server:{server_id}" if server_id else f"admin:nsvc_servers:{service_id}"
        b.button(text="🔙 رجوع", callback_data=back)
    b.adjust(2)
    return b.as_markup()


# ══════════════ السيرفرات العامة (كل الأقسام) ══════════════

SCOPE_LABELS = {
    "category": "📂 قسم رئيسي",
    "subcategory": "🗂 قسم فرعي",
    "number_service": "📞 خدمة أرقام",
    "global": "🌐 عام (كل الأقسام)",
}

# أقصى عدد أزرار لكل صفحة في اختيار الهدف — يبقيه أقل بكثير من حد تليجرام
# (100 زر كحد أقصى للوحة كاملة) لتفادي «reply markup is too long».
SSVC_TARGETS_PER_PAGE = 40

# أقصى عدد سيرفرات لكل صفحة في قائمة السيرفرات العامة (نفس السبب).
STORE_SERVERS_PER_PAGE = 30

# أقصى طول لنص الزر — الأسماء الطويلة جداً تضخّم الـ reply markup
# وقد تتجاوز حد تيليجرام حتى مع عدد أزرار صغير.
_MAX_BUTTON_TEXT = 48


# ══════════════ الدول ══════════════

ADMIN_COUNTRIES_PER_PAGE = 20

# وسم قصير لكل مزود — يظهر بقائمة الدول لتمييز صفوف المزودين عن بعضها
# (كل مزود له صفوفه الخاصة وقد تتكرر الدولة الواحدة).
COUNTRY_PROVIDER_TAGS: tuple[tuple[str, str], ...] = (
    ("fivesim_code", "5S"),
    ("herosms_code", "H"),
    ("sms_activate_code", "SA"),
    ("smshub_code", "SH"),
    ("smspool_code", "SP"),
    ("grizzly_code", "G"),
)


def country_provider_tags(country) -> str:
    """``[5S·H·G]`` حسب أكواد المزودين المضبوطة على الصف."""
    tags = [tag for field, tag in COUNTRY_PROVIDER_TAGS if getattr(country, field, None)]
    return f"[{ '·'.join(tags) }]" if tags else "[—]"


def admin_countries_kb(countries, page: int = 0) -> InlineKeyboardMarkup:
    """قائمة الدول مع ترقيم صفحات وأزرار الإدارة ظاهرة دائماً."""
    b = InlineKeyboardBuilder()

    total_pages = max(
        1, (len(countries) + ADMIN_COUNTRIES_PER_PAGE - 1) // ADMIN_COUNTRIES_PER_PAGE
    )
    page = max(0, min(page, total_pages - 1))

    start = page * ADMIN_COUNTRIES_PER_PAGE
    page_countries = countries[start : start + ADMIN_COUNTRIES_PER_PAGE]

    for c in page_countries:
        status_icon = "🟢" if c.is_active else "⚪"
        b.button(
            text=f"{status_icon} {c.flag} {c.name_ar} {country_provider_tags(c)}",
            callback_data=f"admin:country_view:{c.id}",
        )

    nav_buttons = []
    if page > 0:
        b.button(text="◀️ السابق", callback_data=f"admin:countries:{page - 1}")
        nav_buttons.append(1)
    if page < total_pages - 1:
        b.button(text="التالي ▶️", callback_data=f"admin:countries:{page + 1}")
        nav_buttons.append(1)

    b.button(text="➕ إضافة دولة جديدة", callback_data="admin:country_add", style="success")
    b.button(text="🔄 سحب دول من HeroSMS", callback_data="admin:country_sync_herosms")
    b.button(text="🟢 سحب دول من 5sim", callback_data="admin:country_sync_fivesim_menu")
    b.button(text="🐻 سحب دول من Grizzly", callback_data="admin:country_sync_grizzly_menu")
    b.button(text="🗑 حذف جميع الدول", callback_data="admin:country_delete_all_confirm", style="danger")
    b.button(text="📋 أكواد 5sim المرجعية", callback_data="admin:country_reference_list")
    b.button(text="🔙 رجوع", callback_data="admin:main")

    rows = [2] * ((len(page_countries) + 1) // 2)
    if nav_buttons:
        rows.append(len(nav_buttons))
    rows.extend([2, 2, 2, 1])
    b.adjust(*rows)
    return b.as_markup()


def fivesim_sync_menu_kb() -> InlineKeyboardMarkup:
    """قائمة اختيار خدمات السحب من 5sim."""
    b = InlineKeyboardBuilder()
    b.button(
        text="💬✈️ واتساب + تيليجرام (موصى به)",
        callback_data="admin:country_sync_fivesim:whatsapp,telegram",
    )
    b.button(text="💬 واتساب فقط", callback_data="admin:country_sync_fivesim:whatsapp")
    b.button(text="✈️ تيليجرام فقط", callback_data="admin:country_sync_fivesim:telegram")
    b.button(
        text="⚪ سحب بدون تفعيل (كلاهما)",
        callback_data="admin:country_sync_fivesim_idle:whatsapp,telegram",
    )
    b.button(text="🔙 رجوع", callback_data="admin:countries")
    b.adjust(1, 2, 1, 1)
    return b.as_markup()


def grizzly_sync_menu_kb() -> InlineKeyboardMarkup:
    """قائمة اختيار خدمات السحب من GrizzlySMS."""
    b = InlineKeyboardBuilder()
    b.button(
        text="💬✈️ واتساب + تيليجرام (موصى به)",
        callback_data="admin:country_sync_grizzly:whatsapp,telegram",
    )
    b.button(text="💬 واتساب فقط", callback_data="admin:country_sync_grizzly:whatsapp")
    b.button(text="✈️ تيليجرام فقط", callback_data="admin:country_sync_grizzly:telegram")
    b.button(
        text="⚪ سحب بدون تفعيل (كلاهما)",
        callback_data="admin:country_sync_grizzly_idle:whatsapp,telegram",
    )
    b.button(text="🔙 رجوع", callback_data="admin:countries")
    b.adjust(1, 2, 1, 1)
    return b.as_markup()


def herosms_sync_menu_kb() -> InlineKeyboardMarkup:
    """قائمة اختيار خدمات السحب من HeroSMS."""
    b = InlineKeyboardBuilder()
    b.button(
        text="💬✈️ واتساب + تيليجرام (موصى به)",
        callback_data="admin:country_sync:whatsapp,telegram",
    )
    b.button(text="💬 واتساب فقط", callback_data="admin:country_sync:whatsapp")
    b.button(text="✈️ تيليجرام فقط", callback_data="admin:country_sync:telegram")
    b.button(
        text="⚪ سحب بدون تفعيل (كلاهما)",
        callback_data="admin:country_sync_idle:whatsapp,telegram",
    )
    b.button(
        text="🗑 تصفير الدول المسحوبة وإعادة السحب",
        callback_data="admin:country_reset", style="danger",
    )
    b.button(text="🔙 رجوع", callback_data="admin:countries")
    b.adjust(1, 2, 1, 1, 1)
    return b.as_markup()


def country_reset_confirm_kb() -> InlineKeyboardMarkup:
    """تأكيد تصفير الدول المسحوبة تلقائياً من HeroSMS."""
    b = InlineKeyboardBuilder()
    b.button(
        text="🗑 نعم، احذف جميع الدول",
        callback_data="admin:country_delete_all_execute", style="danger",
    )
    b.button(text="❌ تراجع", callback_data="admin:countries")
    b.adjust(1)
    return b.as_markup()


def admin_country_detail_kb(country) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if country.is_active:
        b.button(text="⚪ تعطيل", callback_data=f"admin:country_toggle:{country.id}")
    else:
        b.button(text="🟢 تفعيل", callback_data=f"admin:country_toggle:{country.id}")
    b.button(text="🗑 حذف", callback_data=f"admin:country_delete:{country.id}", style="danger")
    b.button(text="🔙 رجوع", callback_data="admin:countries")
    b.adjust(1)
    return b.as_markup()


# ══════════════ الأسعار ══════════════


def admin_pricing_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📈 تعديل نسبة الربح العامة", callback_data="admin:set_margin", style="primary")
    b.button(text="🔙 رجوع", callback_data="admin:main")
    b.adjust(1)
    return b.as_markup()


# ══════════════ الإعدادات ══════════════


def admin_payment_settings_kb(settings_values: dict[str, bool]) -> InlineKeyboardMarkup:
    """أزرار تشغيل وإيقاف طرق الدفع."""
    labels = {
        "payment_shamcash_manual_enabled": "💵 شام كاش يدوي",
        "payment_stars_enabled": "⭐ نجوم تيليجرام",
        "payment_usdt_manual_enabled": "₮ USDT يدوي",
        "payment_shamcash_auto_enabled": "💳 شام كاش تلقائي",
        "payment_usdt_auto_enabled": "₮ USDT تلقائي",
        "payment_other_enabled": "📞 طرق أخرى",
        "withdraw_shamcash_syp_enabled": "🇸🇾 سحب شام كاش بالليرة",
    }
    b = InlineKeyboardBuilder()
    for key, label in labels.items():
        state = "🟢 مفعّل" if settings_values.get(key, False) else "⚪ معطّل"
        b.button(
            text=f"{state} {label}",
            callback_data=f"admin:payment_toggle:{key}", style="primary",
        )
    b.button(text="🔙 الإعدادات", callback_data="admin:settings")
    b.adjust(1)
    return b.as_markup()


def admin_settings_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💱 أسعار الصرف اليومية", callback_data="admin:rates", style="primary")
    b.button(text="🛠 يوزر الدعم", callback_data="admin:set_support")
    b.button(text="💳 طريقة الدفع", callback_data="admin:set_payment", style="primary")
    b.button(text="🎛 تفعيل طرق الدفع", callback_data="admin:payment_settings", style="primary")
    b.button(text="💳 عناوين المحافظ", callback_data="admin:wallets", style="primary")
    b.button(text="🚨 حد التحويل الكبير", callback_data="admin:set_large_tx")
    b.button(text="⏳ مهلة انتظار الكود", callback_data="admin:set_order_timeout", style="primary")
    b.button(text="📝 رسالة الترحيب", callback_data="admin:set_welcome")
    b.button(text="💰 نسبة الكاشباك", callback_data="admin:set_cashback")
    b.button(text="💎 نسبة الإحالة", callback_data="admin:set_referral_percent", style="primary")
    b.button(text="💱 عمولة تحويل الرصيد", callback_data="admin:set_transfer_fee", style="primary")
    b.button(text="💱 أدنى تحويل رصيد", callback_data="admin:set_transfer_min", style="primary")
    b.button(text="⏱ Rate Limit", callback_data="admin:set_rate_limit")
    b.button(text="📢 قناة الإشعارات العامة", callback_data="admin:set_public_channel")
    b.button(text="💾 قناة البكاب", callback_data="admin:set_backup_channel")
    b.button(text="🔙 رجوع", callback_data="admin:main")
    b.adjust(1, 2, 2, 2, 2, 2, 2, 1)
    return b.as_markup()


def admin_rates_kb() -> InlineKeyboardMarkup:
    """أزرار تعديل أسعار صرف العرض اليومية."""
    b = InlineKeyboardBuilder()
    b.button(text="🇸🇾 ليرة سورية", callback_data="admin:rate_set:usd_to_syp_rate")
    b.button(text="🇪🇺 يورو", callback_data="admin:rate_set:usd_to_eur_rate")
    b.button(text="🇪🇬 جنيه مصري", callback_data="admin:rate_set:usd_to_egp_rate")
    b.button(text="🔙 رجوع", callback_data="admin:settings")
    b.adjust(3, 1)
    return b.as_markup()


# ══════════════ الإيداعات ══════════════


def deposit_decision_kb(deposit_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ قبول", callback_data=f"deposit_accept:{deposit_id}", style="primary")
    b.button(text="❌ رفض", callback_data=f"deposit_reject:{deposit_id}", style="danger")
    b.adjust(2)
    return b.as_markup()


# ══════════════ إدارة مستخدم ══════════════


def user_manage_kb(user_id: int, is_banned: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ إضافة رصيد", callback_data=f"admin:user_add_balance:{user_id}", style="primary")
    b.button(text="➖ خصم رصيد", callback_data=f"admin:user_deduct_balance:{user_id}", style="primary")
    b.button(text="📋 سجل المعاملات", callback_data=f"admin:user_transactions:{user_id}")
    b.button(text="📩 إرسال رسالة", callback_data=f"admin:user_send_msg:{user_id}")
    if is_banned:
        b.button(text="✅ فك الحظر", callback_data=f"admin:user_unban:{user_id}", style="danger")
    else:
        b.button(text="🚫 حظر", callback_data=f"admin:user_ban:{user_id}", style="danger")
    b.button(text="🔙 رجوع", callback_data="admin:users")
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


# ══════════════ القنوات ══════════════


def admin_channels_kb(channels) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ch in channels:
        b.button(
            text=f"❌ حذف: {ch.title or ch.chat_id}",
            callback_data=f"admin:channel_del:{ch.id}", style="danger",
        )
    b.button(text="➕ إضافة قناة", callback_data="admin:channel_add", style="success")
    b.button(text="🔙 رجوع", callback_data="admin:main")
    b.adjust(1)
    return b.as_markup()

# ══════════════ عناوين محافظ الشحن ══════════════


def admin_wallets_kb(addresses: dict[str, str]) -> InlineKeyboardMarkup:
    """إدارة عناوين المحافظ اليدوية (تُحفظ بقاعدة البيانات وتتفوق على .env)."""
    labels = {
        "shamcash_manual_address": "💠 شام كاش",
        "usdt_trc20_address": "💵 USDT-TRC20",
        "usdt_erc20_address": "💵 USDT-ERC20",
        "usdt_bep20_address": "💵 USDT-BEP20",
    }
    b = InlineKeyboardBuilder()
    for key, label in labels.items():
        value = (addresses.get(key) or "").strip()
        shown = value if value else "— غير مضبوط —"
        if value and len(value) > 26:
            shown = f"{value[:10]}…{value[-6:]}"
        b.button(text=f"{label}: {shown}", callback_data=f"admin:wallet_edit:{key}")
    b.button(text="🔙 الإعدادات", callback_data="admin:settings")
    b.adjust(1)
    return b.as_markup()
