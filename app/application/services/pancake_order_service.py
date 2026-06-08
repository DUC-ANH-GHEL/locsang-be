from __future__ import annotations

import hashlib
import hmac
import logging
import re
import unicodedata
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.domain.models.order import Order
from app.domain.models.order_item import OrderItem
from app.domain.models.product import Product, ProductVariant


class PancakeOrderSyncError(Exception):
    pass


class PancakeOrderService:
    LOCAL_TO_PANCAKE_STATUS: dict[str, int] = {
        "pending": 0,
        "processing": 1,
        "shipped": 2,
        "delivered": 3,
        "cancelled": 6,
    }

    PANCAKE_TO_LOCAL_STATUS: dict[int, str] = {
        0: "pending",
        17: "pending",
        11: "pending",
        12: "processing",
        13: "processing",
        20: "processing",
        1: "processing",
        8: "processing",
        9: "processing",
        2: "shipped",
        3: "delivered",
        16: "delivered",
        4: "processing",
        15: "processing",
        5: "processing",
        6: "cancelled",
        7: "cancelled",
        -1: "cancelled",
    }

    def __init__(self) -> None:
        self.base_url = (settings.PANCAKE_BASE_URL or "").rstrip("/")
        self.api_key = settings.PANCAKE_API_KEY
        self.shop_id = settings.PANCAKE_SHOP_ID
        self.logger = logging.getLogger(__name__)

    def is_enabled(self) -> bool:
        return bool(settings.PANCAKE_ENABLED)

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.shop_id)

    @staticmethod
    def _looks_like_order_dict(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        keys = set(payload.keys())
        meaningful = {
            "id",
            "order_id",
            "custom_id",
            "status",
            "order_status",
            "bill_full_name",
            "bill_phone_number",
            "bill_address",
            "items",
            "order_items",
            "line_items",
            "products",
            "details",
            "order_lines",
            "cod",
            "cash",
            "total_amount",
            "total",
            "grand_total",
        }
        return bool(keys.intersection(meaningful))

    @staticmethod
    def _normalize_order_id(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _matches_order_id(cls, payload: dict[str, Any], target_order_id: str) -> bool:
        target = cls._normalize_order_id(target_order_id)
        if not target:
            return False

        candidates = (
            payload.get("id"),
            payload.get("order_id"),
            payload.get("orderId"),
            payload.get("display_id"),
            payload.get("displayId"),
        )
        return any(cls._normalize_order_id(value) == target for value in candidates)

    @classmethod
    def _has_order_identifier(cls, payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        for key in ("id", "order_id", "orderId", "display_id", "displayId"):
            if payload.get(key) is not None and cls._normalize_order_id(payload.get(key)):
                return True
        return False

    @staticmethod
    def _extract_custom_id(payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""
        for key in ("custom_id", "customId", "tracking_code", "trackingCode"):
            value = payload.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    @classmethod
    def _extract_order_from_payload(
        cls,
        payload: Any,
        target_order_id: str,
        expected_custom_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        expected_custom = str(expected_custom_id or "").strip()

        def custom_matches(candidate: dict[str, Any]) -> bool:
            if not expected_custom:
                return True
            candidate_custom = cls._extract_custom_id(candidate)
            if not candidate_custom:
                # Some Pancake responses omit custom_id while still returning a valid order object.
                # If order id matches the requested one, treat it as a valid match.
                return cls._matches_order_id(candidate, target_order_id)
            return candidate_custom == expected_custom

        if isinstance(payload, dict):
            data = payload.get("data")
            order = payload.get("order")

            # Prefer explicit nested order object.
            if isinstance(data, dict) and isinstance(data.get("order"), dict):
                nested = data.get("order")
                if cls._looks_like_order_dict(nested) and custom_matches(nested):
                    return nested

            for candidate in (data, order, payload):
                if isinstance(candidate, dict) and cls._looks_like_order_dict(candidate):
                    if not custom_matches(candidate):
                        continue
                    if cls._matches_order_id(candidate, target_order_id):
                        return candidate
                    if not target_order_id:
                        return candidate
                    if not cls._has_order_identifier(candidate):
                        return candidate

            # Some endpoints return list in payload.data.
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and cls._looks_like_order_dict(item):
                        if not custom_matches(item):
                            continue
                        if cls._matches_order_id(item, target_order_id):
                            return item

        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and cls._looks_like_order_dict(item):
                    if not custom_matches(item):
                        continue
                    if cls._matches_order_id(item, target_order_id):
                        return item

        return None

    @classmethod
    def local_status_to_pancake_status(cls, status: str) -> int:
        if status is None:
            return 0

        if isinstance(status, bool):
            return 0

        if isinstance(status, int):
            return status if status in cls.PANCAKE_TO_LOCAL_STATUS else 0

        normalized = str(status or "").strip().lower()
        if not normalized:
            return 0

        if normalized.isdigit() or (normalized.startswith("-") and normalized[1:].isdigit()):
            numeric = int(normalized)
            return numeric if numeric in cls.PANCAKE_TO_LOCAL_STATUS else 0

        if normalized in ("returned", "return", "refund", "refunded"):
            return 5

        return cls.LOCAL_TO_PANCAKE_STATUS.get(normalized, 0)

    @classmethod
    def pancake_status_to_local_status(cls, raw_status: Any) -> str:
        if raw_status is None:
            return "pending"

        if isinstance(raw_status, bool):
            return "pending"

        if isinstance(raw_status, int):
            return cls.PANCAKE_TO_LOCAL_STATUS.get(raw_status, "processing")

        if isinstance(raw_status, dict):
            for key in ("id", "status", "order_status", "state", "code"):
                if key in raw_status and raw_status.get(key) is not None:
                    return cls.pancake_status_to_local_status(raw_status.get(key))
            for key in ("name", "label", "title", "text"):
                if key in raw_status and raw_status.get(key):
                    return cls.pancake_status_to_local_status(raw_status.get(key))

        if isinstance(raw_status, list):
            for item in raw_status:
                mapped = cls.pancake_status_to_local_status(item)
                if mapped != "processing":
                    return mapped
            return "processing"

        text = str(raw_status).strip().lower()
        if not text:
            return "pending"

        # Normalize Vietnamese accented text to plain ASCII for robust keyword checks.
        normalized = unicodedata.normalize("NFKD", text)
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        normalized = " ".join(normalized.split())

        if normalized.isdigit() or (normalized.startswith("-") and normalized[1:].isdigit()):
            return cls.PANCAKE_TO_LOCAL_STATUS.get(int(normalized), "processing")

        # Accept mixed strings like "3 - da giao".
        number_match = re.search(r"-?\d+", normalized)
        if number_match:
            try:
                return cls.PANCAKE_TO_LOCAL_STATUS.get(int(number_match.group(0)), "processing")
            except Exception:
                pass

        if (
            "cancel" in normalized
            or "huy" in normalized
            or "fail" in normalized
            or "return" in normalized
            or "hoan tra" in normalized
            or "remove" in normalized
            or "deleted" in normalized
            or "xoa" in normalized
            or "da xoa" in normalized
        ):
            return "cancelled"
        if (
            "deliver" in normalized
            or "complete" in normalized
            or "success" in normalized
            or "hoan thanh" in normalized
            or "da giao" in normalized
        ):
            return "delivered"
        if "ship" in normalized or "transport" in normalized or "giao hang" in normalized or "van chuyen" in normalized:
            return "shipped"
        if "process" in normalized or "pack" in normalized or "confirm" in normalized or "xac nhan" in normalized:
            return "processing"
        if "pending" in normalized or "new" in normalized or "draft" in normalized or "cho" in normalized or "moi" in normalized:
            return "pending"

        return "processing"

    @staticmethod
    def verify_webhook_signature(body: bytes, signature_header: Optional[str], secret: Optional[str]) -> bool:
        if not secret:
            return True
        if not signature_header:
            return False

        candidate = signature_header.strip()
        if not candidate:
            return False

        if "," in candidate:
            pieces = [part.strip() for part in candidate.split(",") if part.strip()]
        else:
            pieces = [candidate]

        signatures: list[str] = []
        for piece in pieces:
            if "=" in piece:
                key, value = piece.split("=", 1)
                if key.strip().lower() in {"sha256", "v1", "sig", "signature"}:
                    signatures.append(value.strip())
                else:
                    signatures.append(piece.strip())
            else:
                signatures.append(piece)

        digest_hex = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        digest_prefixed = f"sha256={digest_hex}"

        for sig in signatures:
            if hmac.compare_digest(sig, digest_hex) or hmac.compare_digest(sig, digest_prefixed):
                return True
        return False

    @staticmethod
    def is_not_found_sync_error(error: Exception | str) -> bool:
        text = str(error or "").strip().lower()
        if not text:
            return False
        patterns = (
            "page not found",
            "not found",
            "cannot find",
            "does not exist",
            "khong ton tai",
        )
        return any(pattern in text for pattern in patterns)

    @staticmethod
    def is_permission_sync_error(error: Exception | str) -> bool:
        text = str(error or "").strip().lower()
        if not text:
            return False
        patterns = (
            "permission",
            "forbidden",
            "khong co quyen",
            "không có quyền",
            "ban khong co quyen",
            "bạn không có quyền",
            "khong duoc phep",
            "không được phép",
            "not allowed",
        )
        return any(pattern in text for pattern in patterns)

    async def update_order_status(
        self,
        *,
        pancake_order_id: str,
        local_status: str,
        pancake_status: Optional[int] = None,
    ) -> dict[str, Any]:
        if not self.is_enabled():
            return {"skipped": True, "reason": "pancake-disabled"}

        if not self.is_configured():
            raise PancakeOrderSyncError("Pancake config missing: PANCAKE_API_KEY/PANCAKE_SHOP_ID")

        normalized_status = str(local_status or "").strip().lower() or "pending"
        resolved_pancake_status = int(pancake_status) if pancake_status is not None else self.local_status_to_pancake_status(normalized_status)

        url = f"{self.base_url}/shops/{self.shop_id}/orders/{pancake_order_id}"
        request_payload: dict[str, Any] = {
            "status": resolved_pancake_status,
            "order_status": resolved_pancake_status,
        }
        last_error: Optional[str] = None

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                response = await client.put(
                    url,
                    params={"api_key": self.api_key},
                    json=request_payload,
                )

                if response.status_code < 400:
                    data = response.json() if response.content else {}
                    if isinstance(data, dict) and data.get("success") is False:
                        last_error = str(data.get("error") or data.get("message") or "Pancake returned success=false")
                    else:
                        return data if isinstance(data, dict) else {"data": data}
                else:
                    last_error = response.text
            except Exception as exc:
                last_error = str(exc)

            # Fallback: update using latest Pancake order payload when server expects full order shape.
            detail = await self.get_order_detail(str(pancake_order_id))
            if isinstance(detail, dict):
                full_payload = dict(detail)
                if isinstance(full_payload.get("data"), dict) and self._looks_like_order_dict(full_payload.get("data")):
                    full_payload = dict(full_payload.get("data"))
                if isinstance(full_payload.get("order"), dict) and self._looks_like_order_dict(full_payload.get("order")):
                    full_payload = dict(full_payload.get("order"))

                full_payload["status"] = resolved_pancake_status
                full_payload["order_status"] = resolved_pancake_status
                try:
                    fallback_response = await client.put(
                        url,
                        params={"api_key": self.api_key},
                        json=full_payload,
                    )
                    if fallback_response.status_code < 400:
                        data = fallback_response.json() if fallback_response.content else {}
                        if isinstance(data, dict) and data.get("success") is False:
                            last_error = str(data.get("error") or data.get("message") or "Pancake returned success=false")
                        else:
                            return data if isinstance(data, dict) else {"data": data}
                    else:
                        last_error = fallback_response.text
                except Exception as exc:
                    last_error = str(exc)

        raise PancakeOrderSyncError(
            f"Unable to update Pancake order status for {pancake_order_id}: {last_error or 'unknown error'}"
        )

    async def get_order_detail(
        self,
        pancake_order_id: str,
        expected_custom_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if not self.is_enabled() or not self.is_configured():
            return None

        order_id = str(pancake_order_id or "").strip()
        if not order_id:
            return None

        request_candidates: list[tuple[str, dict[str, Any]]]= [
            (f"{self.base_url}/shops/{self.shop_id}/orders/{order_id}", {}),
            (f"{self.base_url}/shops/{self.shop_id}/orders/{order_id}", {"include_removed": 1}),
            (f"{self.base_url}/shops/{self.shop_id}/orders/{order_id}", {"with_items": 1}),
            (f"{self.base_url}/shops/{self.shop_id}/orders/{order_id}", {"include": "items"}),
            (f"{self.base_url}/shops/{self.shop_id}/orders/{order_id}", {"include_items": 1}),
            # Fallback with list API from Pancake OpenAPI; include removed to keep cancelled/deleted states in sync.
            (f"{self.base_url}/shops/{self.shop_id}/orders", {"search": order_id, "include_removed": 1, "page_size": 100}),
            (f"{self.base_url}/shops/{self.shop_id}/orders", {"search": order_id, "include_removed": 1, "page_size": 30}),
        ]

        async with httpx.AsyncClient(timeout=20.0) as client:
            for url, extra_params in request_candidates:
                try:
                    params = {"api_key": self.api_key, **extra_params}
                    response = await client.get(url, params=params)
                    if response.status_code >= 400:
                        continue

                    data = response.json() if response.content else None
                    parsed = self._extract_order_from_payload(
                        data,
                        order_id,
                        expected_custom_id=expected_custom_id,
                    )
                    if parsed is not None:
                        return parsed
                except Exception:
                    continue

        return None

    async def find_order_by_custom_id(self, custom_id: str) -> Optional[dict[str, Any]]:
        if not self.is_enabled() or not self.is_configured():
            return None

        target_custom_id = str(custom_id or "").strip()
        if not target_custom_id:
            return None

        url = f"{self.base_url}/shops/{self.shop_id}/orders"
        target_lower = target_custom_id.lower()

        async with httpx.AsyncClient(timeout=20.0) as client:
            for page_number in range(1, 6):
                params = {
                    "api_key": self.api_key,
                    "search": target_custom_id,
                    "include_removed": 1,
                    "page_size": 100,
                    "page_number": page_number,
                }

                try:
                    response = await client.get(url, params=params)
                    if response.status_code >= 400:
                        continue
                    payload = response.json() if response.content else None
                except Exception:
                    continue

                rows: list[dict[str, Any]] = []
                if isinstance(payload, dict):
                    data = payload.get("data")
                    if isinstance(data, list):
                        rows = [item for item in data if isinstance(item, dict)]
                    elif isinstance(data, dict):
                        rows = [data]
                elif isinstance(payload, list):
                    rows = [item for item in payload if isinstance(item, dict)]

                # 1) Strict exact match by custom_id/tracking_code fields.
                for item in rows:
                    item_custom_id = str(item.get("custom_id") or item.get("customId") or "").strip()
                    item_tracking = str(item.get("tracking_code") or item.get("trackingCode") or "").strip()
                    if not self._looks_like_order_dict(item):
                        continue
                    if item_custom_id.lower() == target_lower or item_tracking.lower() == target_lower:
                        return item

                # 2) Fallback: note may contain tracking code from our payload format.
                note_matches: list[dict[str, Any]] = []
                for item in rows:
                    if not self._looks_like_order_dict(item):
                        continue
                    note = str(item.get("note") or item.get("note_print") or "").strip().lower()
                    if target_lower and target_lower in note:
                        note_matches.append(item)

                if len(note_matches) == 1:
                    return note_matches[0]

                # 3) Last fallback: accept a contains match on custom_id/tracking fields if unique.
                contains_matches: list[dict[str, Any]] = []
                for item in rows:
                    if not self._looks_like_order_dict(item):
                        continue
                    item_custom_id = str(item.get("custom_id") or item.get("customId") or "").strip().lower()
                    item_tracking = str(item.get("tracking_code") or item.get("trackingCode") or "").strip().lower()
                    if target_lower and (
                        (item_custom_id and target_lower in item_custom_id)
                        or (item_tracking and target_lower in item_tracking)
                    ):
                        contains_matches.append(item)

                if len(contains_matches) == 1:
                    return contains_matches[0]

                # Stop early if result page already empty.
                if not rows:
                    break

        return None

    @staticmethod
    def _normalize_name(value: Optional[str]) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        normalized = unicodedata.normalize("NFKD", raw)
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return " ".join(normalized.split())

    @staticmethod
    def _extract_items(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            for key in (
                "data",
                "results",
                "items",
                "list",
                "rows",
                "addresses",
                "provinces",
                "districts",
                "communes",
                "wards",
            ):
                v = payload.get(key)
                if isinstance(v, list):
                    return [x for x in v if isinstance(x, dict)]
                if isinstance(v, dict):
                    nested = PancakeOrderService._extract_items(v)
                    if nested:
                        return nested
        return []

    @staticmethod
    def _normalize_address_item(item: dict[str, Any]) -> Optional[dict[str, Any]]:
        id_keys = (
            "id",
            "_id",
            "value",
            "code",
            "province_id",
            "district_id",
            "commune_id",
            "ward_id",
            "wards_id",
            "provinceId",
            "districtId",
            "communeId",
            "wardId",
        )
        name_keys = (
            "name",
            "title",
            "text",
            "label",
            "full_name",
            "province_name",
            "district_name",
            "commune_name",
            "ward_name",
        )

        raw_id = next((item.get(k) for k in id_keys if item.get(k) is not None), None)
        raw_name = next((item.get(k) for k in name_keys if item.get(k) is not None), None)

        if raw_id is None or raw_name is None:
            return None

        try:
            item_id = int(raw_id)
        except Exception:
            return None

        name = str(raw_name).strip()
        if not name:
            return None

        return {"id": item_id, "name": name}

    async def _fetch_address_list(self, candidates: list[str], params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        query = {"api_key": self.api_key}
        if params:
            query.update({k: v for k, v in params.items() if v is not None})

        async with httpx.AsyncClient(timeout=20.0) as client:
            for path in candidates:
                url = f"{self.base_url}{path}"
                try:
                    response = await client.get(url, params=query)
                    if response.status_code >= 400:
                        continue
                    payload = response.json()
                    items = self._extract_items(payload)
                    normalized = [self._normalize_address_item(item) for item in items]
                    result = [x for x in normalized if x is not None]
                    if result:
                        return result
                except Exception:
                    continue

        return []

    async def list_provinces(self) -> list[dict[str, Any]]:
        return await self._fetch_address_list(
            [
                "/provinces",
                "/locations/provinces",
                "/shipping-addresses/provinces",
                "/addresses/provinces",
                f"/shops/{self.shop_id}/provinces",
                f"/shops/{self.shop_id}/shipping-addresses/provinces",
                f"/shops/{self.shop_id}/addresses/provinces",
            ]
        )

    async def list_districts(self, province_id: Optional[int] = None) -> list[dict[str, Any]]:
        params = {"province_id": province_id, "provinceId": province_id}
        return await self._fetch_address_list(
            [
                "/districts",
                "/locations/districts",
                "/shipping-addresses/districts",
                "/addresses/districts",
                f"/shops/{self.shop_id}/districts",
                f"/shops/{self.shop_id}/shipping-addresses/districts",
                f"/shops/{self.shop_id}/addresses/districts",
            ],
            params=params,
        )

    async def list_communes(self, district_id: Optional[int] = None) -> list[dict[str, Any]]:
        params = {"district_id": district_id, "districtId": district_id}
        return await self._fetch_address_list(
            [
                "/communes",
                "/wards",
                "/locations/communes",
                "/locations/wards",
                "/shipping-addresses/communes",
                "/shipping-addresses/wards",
                "/addresses/communes",
                "/addresses/wards",
                f"/shops/{self.shop_id}/communes",
                f"/shops/{self.shop_id}/wards",
                f"/shops/{self.shop_id}/shipping-addresses/communes",
                f"/shops/{self.shop_id}/shipping-addresses/wards",
                f"/shops/{self.shop_id}/addresses/communes",
                f"/shops/{self.shop_id}/addresses/wards",
            ],
            params=params,
        )

    @staticmethod
    def _find_id_by_name(options: list[dict[str, Any]], target_name: Optional[str]) -> Optional[int]:
        target = PancakeOrderService._normalize_name(target_name)
        if not target:
            return None

        for option in options:
            candidate = PancakeOrderService._normalize_name(str(option.get("name") or ""))
            if candidate == target:
                return int(option["id"])

        for option in options:
            candidate = PancakeOrderService._normalize_name(str(option.get("name") or ""))
            if target in candidate or candidate in target:
                return int(option["id"])

        return None

    def _build_item_payload(
        self,
        item: OrderItem,
        product: Optional[Product],
        variant: Optional[ProductVariant],
    ) -> dict[str, Any]:
        pancake_variation_id = getattr(variant, "pancake_variation_id", None)
        if pancake_variation_id:
            return {
                "discount_each_product": 0,
                "is_bonus_product": False,
                "is_discount_percent": False,
                "is_wholesale": False,
                "one_time_product": False,
                "quantity": int(getattr(item, "quantity", 0) or 0),
                "variation_id": str(pancake_variation_id),
            }

        product_name = getattr(product, "name", None) or f"Product #{item.product_id}"
        product_sku = getattr(product, "sku", None) or f"PRODUCT-{item.product_id}"
        unit_price = float(getattr(item, "price", 0) or 0)
        safe_retail_price = max(1, int(round(unit_price)))

        # Use one_time_product to avoid requiring Pancake-side product/variation mapping IDs.
        return {
            "discount_each_product": 0,
            "is_bonus_product": False,
            "is_discount_percent": False,
            "is_wholesale": False,
            "one_time_product": True,
            "quantity": int(getattr(item, "quantity", 0) or 0),
            "variation_info": {
                "name": str(product_name),
                "retail_price": safe_retail_price,
                "weight": 0,
                "detail": str(product_sku),
                "fields": [],
            },
        }

    def build_create_order_payload(
        self,
        *,
        order: Order,
        items: list[OrderItem],
        products_by_id: dict[int, Product],
        variants_by_id: dict[int, ProductVariant],
        receiver_province_name: Optional[str] = None,
        receiver_district_name: Optional[str] = None,
        receiver_ward_name: Optional[str] = None,
    ) -> dict[str, Any]:
        shipping_fee_raw = getattr(order, "shipping_fee", 0)
        shipping_fee = int(shipping_fee_raw or 0)

        province_id = int(order.receiver_province_id) if order.receiver_province_id is not None else None
        district_id = int(order.receiver_district_id) if order.receiver_district_id is not None else None
        commune_id = int(order.receiver_ward_id) if order.receiver_ward_id is not None else None
        full_address = str(order.receiver_address or "").strip()
        post_code = None

        shipping_address = {
            "address": full_address,
            "full_address": full_address,
            "full_name": order.receiver_name,
            "phone_number": order.receiver_phone,
            "province_id": str(province_id) if province_id is not None else None,
            "district_id": str(district_id) if district_id is not None else None,
            "commune_id": str(commune_id) if commune_id is not None else None,
            "province_name": receiver_province_name,
            "district_name": receiver_district_name,
            "commune_name": receiver_ward_name,
            "country_code": "84",
            "post_code": post_code,
        }

        payload_items = [
            self._build_item_payload(
                item,
                products_by_id.get(int(item.product_id)),
                variants_by_id.get(int(item.product_variant_id)) if item.product_variant_id is not None else None,
            )
            for item in items
        ]

        payload: dict[str, Any] = {
            "shop_id": self.shop_id,
            "status": int(settings.PANCAKE_ORDER_STATUS),
            "bill_full_name": order.receiver_name,
            "bill_phone_number": order.receiver_phone,
            "bill_address": full_address,
            "bill_province_id": str(province_id) if province_id is not None else None,
            "bill_district_id": str(district_id) if district_id is not None else None,
            "bill_commune_id": str(commune_id) if commune_id is not None else None,
            "shipping_address": shipping_address,
            "items": payload_items,
            "total_discount": 0,
            "note": order.note or f"Lộc Sang order #{order.tracking_code or order.id}",
            "custom_id": order.tracking_code,
            "cash": 0,
            "is_free_shipping": True,
            "received_at_shop": False,
        }

        # User creates shipment manually in Pancake; only send shipping_fee when it is a positive value.
        if shipping_fee > 0:
            payload["shipping_fee"] = shipping_fee

        return payload

    async def create_order(
        self,
        *,
        order: Order,
        items: list[OrderItem],
        products_by_id: dict[int, Product],
        variants_by_id: dict[int, ProductVariant],
        receiver_province_name: Optional[str] = None,
        receiver_district_name: Optional[str] = None,
        receiver_ward_name: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self.is_enabled():
            return {"skipped": True, "reason": "pancake-disabled"}

        if not self.is_configured():
            raise PancakeOrderSyncError("Pancake config missing: PANCAKE_API_KEY/PANCAKE_SHOP_ID")

        # Resolve address ids from Pancake dictionaries before constructing payload.
        province_id = int(order.receiver_province_id) if order.receiver_province_id is not None else None
        district_id = int(order.receiver_district_id) if order.receiver_district_id is not None else None
        commune_id = int(order.receiver_ward_id) if order.receiver_ward_id is not None else None

        if receiver_province_name:
            provinces = await self.list_provinces()
            resolved = self._find_id_by_name(provinces, receiver_province_name)
            province_id = resolved

        if receiver_district_name:
            districts = await self.list_districts(province_id=province_id)
            resolved = self._find_id_by_name(districts, receiver_district_name)
            district_id = resolved

        if receiver_ward_name:
            communes = await self.list_communes(district_id=district_id)
            resolved = self._find_id_by_name(communes, receiver_ward_name)
            commune_id = resolved

        order.receiver_province_id = province_id
        order.receiver_district_id = district_id
        order.receiver_ward_id = commune_id

        payload = self.build_create_order_payload(
            order=order,
            items=items,
            products_by_id=products_by_id,
            variants_by_id=variants_by_id,
            receiver_province_name=receiver_province_name,
            receiver_district_name=receiver_district_name,
            receiver_ward_name=receiver_ward_name,
        )
        url = f"{self.base_url}/shops/{self.shop_id}/orders"

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(url, params={"api_key": self.api_key}, json=payload)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("success") is False:
                raise PancakeOrderSyncError(str(data.get("error") or data.get("message") or "Pancake returned success=false"))
            if isinstance(data, dict):
                return data
            return {"data": data}
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text if exc.response is not None else str(exc)
            raise PancakeOrderSyncError(f"Pancake rejected order: {detail}") from exc
        except Exception as exc:  # pragma: no cover
            self.logger.exception("Pancake order request failed for tracking_code=%s", getattr(order, "tracking_code", None))
            raise PancakeOrderSyncError(f"Pancake request failed: {exc}") from exc
