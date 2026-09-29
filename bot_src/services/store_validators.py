"""
تحقق من مدخلات طلبات المتجر (دوال خالصة بدون اعتماديات ثقيلة).

- phone: رقم سوري 09xxxxxxxx (يقبل +963/00963 ويوحده).
- player: معرّف لاعب 2-64 حرفاً.
- link: رابط/قيمة 3-500 حرف.
"""

from __future__ import annotations

import re

SYRIAN_MOBILE_RE = re.compile(r"^09\d{8}$")


def normalize_phone(value: str) -> str:
    """يوحد رقم الهاتف السوري إلى صيغة 09xxxxxxxx."""
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("00963"):
        digits = "0" + digits[5:]
    elif digits.startswith("963"):
        digits = "0" + digits[3:]
    return digits


def validate_target(kind: str, value: str) -> tuple[bool, str]:
    """يتحقق من الهدف حسب نوعه. يرجع (ناجح، القيمة/رسالة الخطأ)."""
    value = (value or "").strip()
    if kind == "none":
        return True, ""
    if not value:
        return False, "⚠️ أرسل القيمة المطلوبة."
    if kind == "phone":
        normalized = normalize_phone(value)
        if not SYRIAN_MOBILE_RE.match(normalized):
            return False, (
                "⚠️ رقم غير صالح.\n"
                "أدخل رقماً سورياً من 10 خانات يبدأ بـ <code>09</code> "
                "(مثال: <code>09xxxxxxxx</code>)."
            )
        return True, normalized
    if kind == "player":
        if len(value) < 2 or len(value) > 64:
            return False, "⚠️ معرّف اللاعب غير صالح (2-64 حرفاً)."
        return True, value
    if len(value) < 3 or len(value) > 500:
        return False, "⚠️ الرابط/القيمة غير صالحة."
    return True, value
