"""حسابات الكوبونات الخالصة (بدون اعتماديات)."""

from __future__ import annotations

from decimal import Decimal


def calc_discount(total: Decimal, discount_type: str, value: Decimal) -> Decimal:
    """مبلغ الخصم (موجب، لا يتجاوز الإجمالي)."""
    total = Decimal(str(total or 0))
    value = Decimal(str(value or 0))
    if value <= 0 or total <= 0:
        return Decimal("0")
    if (discount_type or "percent") == "percent":
        discount = total * value / Decimal("100")
    else:
        discount = value
    discount = discount.quantize(Decimal("0.0001"))
    return min(discount, total)
