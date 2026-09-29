"""
بروتوكول المتاجر الخارجية بنمط Hyper Store (API عام للمتاجر).

المواصفة:
- المصادقة: هيدر ``api-token: TOKEN`` (أو ``?api_token=``).
- ``GET /profile``        → {balance, currency, username, ...}
- ``GET /categories``     → التصنيفات (id/name/parent_id)
- ``GET /content/{id}``   → تصنيف + فروعه + منتجاته
- ``GET /products``       → كل المنتجات (params: products_id, limit, page)
- ``POST /newOrder/{productId}/params`` → إنشاء طلب
    (quantity + حقول الخدمة من ``fields`` + order_uuid موصى بها —
    نفس الـ uuid = نفس الطلب القديم فلا يُشترى مرتين)
- ``GET /check?orders=``  → حالة الطلبات (حتى 100، بفواصل)
- الأكواد: 100 رصيد غير كافٍ، 105/110 الخدمة غير متوفرة،
  109 الخدمة غير موجودة، 112/113/114 كمية/معاملات،
  120/121/122/123 مصادقة، 500 خطأ داخلي.
"""

from __future__ import annotations

import json
import logging
import uuid as uuid_lib
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

import aiohttp

from protocols.base import (
    BaseProtocol,
    ProtocolAuthError,
    ProtocolBalance,
    ProtocolConnectionError,
    ProtocolError,
    ProtocolInsufficientFundsError,
    ProtocolInvalidServiceError,
    ProtocolOrder,
    ProtocolOrderStatus,
    ProtocolService,
    is_insufficient_funds_error,
    normalize_order_status,
)

logger = logging.getLogger(__name__)

ENGINE_KEYS = ("hyper_store", "hyper4store", "external_store", "external_store_api")
DEFAULT_API_URL = "https://api.hyper4store.com"

# رموز الأخطاء → الاستثناءات
_ERROR_AUTH = {120, 121, 122, 123}
_ERROR_SERVICE = {105, 109, 110}
_ERROR_FONDS = {100}
_ERROR_INTERNAL = {500}

LINK_FIELD_HINTS = ("link", "url", "address", "channel", "post")
PLAYER_FIELD_HINTS = ("playerid", "player_id", "userid", "user_id", "uid", "username", "member")


def is_hyper_store_config(custom_config: dict | None) -> bool:
    if not custom_config:
        return False
    engine = str(custom_config.get("engine") or custom_config.get("preset") or "").lower()
    return engine in ENGINE_KEYS


def is_hyper_store_provider(provider) -> bool:
    raw = getattr(provider, "custom_config", None)
    if not raw:
        return False
    if isinstance(raw, dict):
        return is_hyper_store_config(raw)
    try:
        return is_hyper_store_config(json.loads(raw))
    except (TypeError, ValueError):
        return False


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _field_keys(product: dict) -> list[str]:
    """مفاتيح الحقول المطلوبة من المنتج (fields/required_fields/input_type).

    بعض منتجات HyperStore ترجع الحقول كقائمة كائنات تحت ``input_type``
    بدل ``fields`` — ندعم الشكلين.
    """
    keys: list[str] = []
    for source_key in ("fields", "input_type"):
        raw_fields = product.get(source_key)
        if isinstance(raw_fields, list):
            for f in raw_fields:
                if isinstance(f, dict) and f.get("key"):
                    keys.append(str(f["key"]))
    required = product.get("required_fields")
    if isinstance(required, str):
        keys.extend(k.strip() for k in required.split(",") if k.strip())
    elif isinstance(required, list):
        keys.extend(str(k) for k in required)
    # إزالة التكرار مع الحفاظ على الترتيب
    seen = set()
    out = []
    for k in keys:
        if k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out


def _iter_field_defs(product: dict) -> list[dict]:
    """كل تعريفات الحقول كقواميس (من fields أو input_type القائمة).

    بعض المنتجات ترجع input_type كنص JSON مرمّز (dropdown الفئات) —
    نحلّله أيضاً.
    """
    import json as _json

    defs: list[dict] = []
    for source_key in ("fields", "input_type"):
        raw_fields = product.get(source_key)
        if isinstance(raw_fields, str):
            try:
                raw_fields = _json.loads(raw_fields)
            except Exception:
                raw_fields = None
        if isinstance(raw_fields, list):
            defs.extend(f for f in raw_fields if isinstance(f, dict))
    return defs


PHONE_LABEL_HINTS = (
    "هاتف", "رقم", "جوال", "موبايل", "سيريتل", "mtn",
    "phone", "mobile", "number", "msisdn",
)


