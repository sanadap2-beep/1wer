"""
كل حالات FSM الخاصة بالبوت.
"""

from aiogram.fsm.state import State, StatesGroup


# ══════════════ المستخدم ══════════════


class DepositStates(StatesGroup):
    waiting_amount = State()
    waiting_proof_photo = State()
    waiting_tx_number = State()


class SupportTicketStates(StatesGroup):
    waiting_message = State()


class ProductGiftStates(StatesGroup):
    waiting_recipient = State()
    confirming_purchase = State()


class AiSupportStates(StatesGroup):
    waiting_question = State()


class NumberBulkStates(StatesGroup):
    waiting_quantity = State()


class AdminTicketStates(StatesGroup):
    waiting_reply = State()


class ShamCashManualStates(StatesGroup):
    waiting_amount = State()
    waiting_proof_photo = State()
    waiting_tx_number = State()


# ══════════════ الشحن اليدوي - USDT ══════════════


class UsdtManualStates(StatesGroup):
    waiting_network = State()
    waiting_amount = State()
    waiting_proof_photo = State()
    waiting_tx_hash = State()


# ══════════════ الشحن التلقائي - شام كاش ══════════════


class ShamCashAutoStates(StatesGroup):
    waiting_currency = State()
    waiting_amount = State()
    waiting_transaction_ref = State()


# ══════════════ الشحن التلقائي - USDT ══════════════


class UsdtAutoStates(StatesGroup):
    waiting_amount = State()


# ══════════════ التحويل بين المستخدمين ══════════════


class ReferralGuardStates(StatesGroup):
    """حالة التحقق البشري لمن دخل عبر رابط إحالة."""
    waiting_answer = State()


# ══════════════ الأدمن - عام ══════════════


class AdminBroadcastStates(StatesGroup):
    waiting_content = State()


class AdminChannelStates(StatesGroup):
    waiting_channel_id = State()


class AdminUserSearchStates(StatesGroup):
    waiting_user_id = State()
    waiting_balance_amount = State()


class AdminPricingStates(StatesGroup):
    waiting_exchange_rate = State()
    waiting_margin_value = State()


class AdminSupportStates(StatesGroup):
    waiting_support_username = State()


class AdminPaymentStates(StatesGroup):
    waiting_payment_text = State()


class AdminWalletStates(StatesGroup):
    waiting_value = State()


class AdminLargeTxStates(StatesGroup):
    waiting_threshold = State()


class AdminOrderTimeoutStates(StatesGroup):
    waiting_minutes = State()


class AdminCountryStates(StatesGroup):
    waiting_code = State()
    waiting_name_ar = State()
    waiting_flag = State()
    waiting_fivesim_code = State()
    waiting_herosms_code = State()
    waiting_sms_activate_code = State()
    waiting_smshub_code = State()
    waiting_smspool_code = State()
    waiting_grizzly_code = State()


# ══════════════ الأدمن - الأقسام الرئيسية ══════════════


class AdminCategoryStates(StatesGroup):
    waiting_name = State()
    waiting_emoji = State()
    waiting_type = State()
    waiting_sort_order = State()
    waiting_edit_field = State()
    waiting_edit_value = State()


# ══════════════ الأدمن - الأقسام الفرعية ══════════════


class AdminSubCategoryStates(StatesGroup):
    waiting_name = State()
    waiting_emoji = State()
    waiting_description = State()
    waiting_image = State()
    waiting_sort_order = State()
    waiting_edit_field = State()
    waiting_edit_value = State()


# ══════════════ الأدمن - المنتجات (Wizard) ══════════════


class AdminProductStates(StatesGroup):
    waiting_name = State()
    waiting_description = State()
    waiting_image = State()
    waiting_price = State()
    waiting_cost_price = State()
    waiting_provider_service_id = State()
    waiting_min_quantity = State()
    waiting_max_quantity = State()
    waiting_estimated_time = State()
    waiting_sort_order = State()
    waiting_pricing_type = State()
    waiting_profit_margin = State()
    waiting_search_query = State()
    waiting_edit_field = State()
    waiting_edit_value = State()
    confirming_price_change = State()
    confirming_delete = State()


class AdminApiProviderStates(StatesGroup):
    waiting_protocol_type = State()
    waiting_name = State()
    waiting_type = State()
    waiting_api_url = State()
    waiting_api_key = State()
    waiting_currency = State()
    waiting_rate_to_usd = State()
    waiting_priority = State()
    waiting_low_balance_threshold = State()
    waiting_custom_config = State()
    waiting_custom_wizard_value = State()
    waiting_edit_field = State()
    waiting_edit_value = State()
    confirming_sync = State()


class AdminStarsStates(StatesGroup):
    waiting_stars_amount = State()
    waiting_usd_amount = State()
    waiting_label = State()
    waiting_edit_field = State()
    waiting_edit_value = State()


class AdminNumberServiceStates(StatesGroup):
    waiting_code = State()
    waiting_name = State()
    waiting_emoji = State()
    waiting_fivesim_code = State()
    waiting_herosms_code = State()
    waiting_sms_activate_code = State()
    waiting_smshub_code = State()
    waiting_smspool_code = State()
    waiting_grizzly_code = State()
    waiting_edit_field = State()
    waiting_edit_value = State()
    waiting_availability_channel = State()
    waiting_availability_topn = State()
    waiting_availability_watchlist = State()
    waiting_availability_repost_every = State()
    # سيرفرات/مزودين الخدمة
    waiting_server_name = State()
    waiting_server_emoji = State()
    waiting_server_provider = State()
    waiting_server_edit_value = State()


class AdminMaintenanceStates(StatesGroup):
    waiting_message = State()


class AdminWelcomeStates(StatesGroup):
    waiting_message = State()


class AdminSettingsStates(StatesGroup):
    waiting_value = State()


class AdminMultiAdminStates(StatesGroup):
    waiting_admin_id = State()


class AdminSendMessageStates(StatesGroup):
    waiting_user_id = State()
    waiting_message = State()


class AdminFeatureStates(StatesGroup):
    waiting_search = State()
    waiting_option_value = State()


class AdminBulkDiscountStates(StatesGroup):
    waiting_tiers = State()


class AdminMainButtonStates(StatesGroup):
    waiting_label = State()
    waiting_action = State()
    choosing_target_type = State()
    choosing_category = State()
    choosing_subcategory = State()
    choosing_product = State()


class AdminNotificationStates(StatesGroup):
    waiting_template_title = State()
    waiting_template_body = State()


class AdminMarginStates(StatesGroup):
    """ضبط هوامش الربح: قسم / قسم فرعي / منتج."""

    waiting_category_margin = State()
    waiting_sub_margin = State()
    waiting_product_margin = State()


class MobileCreditDepositStates(StatesGroup):
    """الشحن برصيد الجوال: رقم الجوال ثم المبلغ ثم صورة الإثبات."""

    waiting_provider_number = State()
    waiting_amount = State()
    waiting_proof_photo = State()


class AdminTgReadyStates(StatesGroup):
    """رفع ملف الجلسات الجاهزة: نسبة الربح ثم التكلفة ثم الملف."""

    waiting_margin = State()
    waiting_cost = State()
    waiting_file = State()
    waiting_price = State()
    waiting_price_country = State()


class QuickSetupStates(StatesGroup):
    """معالج الإعداد السريع للزبون: نسبة الربح فقط."""

    waiting_margin = State()


class AdminStoreStates(StatesGroup):
    """إدارة المتجر: المزودون والأقسام والنشر والهوامش."""

    waiting_provider_name = State()
    waiting_provider_url = State()
    waiting_provider_key = State()
    waiting_provider_key_edit = State()
    waiting_search = State()
    waiting_margin = State()
    waiting_category_name = State()
    waiting_sub_name = State()
    waiting_product_name = State()


class StoreStates(StatesGroup):
    """شراء الزبون من المتجر: الهدف ثم الكمية."""

    waiting_target = State()
    waiting_quantity = State()
    waiting_coupon = State()


class StoreFindStates(StatesGroup):
    """بحث «ما لقيت لعبتك»: الاستعلام ثم الهدف ثم الكمية."""

    waiting_query = State()
    waiting_target = State()
    waiting_quantity = State()


class AdminStoreSetupStates(StatesGroup):
    """معالج تجهيز قسم متجر: نسبة الربح ثم التنفيذ."""

    waiting_margin = State()


class AdminCouponStates(StatesGroup):
    """إنشاء كوبون/حملة: الكود ثم القيمة ثم الحدود."""

    waiting_code = State()
    waiting_value = State()
    waiting_limits = State()


class AdminOfferStates(StatesGroup):
    """عرض مؤقت: الخصم ثم المدة."""

    waiting_discount = State()
    waiting_hours = State()


class AdminTraderStates(StatesGroup):
    """رتب التجار: تعديل نسبة ثم حفظ."""

    waiting_discount = State()
