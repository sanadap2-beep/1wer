"""Compact top-level menu for the bot.

The store and extras pages own their dynamic catalog and feature shortcuts;
the first screen contains only the essential actions and two entry points.
All visible static labels use the existing Arabic/English translation service.
"""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import NumberService, Category
from services.i18n_service import I18nService
from services.main_button_service import MainMenuButton


def build_main_menu(
    number_services=None,
    categories=None,
    balance_usd: str = "0.00",
    language: str = "ar",
    balance_display: str | None = None,
    show_marketplace: bool = False,
    show_tasks: bool = False,
    show_points: bool = False,
    dynamic_buttons=None,
    show_agent: bool = False,
    agent_percent: str = "10",
    completed_orders_count: int | None = None,
    show_ai: bool = False,
    show_whatsapp: bool = False,
) -> InlineKeyboardMarkup:
    """نسخة الأرقام فقط: شراء + جلسات + حساب + شحن + دعم."""
    t = lambda key, **kw: I18nService.t(key, language, **kw)  # noqa: E731
    balance_text = balance_display if balance_display is not None else f"${balance_usd}"
    b = InlineKeyboardBuilder()

    # الأرقام أولاً — قلب البوت
    b.button(text="📱 شراء أرقام", callback_data="num_hub", style="success")
    b.button(text="📦 جلسات تيليجرام الجاهزة", callback_data="tgready:list", style="success")
    b.button(text="🛍 المتجر (رشق/ألعاب/برامج/رصيد)", callback_data="store:home", style="success")
    b.button(text=t("menu_account_with_balance", balance=balance_text), callback_data="menu:account", style="primary")
    b.button(text=t("menu_deposit"), callback_data="menu:deposit", style="primary")
    b.button(text=t("menu_referral"), callback_data="menu:referral", style="primary")
    b.button(text=t("menu_support"), callback_data="menu:support")
    b.button(text="ℹ️ معلومات البوت", callback_data="info:home")
    b.button(text=t("menu_terms"), callback_data="info:terms", style="danger")

    b.adjust(2)
    return b.as_markup()



def deposit_menu_kb(
    shamcash_manual_enabled: bool = True,
    stars_enabled: bool = True,
    usdt_manual_enabled: bool = True,
    shamcash_auto_enabled: bool = True,
    usdt_auto_enabled: bool = True,
    mobile_credit_enabled: bool = False,
    other_enabled: bool = True,
    language: str = "ar",
) -> InlineKeyboardMarkup:
    """
    قائمة طرق شحن الرصيد (حتى 7 طرق).
    كل طريقة تظهر فقط إذا كانت مفعلة من لوحة الأدمن.
    """
    t = lambda key: I18nService.t(key, language)  # noqa: E731
    b = InlineKeyboardBuilder()

    if shamcash_manual_enabled:
        b.button(
            text=t("deposit_method_shamcash_manual"),
            callback_data="deposit:shamcash_manual", style="primary",
        )

    if stars_enabled:
        b.button(
            text=t("deposit_method_stars"),
            callback_data="deposit:stars", style="primary",
        )

    if shamcash_auto_enabled:
        b.button(
            text=t("deposit_method_shamcash_auto"),
            callback_data="deposit:shamcash_auto", style="primary",
        )

    if usdt_auto_enabled:
        b.button(
            text=t("deposit_method_usdt_auto"),
            callback_data="deposit:usdt_auto", style="primary",
        )

    if usdt_manual_enabled:
        b.button(
            text=t("deposit_method_usdt_manual"),
            callback_data="deposit:usdt_manual", style="primary",
        )

    if mobile_credit_enabled:
        b.button(
            text="📲 رصيد جوال",
            callback_data="deposit:mobile_credit", style="primary",
        )

    if other_enabled:
        b.button(
            text=t("deposit_method_other"),
            callback_data="deposit:other", style="primary",
        )

    b.button(
        text=t("back_to_main"),
        callback_data="back_to_main",
    )

    b.adjust(2, 2, 2, 2, 1)
    return b.as_markup()


def stars_packages_kb(
    packages: list,
    language: str = "ar",
) -> InlineKeyboardMarkup:
    """قائمة باقات النجوم المتاحة."""
    t = lambda key: I18nService.t(key, language)  # noqa: E731
    b = InlineKeyboardBuilder()
    for pkg in packages:
        b.button(
            text=f"{pkg.label} = ${pkg.usd_amount}",
            callback_data=f"stars_buy:{pkg.id}", style="primary",
        )
    b.button(
        text=t("back"),
        callback_data="menu:deposit", style="primary",
    )
    b.adjust(2)
    return b.as_markup()


def insufficient_balance_kb(language: str = "ar") -> InlineKeyboardMarkup:
    """زر شحن الرصيد عند عدم كفاية الرصيد."""
    t = lambda key: I18nService.t(key, language)  # noqa: E731
    b = InlineKeyboardBuilder()
    b.button(
        text=t("topup_now"),
        callback_data="menu:deposit", style="primary",
    )
    b.button(
        text=t("back_to_menu"),
        callback_data="back_to_main",
    )
    b.adjust(1)
    return b.as_markup()


def confirm_large_order_kb(
    confirm_data: str,
    language: str = "ar",
) -> InlineKeyboardMarkup:
    """تأكيد الطلبات الكبيرة."""
    t = lambda key: I18nService.t(key, language)  # noqa: E731
    b = InlineKeyboardBuilder()
    b.button(
        text=t("yes_confirm"),
        callback_data=confirm_data,
    )
    b.button(
        text=t("cancel"),
        callback_data="back_to_main",
    )
    b.adjust(2)
    return b.as_markup()


def back_to_main_kb(language: str = "ar") -> InlineKeyboardMarkup:
    """زر رجوع للقائمة الرئيسية فقط."""
    b = InlineKeyboardBuilder()
    b.button(
        text=I18nService.t("back_to_main", language),
        callback_data="back_to_main",
    )
    return b.as_markup()