def detect_target_kind(product: dict) -> str:
    """نوع الهدف المطلوب: phone | player | link | none.

    - phone: حقل بصيغة رقم هاتف (سيريتل/MTN — يبدأ بـ 09).
    - player: حقل Player ID / user id.
    - link: رابط.
    - none: لا يحتاج هدف (كمية فقط).
    """
    defs = _iter_field_defs(product)
    lowers = [(str(d.get("key", "")), str(d.get("label", "")), str(d.get("provider_key", ""))) for d in defs]
    for key, label, pkey in lowers:
        blob = f"{key} {label} {pkey}".lower()
        if any(h in blob for h in PHONE_LABEL_HINTS) and "quantity" not in key.lower():
            return "phone"
    for key, label, pkey in lowers:
        blob = f"{key} {label} {pkey}".lower()
        if any(h in blob for h in PLAYER_FIELD_HINTS):
            return "player"
    for key, label, pkey in lowers:
        blob = f"{key} {label} {pkey}".lower()
        if any(h in blob for h in LINK_FIELD_HINTS):
            return "link"
    # احتياطي: أي حقل غير quantity يعني هدفاً نصياً عاماً
    keys = _field_keys(product)
    extra = [k for k in keys if k.lower() != "quantity"]
    if extra:
        return "link"
    return "none"


def quantity_options(product: dict) -> list[str]:
    """خيارات الفئات الثابتة (dropdown) لحقل الكمية إن وجدت.

    مثال: رصيد سيريتل — options: ["1.92","2.88",...].
    ترجع قائمة فارغة إذا الكمية حرة.
    """
    for d in _iter_field_defs(product):
        if str(d.get("key", "")).lower() != "quantity":
            continue
        adv = d.get("advanced") or {}
        opts = adv.get("options") if isinstance(adv, dict) else None
        if isinstance(opts, list) and opts:
            return [str(o) for o in opts]
    return []


def target_field_label(product: dict) -> str:
    """تسمية حقل الهدف للعرض (من label المزود أو افتراضي)."""
    kind = detect_target_kind(product)
    for d in _iter_field_defs(product):
        key = str(d.get("key", ""))
        if key.lower() == "quantity":
            continue
        label = str(d.get("label") or d.get("provider_key") or "").strip()
        if kind == "phone" and label:
            return label
        if kind == "player" and label:
            return label
        if kind == "link" and label:
            return label
    return {"phone": "رقم الهاتف", "player": "معرّف اللاعب", "link": "الرابط"}.get(kind, "الهدف")


