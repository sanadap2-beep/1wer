"""
السجل المرجعي لكل الإضافات في البوت.

كل إضافة جديدة تُعرَّف هنا مرة واحدة، فتحصل تلقائياً على:
- مفتاح تفعيل/إيقاف من لوحة الأدمن.
- إعدادات خاصة قابلة للتعديل من لوحة الأدمن.
- سجل استخدام يقيس هل هي مستعملة فعلاً أم ميتة.

لا يُضاف أي سطر كود لميزة جديدة في مكان آخر من البوت بدون تسجيلها هنا،
وإلا لن تظهر للأدمن ولن يستطيع التحكم بها.

الحقول:
- key: معرف فريد (يُستخدم في الكود وفي قاعدة البيانات).
- name_ar / name_en: الاسم الظاهر في اللوحة.
- category_ar: مجموعة العرض في اللوحة.
- desc_ar: شرح مختصر يفهمه الأدمن.
- default_enabled: هل تعمل فور التثبيت.
- defaults: الإعدادات الافتراضية القابلة للتعديل.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    name_ar: str
    name_en: str
    category_ar: str
    desc_ar: str
    default_enabled: bool = False
    defaults: dict = field(default_factory=dict)

    @property
    def emoji_category(self) -> str:
        return _CATEGORY_EMOJI.get(self.category_ar, "🧩")


_CATEGORY_EMOJI = {
    "الأساس": "⚙️",
    "الاقتصاد": "💰",
    "السوق": "🏪",
    "الأرقام": "📱",
    "الرشق": "📈",
    "الألعاب": "🎮",
    "التطبيقات": "📦",
    "الذكاء": "🤖",
    "الثقة": "🛡️",
    "النمو": "🚀",
    "التفاعل": "🎯",
    "القنوات": "🌐",
    "الإشعارات": "🔔",
    "الاشتراكات": "🔐",
}


def _spec(
    key: str,
    name_ar: str,
    name_en: str,
    category_ar: str,
    desc_ar: str,
    default_enabled: bool = False,
    **defaults,
) -> FeatureSpec:
    return FeatureSpec(
        key=key,
        name_ar=name_ar,
        name_en=name_en,
        category_ar=category_ar,
        desc_ar=desc_ar,
        default_enabled=default_enabled,
        defaults=dict(defaults),
    )


# ══════════════════════════════════════════════════════════════
#  السجل الكامل
# ══════════════════════════════════════════════════════════════

FEATURES: tuple[FeatureSpec, ...] = (
    _spec(
        "deposit_bonuses",
        "🎁 مكافآت الشحن (نسبة إضافية على الإيداع)",
        "Deposit Bonuses",
        "الاقتصاد",
        "يحدد الأدمن قواعد: كل إيداع >= حد معين يمنح نسبة إضافية من "
        "الرصيد تلقائياً فور اكتمال الإيداع. زيادة مباشرة لحجم الإيداعات.",
        False,
        rules_json='[{"min_deposit":5,"percent":2,"max_bonus":2}]',
        notify_on_grant=True,
    ),
    # ─────────── الأساس ───────────
    _spec(
        "agent_program",
        "برنامج الوكلاء (خصم حتى 10%)",
        "Agent Program",
        "الاقتصاد",
        "وكلاء بخصم على كل المنتجات والخدمات: الأدمن يصدر كوداً، ومن يدخله "
        "يصبح وكلاً. يُسحب من وُجد إيداعه الأسبوعي أقل من الحد.",
        False,
        default_percent=10,
        min_weekly_deposit_usd=20,
        check_interval_hours=6,
        min_percent=1,
        max_percent=50,
    ),
    _spec(
        "feature_usage_analytics",
        "قياس استخدام الإضافات",
        "Feature Usage Analytics",
        "الأساس",
        "يسجل استخدام كل إضافة ليعرف الأدمن أيها يستحق التطوير وأيها يجب إيقافه.",
        True,
        retention_days=90,
    ),

    # ─────────── الأرقام ───────────
    _spec(
        "instant_delivery",
        "التسليم اللحظي المتوازي",
        "Parallel Instant Delivery",
        "الأرقام",
        "فحص الطلبات بشكل متوازٍ بدل التسلسلي، مع webhook لمن يدعمه.",
        True,
        batch_size=25,
        poll_interval_seconds=5,
        enable_webhooks=True,
    ),
    _spec(
        "bulk_numbers",
        "شراء الأرقام بالجملة",
        "Bulk Number Purchase",
        "الأرقام",
        "شراء عدة أرقام بطلب واحد مع خصم تدريجي وتصدير النتائج.",
        True,
        max_quantity=500,
        concurrency=10,
        discount_tiers_json='[[10,1],[50,3],[100,5],[500,8]]',
    ),
    _spec(
        "ready_number_packages",
        "باقات الأرقام الجاهزة",
        "Ready Number Packages",
        "الأرقام",
        "باقات كمية جاهزة تظهر للمستخدم وتختصر اختيار الكمية للتجار والمبتدئين.",
        True,
        quantities_json='[5,10,25,50]',
        max_cards=8,
    ),
    _spec(
        "numbers_availability_board",
        "التوفر المتقطع (قناة الأرقام الحية)",
        "Numbers Availability Board",
        "الأرقام",
        "قناة حية تُحدَّث كل دقيقة: ترتيب دوّار للدول المتوفرة + وسم 🔥 للدول النادرة "
        "لحظة رجوعها للمخزون. الرسالة تُعدَّل في مكانها، والحالة محفوظة فتنجو من إعادة "
        "التشغيل، وكل زر رابط شراء مباشر لدولة مفعّلة فعلاً.",
        False,
        channel_chat_id="",
        service_code="whatsapp",
        top_n=12,
        refresh_seconds=60,
        rotate_stable=True,
        always_publish=True,
        watched_country_codes=(
            "ae,uae,sa,ksa,us,usa,gb,uk,qa,kw,bh,om,jo,eg,de,fr,ca,au"
        ),
        header_text=(
            "📡 <b>التوفر المتقطع — أرقام {service}</b>\n"
            "🔥 = دولة نادرة عادت للمخزون الآن · 💎 = نادرة متاحة · 🟢 = متوفرة\n"
            "اضغط على الدولة لينقلك البوت مباشرة لإتمام الطلب."
        ),
    ),
    _spec(
        "smart_number_routing",
        "توجيه مزودي الأرقام الذكي",
        "Smart Number Provider Routing",
        "الأرقام",
        "لا يختار الأرخص فقط؛ يرتب مزودي الأرقام حسب السعر ونسبة النجاح وسرعة وصول الكود.",
        True,
        days=14,
        min_samples=5,
        price_weight=65,
        quality_weight=35,
        min_success_rate=55,
    ),
    _spec(
        "number_server_selection",
        "السيرفرات/المزودين المتعددين",
        "Number Servers / Providers",
        "الأرقام",
        "كل خدمة أرقام تحوي أكثر من سيرفر (مزود). قبل اختيار الدولة يختار "
        "المستخدم السيرفر الذي يناسبه، والأدمن يدير السيرفرات بالكامل.",
        True,
        auto_create_per_provider=True,
    ),

    # ─────────── الرشق ───────────

    # ─────────── الألعاب ───────────

    # ─────────── التطبيقات ───────────

    # ─────────── الذكاء ───────────

    # ─────────── الثقة ───────────

    # ─────────── النمو ───────────

    # ─────────── القنوات ───────────

    # ─────────── الأساس التقني ───────────
    # ─────────── الإضافات الثلاث الهدية (على مستوى البوت كامل) ───────────
    _spec(
        "self_heal_sentinel",
        "الحارس الذاتي (وضع آمن)",
        "Self-Heal Sentinel",
        "الأساس",
        "يراقب معدل الأخطاء ويُدخل البوت وضعاً آمناً يعطّل الميزات الخطرة "
        "تلقائياً قبل أن تتفاقم الخسارة.",
        True,
        error_threshold=20,
        window_minutes=10,
    ),
    # ─────────── الرشق: الأقسام الداخلية والبناء التلقائي ───────────
    # ─────────── الثقة: حماية الإحالة من البوتات ───────────
    _spec(
        "referral_bot_guard",
        "حماية الإحالة من البوتات",
        "Referral Bot Guard",
        "الثقة",
        "من يدخل عبر رابط إحالة يمر باختبار بشري قبل التفعيل ومكافأة المحيل؛ "
        "وعند تكرار الفشل يُعتبر روبوتاً فيُحظر هو ويُعاقب صاحب رابط الإحالة.",
        True,
        max_fails=3,
        ban_referrer_on_bot=True,
        ban_joiner_on_bot=True,
    ),
    # ─────────── الاشتراكات: مزامنة ggsoma ───────────
    # ─────────── الإشعارات: مباشر البوت ───────────
    _spec(
        "live_bot_feed",
        "📡 مباشر البوت (أحداث الشراء والاسترجاع)",
        "Bot Live Feed",
        "الإشعارات",
        "إشعارات فورية للوحة الأدمن عند كل عملية شراء تنجح وتُفعَّل (خصم "
        "الرصيد) وعند كل استرجاع/فشل (رجوع الرصيد للمستخدم) — ليعرف صاحب "
        "البوت مباشرة ماذا يحدث دون انتظار شكوى من المستخدم.",
        True,
        notify_success=True,
        notify_refund=True,
    ),
    # ─────────── الإضافات الجديدة: التجارة والتفاعل ───────────

    # ─────────── الدفعة الجديدة: العمليات بالليرة وتحويلات الشتات ───────────
    _spec(
        "mobile_credit_deposit",
        "📲 الشحن برصيد الجوال (مراجعة الأدمن)",
        "Mobile Credit Deposit",
        "الاقتصاد",
        "طريقة شحن جديدة: يرسل المستخدم رقم جواله والمبلغ ولقطة من عملية "
        "التحويل، فيصبح طلباً بانتظار موافقة الأدمن كباقي طرق الشحن.",
        False,
        min_amount_usd=1,
        max_amount_usd=250,
    ),
    _spec(
        "syp_display",
        "💱 عرض السعر بالليرة السورية",
        "Live SYP Display",
        "الاقتصاد",
        "يُظهر إجمالي السعر بالدولار وما يعادله عند سعر الصرف الحالي "
        "بجانب عمليات الشراء والمحفظة — الشفافية التي يبحث عنها المشتري السوري.",
        True,
    ),
    _spec(
        "db_backup_telegram",
        "💾 النسخ الاحتياطي اليومي (قناة تلغرام)",
        "Daily Telegram DB Backup",
        "الأساس",
        "لقطة متسقة من قاعدة البيانات يومياً تُرسل لقناة النسخ. chat_id "
        "قابل للضبط من هنا، أو يقع على backup_channel_id إن تُرك فارغاً.",
        True,
        chat_id="",
        backup_time="03:00",
    ),
)


BY_KEY: dict[str, FeatureSpec] = {spec.key: spec for spec in FEATURES}


def get_spec(key: str) -> FeatureSpec | None:
    return BY_KEY.get(key)


def all_keys() -> list[str]:
    return [spec.key for spec in FEATURES]


def by_category() -> dict[str, list[FeatureSpec]]:
    grouped: dict[str, list[FeatureSpec]] = {}
    for spec in FEATURES:
        grouped.setdefault(spec.category_ar, []).append(spec)
    return grouped


def categories_ordered() -> list[str]:
    order = list(_CATEGORY_EMOJI.keys())
    present = [c for c in order if c in by_category()]
    present += [c for c in by_category() if c not in order]
    return present
