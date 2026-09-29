"""
دليل وشروحات البوت للمستخدمين ومعلومات المطور.
نسخة الأرقام فقط: شرح الأرقام + الجلسات + الشحن + الحساب + الإحالة + الدعم.
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

router = Router(name="bot_info")

DEVELOPER_NAME = "أب سند الفلسطيني"
DEVELOPER_USERNAME = "@I8_ZU"


def _info_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 شرح شراء الأرقام", callback_data="info:numbers", style="success")],
        [InlineKeyboardButton(text="📦 شرح الجلسات الجاهزة", callback_data="info:sessions", style="success")],
        [InlineKeyboardButton(text="🛍 شرح المتجر (رشق/ألعاب/برامج/رصيد)", callback_data="info:store", style="success")],
        [InlineKeyboardButton(text="💳 كيف تشحن رصيدك", callback_data="info:deposit", style="primary")],
        [InlineKeyboardButton(text="👤 شرح حسابي", callback_data="info:account", style="primary")],
        [InlineKeyboardButton(text="🎁 شرح الإحالة", callback_data="info:referral", style="primary")],
        [InlineKeyboardButton(text="🆘 الدعم الفني", callback_data="info:support")],
        [InlineKeyboardButton(text="📢 الاشتراك الإجباري", callback_data="info:subscription")],
        [InlineKeyboardButton(text="🟢 طلبات أنجزناها", callback_data="info:stats", style="primary")],
        [InlineKeyboardButton(text="🔺 شروط الاستخدام", callback_data="info:terms", style="danger")],
        [InlineKeyboardButton(text="👨‍💻 المطور وحقوق البوت", callback_data="info:developer", style="primary")],
        [InlineKeyboardButton(text="⬅️ رجوع للقائمة الرئيسية", callback_data="back_to_main")],
    ])


async def _safe_edit(callback: CallbackQuery, text: str):
    try:
        await callback.message.edit_text(text, reply_markup=_info_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=_info_kb())
    await callback.answer()


@router.callback_query(F.data == "info:home")
async def bot_info_home(callback: CallbackQuery):
    await _safe_edit(
        callback,
        "ℹ️ <b>معلومات البوت</b>\n\n"
        "أهلاً فيك! هذا بوت متخصص ببيع <b>أرقام التفعيل (OTP)</b> "
        "للواتساب وتيليجرام وباقي التطبيقات، بالإضافة لقسم "
        "<b>جلسات تيليجرام الجاهزة</b>.\n\n"
        "💰 <b>العملة الأساسية:</b> الدولار الأمريكي ($)، "
        "ويظهر لك ما يعادلها بعملتك حسب سعر الصرف اليومي.\n\n"
        "🛡 <b>الضمان:</b> إذا لم يصل الكود خلال المهلة يرجع رصيدك تلقائياً بدون ما تكلم حدا.\n\n"
        "📚 <b>اختار من الأزرار تحت لشرح مفصل لكل قسم وطريقة استخدامه.</b>\n\n"
        f"👨‍💻 <b>تطوير:</b> المبرمج {DEVELOPER_NAME}\n"
        f"📩 <b>للتواصل:</b> {DEVELOPER_USERNAME}",
    )


@router.callback_query(F.data == "info:stats")
async def public_stats(callback: CallbackQuery, session):
    from sqlalchemy import func, select
    from database.models import NumberOrder, OrderStatus, UnifiedOrder, UnifiedOrderStatus

    number_count = (
        await session.execute(
            select(func.count(NumberOrder.id)).where(NumberOrder.status == OrderStatus.COMPLETED)
        )
    ).scalar_one()
    unified_count = (
        await session.execute(
            select(func.count(UnifiedOrder.id)).where(UnifiedOrder.status == UnifiedOrderStatus.COMPLETED)
        )
    ).scalar_one()
    total = int(number_count or 0) + int(unified_count or 0)
    await _safe_edit(
        callback,
        "🟢 <b>طلبات أنجزناها</b>\n\n"
        f"أنجزنا حتى الآن <b>{total}</b> طلب بنجاح داخل البوت.\n\n"
        "• الأرقام: الكود وصلك وتم التفعيل.\n"
        "• الجلسات: الملف استلمته ودخلت الحساب.\n\n"
        "أي طلب يفشل يرجع رصيده تلقائياً.",
    )


@router.callback_query(F.data == "info:terms")
async def terms(callback: CallbackQuery):
    await _safe_edit(
        callback,
        "🔺 <b>شروط الاستخدام</b>\n\n"
        "1) استخدم الأرقام والجلسات بشكل قانوني ومسؤول.\n"
        "2) أسعار الأرقام متغيرة حسب المزود، والسعر النهائي هو الظاهر قبل زر التأكيد.\n"
        "3) إذا لم يصل الكود خلال المهلة (5 دقائق عادة) يرجع رصيدك تلقائياً.\n"
        "4) الجلسات الجاهزة تسليمها فوري بملف ZIP، تأكد تحفظ الـ 2FA الخاصة فيك.\n"
        "5) ممنوع الاحتيال أو إساءة استخدام روابط الإحالة.\n"
        "6) الشحن اليدوي يحتاج إثبات صحيح، وأي إثبات مزور يعرض حسابك للحظر.\n\n"
        "ضغطك زر الشراء يعني موافقتك على هالشروط.",
    )


@router.callback_query(F.data == "info:numbers")
async def numbers_info(callback: CallbackQuery):
    await _safe_edit(
        callback,
        "📱 <b>شرح شراء الأرقام — خطوة خطوة</b>\n\n"
        "1) من القائمة الرئيسية اضغط <b>📱 شراء أرقام</b>.\n"
        "2) اختار <b>الخدمة</b> (واتساب / تيليجرام / ...).\n"
        "3) اختار <b>السيرفر</b> (سيرفر 1، سيرفر 2... — الأرخص يظهر أولاً).\n"
        "4) اختار <b>الدولة</b> — الأسعار مرتبة من الأرخص 🟢.\n"
        "5) راح يطلع لك <b>السعر النهائي + مدة الانتظار</b>، اضغط تأكيد الشراء.\n"
        "6) البوت يعطيك الرقم فوراً وينتظر الكود تلقائياً.\n\n"
        "✅ <b>وصل الكود؟</b> انسخه وفعّل حسابك.\n"
        "↩️ <b>ما وصل؟</b> انتظر انتهاء المهلة ويرجع رصيدك لحاله.\n"
        "❌ <b>زر إلغاء:</b> إذا ما بدأ المزود بتجهيز الرقم فيك تلغي وتسترد رصيدك.\n\n"
        "📦 <b>الشراء بالجملة:</b> إذا مفعّلة من الإدارة، فيك تشتري عدة أرقام بنفس الدولة والخدمة بضغطة وحدة، وأي رقم يفشل يرجع سعره تلقائياً.",
    )


@router.callback_query(F.data == "info:sessions")
async def sessions_info(callback: CallbackQuery):
    await _safe_edit(
        callback,
        "📦 <b>شرح جلسات تيليجرام الجاهزة</b>\n\n"
        "الجلسة = حساب تيليجرام جاهز بملفات دخول، تستلمها وتدخل بدون رقم.\n\n"
        "1) اضغط <b>📦 جلسات تيليجرام الجاهزة</b> من القائمة.\n"
        "2) اختار الدولة / الفئة المتاحة وشوف السعر.\n"
        "3) أكّد الشراء — يخصم من رصيدك.\n"
        "4) يوصلك فوراً ملف <b>ZIP</b> فيه:\n"
        "   • ملف session\n"
        "   • مجلد tdata\n"
        "   • كود التحقق 2FA إذا موجود\n"
        "5) حمّل الملف وافتحه بتيليجرام ديسكتوب / Telethon.\n\n"
        "📩 <b>زر طلب الكود التلقائي:</b> إذا الجلسة تحتاج كود دخول جديد، اضغطه والبوت يجيبه لك.\n"
        "🔄 <b>إعادة إرسال الملف:</b> إذا ضاع الملف من محادثتك، فيك تطلبه من صفحة طلباتك.\n\n"
        "⚠️ مهم: غيّر الـ 2FA وحط إيميلك الخاص فور الاستلام.",
    )


@router.callback_query(F.data == "info:store")
async def store_info(callback: CallbackQuery):
    await _safe_edit(
        callback,
        "🛍 <b>شرح المتجر — خطوة خطوة</b>\n\n"
        "المتجر فيه 4 أقسام:\n"
        "• 📈 <b>الرشق:</b> متابعين/لايكات/مشاهدات لانستا وتيك توك ويوتيوب وغيرها — أرسل رابط حسابك أو منشورك.\n"
        "• 🎮 <b>شحن الألعاب:</b> شدات ببجي وجواهر فري فاير وغيرها — أرسل Player ID فقط.\n"
        "• 📱 <b>شحن البرامج:</b> خدمات التطبيقات حسب المتاح.\n"
        "• 💳 <b>الرصيد:</b> سيريتل وMTN بفئات ثابتة — اختار الفئة وأرسل الرقم (يبدأ بـ 09).\n\n"
        "1) ادخل 🛍 المتجر واختار القسم ثم الفرع ثم المنتج.\n"
        "2) أدخل المطلوب (رابط / Player ID / رقم هاتف).\n"
        "3) اختار الكمية أو الفئة وشوف السعر النهائي.\n"
        "4) أكّد — يُخصم من رصيدك ويتنفذ الطلب تلقائياً.\n\n"
        "🧺 <b>السلة:</b> أضف عدة منتجات وأتممها بدفعة واحدة.\n"
        "🎟 <b>الكوبون:</b> عندك كود خصم؟ اضغط «عندي كوبون» بشاشة التأكيد.\n"
        "🔔 <b>نبهني:</b> من صفحة المنتج فعّل تنبيه تغير السعر.\n\n"
        "✅ عند الاكتمال يوصلك إشعار (وقيّم تجربتك بالنجوم ⭐).\n"
        "↩️ إذا فشل الطلب لدى المزود يرجع رصيدك تلقائياً.",
    )


@router.callback_query(F.data == "info:deposit")
async def deposit_info(callback: CallbackQuery):
    await _safe_edit(
        callback,
        "💳 <b>كيف تشحن رصيدك؟ — شرح كل الطرق</b>\n\n"
        "1) من القائمة اضغط <b>💰 شحن الرصيد</b>.\n"
        "2) اختار طريقة الدفع المتاحة:\n"
        "   • 💵 <b>شام كاش يدوي:</b> حوّل للمحفظة الظاهرة، ثم أرسل صورة الإثبات + رقم العملية.\n"
        "   • ⚡ <b>شام كاش تلقائي:</b> يطلع لك عنوان دفع، حوّل عليه واضغط تحقق.\n"
        "   • 💲 <b>USDT يدوي (TRC20/ERC20/BEP20):</b> حوّل للعنوان الصحيح حسب الشبكة، وأرسل hash العملية.\n"
        "   • ⚡ <b>USDT تلقائي:</b> فاتورة تنعمل لك، ادفعها خلال 30 دقيقة.\n"
        "   • ⭐ <b>نجوم تيليجرام:</b> اختار باقة النجوم وادفع بالنجوم مباشرة.\n"
        "3) أدخل <b>المبلغ بالدولار</b> (انتبه للحد الأدنى المكتوب تحت كل طريقة).\n"
        "4) اليدوي يراجعه الأدمن ويضيف رصيدك، والتلقائي ينضاف فور تأكيد الدفع.\n\n"
        "📩 يوصلك إشعار بكل خطوة: استلام الطلب / القبول / الرفض مع السبب.",
    )


@router.callback_query(F.data == "info:account")
async def account_info(callback: CallbackQuery):
    await _safe_edit(
        callback,
        "👤 <b>شرح صفحة حسابي</b>\n\n"
        "من زر <b>👤 حسابي</b> تشوف:\n\n"
        "• 💰 <b>رصيدك الحالي</b> بالدولار + ما يعادله بعملتك.\n"
        "• 🛒 <b>إجمالي مشترياتك</b> وعدد طلباتك المنفذة.\n"
        "• 🎁 <b>الكاشباك والنقاط</b> إذا مفعّلة من الإدارة.\n"
        "• 👥 <b>عدد إحالاتك</b>.\n\n"
        "الأزرار داخل حسابي:\n"
        "• 📱 طلبات الأرقام: كل أرقامك وأكوادها وحالتها.\n"
        "• 🛒 طلبات أخرى: طلبات الجلسات.\n"
        "• 📊 سجل المعاملات: كل شحن وشراء واسترجاع.\n"
        "• 💱 تحويل رصيد: أرسل رصيداً لمستخدم آخر بآيديه الرقمي.\n"
        "• 🔔 تنبيهاتي: تنبيهات انخفاض الأسعار.\n"
        "• 💱 العملة / 🌐 اللغة: تغيير العرض واللغة (عربي / English).",
    )


@router.callback_query(F.data == "info:referral")
async def referral_info(callback: CallbackQuery):
    await _safe_edit(
        callback,
        "🎁 <b>شرح نظام الإحالة (اربح من دعوة أصحابك)</b>\n\n"
        "1) اضغط زر <b>🎁 الإحالة</b> من القائمة.\n"
        "2) انسخ <b>رابطك الخاص</b> وشاركه.\n"
        "3) أي حد يدخل من رابطك ويفعّل حسابه، تاخذ <b>مكافأة دولارية</b> تنضاف لرصيدك تلقائياً.\n"
        "4) تشوف عدد المدعوين وأرباحك بنفس الصفحة.\n\n"
        "⚠️ ملاحظة: لازم تكون مشترك بالقنوات الإجبارية عشان تنحسب لك المكافأة، "
        "وأي تحايل (حسابات وهمية) يلغي الأرباح.",
    )


@router.callback_query(F.data == "info:support")
async def support_info(callback: CallbackQuery):
    await _safe_edit(
        callback,
        "🆘 <b>الدعم الفني — كيف تتواصل معنا؟</b>\n\n"
        "1) اضغط زر <b>🆘 الدعم</b> من القائمة الرئيسية.\n"
        "2) اكتب مشكلتك برسالة وحدة واضحة (مع رقم الطلب أو صورة الإثبات إذا موجودة).\n"
        "3) تنفتح لك <b>تذكرة</b> ويرد عليك الأدمن بنفس المحادثة.\n"
        "4) يوصلك إشعار أول ما يرد الأدمن.\n\n"
        "⏰ نحاول نرد بأسرع وقت. لا ترسل رسائل متكررة عشان تذكرتك ما تتأخر.",
    )


@router.callback_query(F.data == "info:subscription")
async def subscription_info(callback: CallbackQuery):
    await _safe_edit(
        callback,
        "📢 <b>الاشتراك الإجباري بالقنوات</b>\n\n"
        "البوت يطلب منك تشترك بقناة أو أكثر قبل الاستخدام.\n\n"
        "1) أول ما تضغط /start يطلع لك أزرار القنوات.\n"
        "2) اشترك بكل القنوات.\n"
        "3) ارجع واضغط <b>✅ تحقق من الاشتراك</b>.\n"
        "4) تنفتح لك القائمة الرئيسية مباشرة.\n\n"
        "إذا غادرت أي قناة لاحقاً، البوت يوقفك مؤقتاً لحد ما ترجع تشترك.",
    )


@router.callback_query(F.data == "info:developer")
async def developer_info(callback: CallbackQuery):
    await _safe_edit(
        callback,
        "👨‍💻 <b>المطور وحقوق البوت</b>\n\n"
        "🤖 <b>هذا البوت برمجة وتطوير:</b>\n"
        f"👨‍💻 المبرمج <b>{DEVELOPER_NAME}</b>\n"
        "🌍 فلسطين\n\n"
        "© جميع الحقوق محفوظة للمطور. يُمنع نسخ البوت أو بيع نسخة منه بدون إذن خطي.\n\n"
        "📩 <b>للتواصل وطلب بوت خاص أو دعم فني:</b>\n"
        f"✈️ تيليجرام: {DEVELOPER_USERNAME}\n\n"
        "💡 متوفر: تصميم بوتات متاجر وأرقام وشحن تلقائي ولوحات أدمن كاملة.",
    )


# ── روابط قديمة من نسخة المتجر (للتوافق مع الرسائل القديمة) ──
@router.callback_query(F.data.in_({"info:guide", "info:market", "info:market_buy", "info:market_sell", "info:special", "info:ads", "info:notifications", "info:withdraw"}))
async def legacy_alias(callback: CallbackQuery):
    """أزرار قديمة حُذفت أقسامها بنسخة الأرقام — نوجّهها للصفحة الرئيسية للمعلومات."""
    await bot_info_home(callback)