class HyperStoreProtocol(BaseProtocol):
    """متجر خارجي عام بنمط Hyper Store (api-token)."""

    name = "hyper_store"

    def __init__(self, api_url: str, api_key: str, custom_config: dict | None = None):
        super().__init__(api_url or DEFAULT_API_URL, api_key, custom_config)
        self.timeout = int((custom_config or {}).get("timeout", 45))
        self.page_limit = int((custom_config or {}).get("page_limit", 100))

    # ─────────── HTTP ───────────

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "api-token": self.api_key,
        }

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.api_url.rstrip('/')}/{path.lstrip('/')}"

    def _raise_for_error(self, data: dict) -> None:
        """يرجم استثناءً مناسباً إذا كانت الاستجابة خطأ رقمياً/نصياً."""
        if not isinstance(data, dict):
            return
        code = data.get("error")
        if code is None:
            code = data.get("code")
        if code is None:
            return
        try:
            code_int = int(code)
        except (TypeError, ValueError):
            code_int = None
        message = str(data.get("message") or data.get("error_message") or data.get("msg") or code)

        if code_int in _ERROR_AUTH:
            raise ProtocolAuthError(f"مشكلة مصادقة مع المتجر ({code_int}): {message}")
        if code_int in _ERROR_FONDS or is_insufficient_funds_error(message):
            raise ProtocolInsufficientFundsError(f"رصيد غير كافٍ لدى المتجر: {message}")
        if code_int in _ERROR_SERVICE:
            raise ProtocolInvalidServiceError(f"الخدمة غير متوفرة لدى المتجر: {message}")
        if code_int in _ERROR_INTERNAL:
            raise ProtocolConnectionError(f"خطأ داخلي لدى المتجر: {message}")
        if isinstance(code, str) and code.strip() and not code.isdigit():
            raise ProtocolError(f"خطأ من المتجر: {message}")

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        params: dict | None = None,
    ):
        url = self._url(path)
        if params:
            query = urlencode({k: v for k, v in params.items() if v is not None})
            if query:
                url = f"{url}?{query}"
        try:
            async with aiohttp.ClientSession(
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as session:
                kwargs = {}
                if payload is not None and method.upper() != "GET":
                    kwargs["json"] = payload
                async with session.request(method.upper(), url, **kwargs) as response:
                    body = await response.text()
                    if response.status in (401, 403):
                        raise ProtocolAuthError(f"مفتاح المتجر مرفوض: HTTP {response.status}")
                    try:
                        parsed = json.loads(body) if body else {}
                    except json.JSONDecodeError as exc:
                        raise ProtocolError(f"استجابة غير JSON من المتجر: {body[:200]}") from exc
                    if isinstance(parsed, dict):
                        self._raise_for_error(parsed)
                    if response.status not in (200, 201, 202):
                        raise ProtocolConnectionError(
                            f"HTTP {response.status} من المتجر: {body[:200]}"
                        )
                    return parsed
        except ProtocolError:
            raise
        except TimeoutError as exc:
            raise ProtocolConnectionError("انتهت مهلة الاتصال بالمتجر الخارجي") from exc
        except aiohttp.ClientError as exc:
            raise ProtocolConnectionError(f"تعذر الاتصال بالمتجر الخارجي: {exc}") from exc

    # ─────────── الأساسيات ───────────

    async def test_connection(self) -> bool:
        await self._request("GET", "/profile")
        return True

    async def get_balance(self) -> ProtocolBalance:
        data = await self._request("GET", "/profile")
        if not isinstance(data, dict):
            raise ProtocolError("رصيد المتجر ليس كائناً")
        # الرد ملفوف: {status, data: {balance,...}} — ندعم الشكلين.
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        raw_amount = payload.get("balance", payload.get("amount", payload.get("credit", 0)))
        try:
            amount = Decimal(str(raw_amount))
        except (InvalidOperation, ValueError) as exc:
            raise ProtocolError("قيمة الرصيد غير صالحة") from exc
        return ProtocolBalance(
            amount=amount,
            currency=str(data.get("currency") or "USD"),
            raw=data,
        )

    # ─────────── الخدمات ───────────

    async def get_categories(self) -> list[dict]:
        data = await self._request("GET", "/categories", params={"parent_id": 0})
        return self._as_list(data)

    async def get_services(self) -> list[ProtocolService]:
        """كل المنتجات من المتجر (ترقيم صفحات حتى النفاد)."""
        out: list[ProtocolService] = []
        seen: set[str] = set()
        page = 1
        while True:
            data = await self._request(
                "GET", "/products", params={"limit": self.page_limit, "page": page}
            )
            items = self._as_list(data)
            if not items:
                break
            for item in items:
                svc = self._parse_service(item)
                if svc is None or svc.external_id in seen:
                    continue
                seen.add(svc.external_id)
                out.append(svc)
            if len(items) < self.page_limit:
                break
            page += 1
            if page > 500:  # حاجز أمان
                break
        return out

    async def get_product_info(self, service_id: str | int) -> dict:
        """بيانات منتج واحد (لحقول الطلب)."""
        data = await self._request("GET", "/products", params={"products_id": service_id})
        items = self._as_list(data)
        if not items:
            return {}
        return items[0] if isinstance(items[0], dict) else {}

    def _parse_service(self, item: dict) -> ProtocolService | None:
        if not isinstance(item, dict):
            return None
        external_id = item.get("id", item.get("product_id", item.get("service_id")))
        if external_id is None:
            return None
        rate = _as_decimal(item.get("price", item.get("rate", 0))) or Decimal("0")
        input_type = str(item.get("input_type") or "").lower()
        field_keys = _field_keys(item)
        field_lowers = [k.lower() for k in field_keys]

        requires_link = any(h in input_type for h in LINK_FIELD_HINTS) or any(
            any(h in fk for h in LINK_FIELD_HINTS) for fk in field_lowers
        )
        requires_player_id = any(
            any(h in fk for h in PLAYER_FIELD_HINTS) for fk in field_lowers
        )
        name = str(
            item.get("name") or item.get("name_ar") or item.get("title") or f"خدمة {external_id}"
        )
        opts = quantity_options(item)
        kind = detect_target_kind(item)
        return ProtocolService(
            external_id=str(external_id),
            name=name,
            category=(
                str(item["category"])
                if item.get("category")
                else (str(item["category_name"]) if item.get("category_name") else None)
            ),
            service_type=input_type or None,
            rate=rate,
            min_quantity=_as_int(item.get("min", item.get("min_quantity", 1)), 1),
            max_quantity=_as_int(item.get("max", item.get("max_quantity", 1000000)), 1000000),
            description=item.get("description") or None,
            requires_link=(kind == "link"),
            requires_quantity=True,
            requires_player_id=(kind == "player"),
            supports_refill=bool(item.get("refill") or item.get("supports_refill")),
            supports_cancel=bool(item.get("cancel") or item.get("supports_cancel")),
            raw={**item, "_target_kind": kind, "_quantity_options": opts},
        )

    # ─────────── الطلبات ───────────

    def _target_field_name(self, product: dict, requires_player_id: bool) -> str:
        """اسم حقل الهدف حسب حقول المنتج (رابط/بلايدير/عموم)."""
        field_keys = _field_keys(product)
        if requires_player_id:
            for key in field_keys:
                if any(h in key.lower() for h in PLAYER_FIELD_HINTS):
                    return key
            return "playerId"
        for key in field_keys:
            if any(h in key.lower() for h in LINK_FIELD_HINTS):
                return key
        if field_keys:
            return field_keys[0]
        return "link"

    async def place_order(
        self,
        service_id: str,
        target: str,
        quantity: int | str | Decimal,
        extra_params: dict | None = None,
    ) -> ProtocolOrder:
        product = await self.get_product_info(service_id)
        payload: dict = {"quantity": str(quantity)}
        order_uuid = str(uuid_lib.uuid4())
        payload["order_uuid"] = order_uuid

        if target:
            field_keys = _field_keys(product)
            is_player = any(
                any(h in k.lower() for h in PLAYER_FIELD_HINTS) for k in field_keys
            )
            field_name = self._target_field_name(product, is_player)
            payload[field_name] = target

        if extra_params:
            for key, value in extra_params.items():
                if value is not None:
                    payload[key] = value

        data = await self._request("POST", f"/newOrder/{service_id}/params", payload=payload)
        if not isinstance(data, dict):
            raise ProtocolError(f"المتجر لم يرجع بيانات الطلب: {data}")
        order_id = data.get("order_id", data.get("id", data.get("orderId")))
        if order_id is None:
            raise ProtocolError(f"المتجر لم يرجع order_id: {data}")
        return ProtocolOrder(
            external_order_id=str(order_id),
            status=normalize_order_status(str(data.get("status") or "pending")),
            raw={
                **data,
                "order_code": data.get("order_code", data.get("code")),
                "order_uuid": data.get("order_uuid", order_uuid),
            },
        )

    async def check_order_status(self, external_order_id: str) -> ProtocolOrderStatus:
        data = await self._request("GET", "/check", params={"orders": external_order_id})
        entry = self._find_order_entry(data, external_order_id)
        if not isinstance(entry, dict):
            entry = {}
        status = str(
            entry.get("status")
            or entry.get("state")
            or data.get("status")
            or "pending"
        )
        delivered = entry.get("delivered_data", entry.get("deliveredData"))
        raw = {**entry}
        if delivered:
            raw["delivered_data"] = delivered
        return ProtocolOrderStatus(
            external_order_id=str(external_order_id),
            status=normalize_order_status(status),
            charge=_as_decimal(
                entry.get("charge", entry.get("price", entry.get("cost")))
            ),
            remains=_as_int(entry.get("remains"), 0) or None,
            start_count=_as_int(entry.get("start_count"), 0) or None,
            raw=raw,
        )

    @staticmethod
    def _find_order_entry(data, external_order_id: str) -> dict | None:
        """يجد مدخل الطلب داخل استجابة /check (قائمة/قاموس).

        يدعم الشكل الملفوف: {status, data: {order_code: entry}}.
        """
        wanted = str(external_order_id)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    if str(item.get("order_id", item.get("id", ""))) == wanted:
                        return item
                    if str(item.get("order_code", "")) == wanted:
                        return item
            return data[0] if len(data) == 1 and isinstance(data[0], dict) else None
        if isinstance(data, dict):
            # {status: OK, data: {code: entry}} — ابحث بالمفتاح مباشرة
            inner = data.get("data")
            if isinstance(inner, dict):
                if wanted in inner and isinstance(inner[wanted], dict):
                    return inner[wanted]
                found = HyperStoreProtocol._find_order_entry(inner, wanted)
                if found:
                    return found
            if isinstance(data.get("orders"), list):
                return HyperStoreProtocol._find_order_entry(data["orders"], wanted)
            if isinstance(data.get("data"), list):
                return HyperStoreProtocol._find_order_entry(data["data"], wanted)
            if any(k in data for k in ("status", "state", "delivered_data")):
                # تجاهل غلاف {status: OK} الفارغ
                if set(data.keys()) <= {"status", "message", "code"}:
                    return None
                return data
        return None

    @staticmethod
    def _as_list(data) -> list:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("products", "items", "services", "results", "data", "categories"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []
