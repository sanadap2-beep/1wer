"""
🎨 محرك ستايل الرسائل الفاخر (Lux) — دوال خالصة بدون اعتماديات ثقيلة.

- صناديق بفواصل ━━━ وعناوين بتطويل مطابقة لهوية البوت.
- أسعار مزدوجة $ + ل.س (سعر الصرف يُمرر من المتصل).
- مدد بالعربي + تذييل «نورت بوتنا».
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from html import escape

SEP = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
FOOTER = "\nنـورت بـوتـنـا 🤍"


def _num(value) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def dual(amount_usd, syp_rate) -> str:
    """$3.10 (431 ل.س) — دولار + ليرة."""
    usd = _num(amount_usd)
    try:
        rate = Decimal(str(syp_rate or 0))
    except Exception:
        rate = Decimal("0")
    usd_text = f"${usd:,.2f}"
    if rate > 0:
        return f"{usd_text} ({(usd * rate):,.0f} ل.س)"
    return usd_text


def elapsed_ar(start: datetime | None, end: datetime | None) -> str:
    """المدة بين وقتين بالعربي: 10 دقيقة و 18 ثانية."""
    if not start or not end:
        return "—"
    total = max(0, int((end - start).total_seconds()))
    m, s = divmod(total, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h} ساعة و {m} دقيقة"
    if m:
        return f"{m} دقيقة و {s} ثانية"
    return f"{s} ثانية"


def order_created(
    product: str, price_dual: str, target_label: str, target: str,
    order_no: str, auto_note: str = "هـذا الـمـنـتـج بـعـمـل بـشـكـل تـلـقـائـي",
) -> str:
    return (
        "✅ تـم إنـشـاء طـلـبـك بـنـجـاح\n"
        f"{SEP}\n\n"
        f"📦 الـمـنـتـج : {escape(product)}\n"
        f"💰 الـسـعـر : {price_dual}\n"
        f"🔹 الـمـعـلـومـات الـمـدخـلـة:\n{target_label}: {escape(target)}\n"
        f"🔹 رقـم الـطـلـب :\n{escape(order_no)}\n"
        f"{SEP}\n\n"
        "عـنـدمـا يـتـم الـشـحـن سـيـتـم اعـلامـك :\n"
        f"( {auto_note} )"
    )


def order_completed(
    product: str, target_label: str, target: str, order_no: str,
    elapsed: str, server_reply: str,
) -> str:
    return (
        "✅ تـم اكـتـمـال طـلـبـك بـنـجـاح!\n"
        f"{SEP}\n\n"
        f"📦 الـمـنـتـج: {escape(product)}\n"
        f"🔹 الـمـعـلـومـات الـمـدخـلـة:\n{target_label}: {escape(target)}\n"
        f"🔹 رقـم الـطـلـب:\n{escape(order_no)}\n"
        f"🕒 الـوقـت الـمـسـتـغـرق: {escape(elapsed)}\n"
        f"📨 رد الـسـيـرفـر:\n{escape(server_reply or 'تم تنفيذ الطلب بنجاح')}\n"
        f"{SEP}"
        f"{FOOTER}"
    )


def product_card(
    service: str, product: str, qty_range: str, price_dual: str,
    after_dual: str | None, rank_line: str | None, notes: list[str] | None = None,
) -> str:
    lines = [
        "⚫️ مـعـلـومـات الـخـدمـة :",
        SEP,
        f"🛍️ الخدمة: {escape(service)}",
        f"📦 الـمـنـتـج: {escape(product)}",
        f"🔢 الـكـمـيـة: {escape(qty_range)}",
        f"💵 الـسـعـر: {price_dual}",
    ]
    if after_dual:
        lines.append(f"🎁 بـعـد الـخـصـم: {after_dual}")
    if rank_line:
        lines.append(f"👑 مـسـتـوى حـسـابـك: {escape(rank_line)}")
    lines.append(SEP)
    if notes:
        lines.append("\n📌 مـلاحـظـة:")
        lines.extend(notes)
        lines.append(SEP)
    lines.append("\n⬇️ أدخـل: { الـهـدف }")
    return "\n".join(lines)


def confirm_order(
    product: str, qty: str, target_label: str, target: str,
    before_dual: str, after_dual: str,
) -> str:
    return (
        "⚡ تـأكـيـد الـطـلـب :\n"
        f"{SEP}\n\n"
        f"📦 الـمـنـتـج : {escape(product)}\n"
        f"🔢 الـكـمـيـة : {escape(str(qty))}\n\n"
        f"🆔 الـمـعـلـومـات الـمـدخـلـة:\n• {target_label} : {escape(target)}\n\n"
        f"💰 الـسـعـر الإجـمـالـي (قـبـل الـخـصـم) : {before_dual}\n"
        f"💰 الـسـعـر الإجـمـالـي (بـعـد الـخـصـم) : {after_dual}\n"
        f"{SEP}\n"
        "أخـتـر مـن الأسـفـل 👇🏻"
    )


def deposit_approved(
    amount_dual: str, method: str, from_name: str, new_balance: str, op_no: str,
) -> str:
    return (
        "✅ تـم قـبـول الإيـداع\n"
        f"{SEP}\n\n"
        f"💰 الـمـبـلـغ : {amount_dual}\n"
        f"💳 طـريـقـة الـدفـع : {escape(method)}\n\n"
        f"👤 مـن الـحـسـاب : {escape(from_name)}\n"
        f"📊 رصـيـدك الـجـديـد : {new_balance}\n\n"
        f"🆔 رقـم الـعـمـلـيـة : {escape(str(op_no))}\n\n"
        f"{SEP}\n\n"
        "💎 تمت إضافة المبلغ إلى رصيدك بنجاح."
    )


def account_card(
    user_id: int, name: str, username: str | None, balance_dual: str,
    spent_dual: str, rank_line: str,
) -> str:
    handle = f"@{username}" if username else "—"
    return (
        "⚫️ معلومات حسابك ⚫️\n\n"
        f"🆔 المعرف: {user_id}\n"
        f"👤 الاسم: {escape(name)}\n"
        f"🔗 المعرف: {escape(handle)}\n\n"
        f"💰 الرصيد: {balance_dual}\n"
        f"📊 إجمالي المصروفات: {spent_dual}\n"
        f"🏆 الرتبة: {escape(rank_line)}"
    )
