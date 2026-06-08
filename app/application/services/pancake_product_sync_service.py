from __future__ import annotations

import asyncio
import re
import unicodedata
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.domain.models.category import Category
from app.domain.models.order_item import OrderItem
from app.domain.models.product import (
    Product,
    ProductAttribute,
    ProductAttributeValue,
    ProductImage,
    ProductVariant,
    VariantAttributeValue,
)


class PancakeProductSyncError(Exception):
    pass


@dataclass
class PancakeSyncSummary:
    fetched_variations: int = 0
    fetched_combos: int = 0
    fetched_promotions: int = 0
    products_with_combo: int = 0
    products_with_promotions: int = 0
    promotions_with_targets: int = 0
    promotions_without_targets: int = 0
    products_with_active_promotions: int = 0
    created_products: int = 0
    updated_products: int = 0
    deleted_products: int = 0
    created_variants: int = 0
    updated_variants: int = 0
    inactivated_variants: int = 0


class PancakeProductSyncService:
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
    def _slugify(value: str) -> str:
        value = unicodedata.normalize("NFKD", value or "")
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = value.lower().strip()
        value = re.sub(r"[^a-z0-9\s-]", "", value)
        value = re.sub(r"[\s-]+", "-", value)
        return value.strip("-") or "product"

    @staticmethod
    def _normalize_field_name(name: str) -> str:
        n = unicodedata.normalize("NFKD", name or "")
        n = "".join(ch for ch in n if not unicodedata.combining(ch))
        return n.strip().lower()

    @staticmethod
    def _as_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _as_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "no", "n", "off", ""}:
                return False
        return bool(value)

    @staticmethod
    def _as_list_of_dicts(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _merge_unique_dict_lists(*sources: Any) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source in sources:
            for item in PancakeProductSyncService._as_list_of_dicts(source):
                marker = str(item)
                if marker in seen:
                    continue
                seen.add(marker)
                merged.append(item)
        return merged

    def _collect_combo_fields(self, pinfo: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        # Pancake may store bundle/combo data in product-level payload, promotion payload,
        # or variation-level rows depending on account configuration.
        promotions = self._merge_unique_dict_lists(
            pinfo.get("promotions"),
            *[row.get("promotions") for row in rows],
        )
        gift_products = self._merge_unique_dict_lists(
            pinfo.get("gift_products"),
            *[row.get("gift_products") for row in rows],
        )
        combo_products = self._merge_unique_dict_lists(
            pinfo.get("combo_products"),
            pinfo.get("combo_items"),
            pinfo.get("combo_variations"),
            *[row.get("combo_products") for row in rows],
            *[row.get("combo_items") for row in rows],
            *[row.get("combo_variations") for row in rows],
        )

        out: dict[str, Any] = {}
        if promotions:
            out["promotions"] = promotions
        if gift_products:
            out["gift_products"] = gift_products
        if combo_products:
            out["combo_products"] = combo_products
        return out

    @staticmethod
    def _as_text(value: Any) -> Optional[str]:
        text = str(value or "").strip()
        return text or None

    async def _fetch_combo_products(self) -> list[dict[str, Any]]:
        """Fetch combo definitions from Pancake's dedicated combo endpoint.

        This endpoint is optional across Pancake tenants; when unavailable,
        sync continues with variation payload only.
        """
        url = f"{self.base_url}/shops/{self.shop_id}/combo_products"
        params = {"api_key": self.api_key}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return []
            data = payload.get("data") or []
            if not isinstance(data, list):
                return []
            return [item for item in data if isinstance(item, dict)]
        except Exception as exc:
            self.logger.warning("Unable to fetch Pancake combo products: %s", exc)
            return []

    async def _fetch_promotion_advance(self, *, page_size: int = 100, max_pages: int = 20) -> list[dict[str, Any]]:
        """Fetch promotion definitions from Pancake promotion endpoint.

        Similar to combo endpoint, this is optional for some tenants and should
        not fail the whole sync process.
        """
        promotions: list[dict[str, Any]] = []
        page = 1

        while page <= max_pages:
            url = f"{self.base_url}/shops/{self.shop_id}/promotion_advance"
            params = {
                "api_key": self.api_key,
                "page": page,
                "page_size": page_size,
            }
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                self.logger.warning("Unable to fetch Pancake promotions page %s: %s", page, exc)
                break

            if not isinstance(payload, dict):
                break

            data = payload.get("data") or []
            if not isinstance(data, list):
                break

            valid_items = [item for item in data if isinstance(item, dict)]
            promotions.extend(valid_items)

            total_pages = self._as_int(payload.get("total_pages"), default=0)
            if len(valid_items) < page_size:
                break
            if total_pages and page >= total_pages:
                break

            page += 1

        return promotions

    def _extract_promotion_targets(
        self,
        source: Any,
        *,
        variation_to_product_id: dict[str, str],
    ) -> list[dict[str, Any]]:
        if not isinstance(source, list):
            return []

        targets: list[dict[str, Any]] = []
        for item in source:
            if not isinstance(item, dict):
                continue

            nested_product = item.get("product") if isinstance(item.get("product"), dict) else {}
            product_id = self._as_text(
                item.get("product_id")
                or item.get("pancake_product_id")
                or nested_product.get("product_id")
                or nested_product.get("pancake_product_id")
            )
            variation_id = self._as_text(
                item.get("variation_id")
                or item.get("variant_id")
                or nested_product.get("variation_id")
                or nested_product.get("variant_id")
            )
            if not product_id and variation_id:
                product_id = variation_to_product_id.get(variation_id)
            if not product_id:
                continue

            quantity = self._as_int(
                item.get("count")
                or item.get("quantity")
                or item.get("qty")
                or nested_product.get("count")
                or nested_product.get("quantity")
                or nested_product.get("qty"),
                1,
            ) or 1

            target_item: dict[str, Any] = {
                "product_id": str(product_id),
                "quantity": quantity,
            }
            if variation_id:
                target_item["variation_id"] = variation_id
            targets.append(target_item)

        return targets

    def _extract_promotion_targets_recursive(
        self,
        source: Any,
        *,
        variation_to_product_id: dict[str, str],
        depth: int = 0,
        parent_hint: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if depth > 8:
            return []

        targets: list[dict[str, Any]] = []

        if isinstance(source, list):
            for item in source:
                targets.extend(
                    self._extract_promotion_targets_recursive(
                        item,
                        variation_to_product_id=variation_to_product_id,
                        depth=depth + 1,
                        parent_hint=parent_hint,
                    )
                )
            return targets

        if not isinstance(source, dict):
            return []

        hint = str(parent_hint or "").lower()

        nested_product = source.get("product") if isinstance(source.get("product"), dict) else {}
        product_id = self._as_text(
            source.get("product_id")
            or source.get("pancake_product_id")
            or source.get("id_product")
            or nested_product.get("product_id")
            or nested_product.get("pancake_product_id")
            or nested_product.get("id_product")
        )
        variation_id = self._as_text(
            source.get("variation_id")
            or source.get("variant_id")
            or source.get("id_variation")
            or nested_product.get("variation_id")
            or nested_product.get("variant_id")
            or nested_product.get("id_variation")
        )

        # Many Pancake promotion payloads use generic `id` under context keys like
        # `products`, `items`, `bonus_items`, `free_products`, `variations`.
        raw_id = self._as_text(source.get("id"))
        if raw_id:
            if not variation_id and ("variation" in hint or "variant" in hint):
                variation_id = raw_id
            elif not product_id and any(token in hint for token in ("product", "item", "bonus", "free", "goods", "gift")):
                product_id = raw_id

        if not product_id and variation_id:
            product_id = variation_to_product_id.get(variation_id)

        if product_id:
            quantity = self._as_int(
                source.get("count")
                or source.get("quantity")
                or source.get("qty")
                or source.get("products_count")
                or nested_product.get("count")
                or nested_product.get("quantity")
                or nested_product.get("qty"),
                1,
            ) or 1

            target_item: dict[str, Any] = {
                "product_id": str(product_id),
                "quantity": quantity,
            }
            if variation_id:
                target_item["variation_id"] = variation_id
            targets.append(target_item)

        for key, value in source.items():
            if isinstance(value, (dict, list)):
                targets.extend(
                    self._extract_promotion_targets_recursive(
                        value,
                        variation_to_product_id=variation_to_product_id,
                        depth=depth + 1,
                        parent_hint=str(key),
                    )
                )

        return targets

    def _build_promotions_by_product(
        self,
        *,
        promotion_products: list[dict[str, Any]],
        grouped_rows: dict[str, list[dict[str, Any]]],
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
        """Map promotion definitions to source products.

        The mapped promotion list is merged into `pancake_payload.promotions`
        so storefront endpoints can reuse existing combo/promotion candidate parsing.
        """
        variation_to_product_id: dict[str, str] = {}
        known_product_ids: set[str] = {str(pid) for pid in grouped_rows.keys()}
        product_code_to_product_id: dict[str, str] = {}
        product_display_id_to_product_id: dict[str, str] = {}
        variation_display_id_to_product_id: dict[str, str] = {}
        product_name_to_product_id: dict[str, str] = {}
        for product_id, rows in grouped_rows.items():
            for row in rows:
                variation_id = self._as_text(row.get("id"))
                if variation_id:
                    variation_to_product_id[variation_id] = product_id

                product_obj = row.get("product") if isinstance(row.get("product"), dict) else {}
                product_code = self._as_text(
                    product_obj.get("code")
                    or product_obj.get("product_code")
                    or product_obj.get("barcode")
                    or row.get("code")
                    or row.get("sku")
                )
                if product_code:
                    product_code_to_product_id[product_code] = str(product_id)

                product_display_id = self._as_text(product_obj.get("display_id") or product_obj.get("id_display"))
                if product_display_id:
                    product_display_id_to_product_id[product_display_id] = str(product_id)

                variation_display_id = self._as_text(row.get("display_id") or row.get("id_display"))
                if variation_display_id:
                    variation_display_id_to_product_id[variation_display_id] = str(product_id)

                product_name = self._as_text(product_obj.get("name"))
                if product_name:
                    product_name_to_product_id[product_name.strip().lower()] = str(product_id)

        promotions_by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
        promotions_with_targets = 0
        promotions_without_targets = 0

        for raw_promotion in promotion_products:
            promotion_obj = (
                raw_promotion.get("promotion_product")
                if isinstance(raw_promotion.get("promotion_product"), dict)
                else raw_promotion
            )
            if not isinstance(promotion_obj, dict):
                continue

            promo_name = self._as_text(promotion_obj.get("name")) or self._as_text(raw_promotion.get("name"))
            promo_id = (
                self._as_text(promotion_obj.get("id"))
                or self._as_text(raw_promotion.get("id"))
                or self._as_text(raw_promotion.get("promotion_id"))
            )

            raw_targets: list[dict[str, Any]] = []
            for key in (
                "variations",
                "items",
                "products",
                "combo_products",
                "combo_items",
                "gift_products",
                "bonus_items",
                "bonus_products",
                "free_products",
                "applied_products",
            ):
                raw_targets.extend(
                    self._extract_promotion_targets(
                        promotion_obj.get(key),
                        variation_to_product_id=variation_to_product_id,
                    )
                )

            raw_targets.extend(
                self._extract_promotion_targets_recursive(
                    promotion_obj,
                    variation_to_product_id=variation_to_product_id,
                )
            )

            # Fallback: scan all scalar values in the promotion payload and map by
            # known product ids, variation ids, or product codes from synced rows.
            stack: list[Any] = [promotion_obj]
            while stack:
                current = stack.pop()
                if isinstance(current, dict):
                    stack.extend(current.values())
                    continue
                if isinstance(current, list):
                    stack.extend(current)
                    continue

                token = self._as_text(current)
                if not token:
                    continue

                if token in known_product_ids:
                    raw_targets.append({"product_id": token, "quantity": 1})
                    continue

                mapped_pid = variation_to_product_id.get(token)
                if mapped_pid:
                    raw_targets.append({"product_id": str(mapped_pid), "variation_id": token, "quantity": 1})
                    continue

                mapped_by_code = product_code_to_product_id.get(token)
                if mapped_by_code:
                    raw_targets.append({"product_id": str(mapped_by_code), "quantity": 1})
                    continue

                mapped_by_product_display = product_display_id_to_product_id.get(token)
                if mapped_by_product_display:
                    raw_targets.append({"product_id": str(mapped_by_product_display), "quantity": 1})
                    continue

                mapped_by_variation_display = variation_display_id_to_product_id.get(token)
                if mapped_by_variation_display:
                    raw_targets.append({"product_id": str(mapped_by_variation_display), "quantity": 1})
                    continue

                mapped_by_name = product_name_to_product_id.get(token.strip().lower())
                if mapped_by_name:
                    raw_targets.append({"product_id": str(mapped_by_name), "quantity": 1})

            unique_targets: list[dict[str, Any]] = []
            seen_targets: set[str] = set()
            for target in raw_targets:
                marker = str((target.get("product_id"), target.get("variation_id"), target.get("quantity")))
                if marker in seen_targets:
                    continue
                seen_targets.add(marker)
                unique_targets.append(target)

            if not unique_targets:
                promotions_without_targets += 1
                continue

            promotions_with_targets += 1

            promotion_template = dict(promotion_obj)
            if promo_name:
                promotion_template.setdefault("name", promo_name)
            if promo_id:
                promotion_template.setdefault("id", promo_id)

            for base in unique_targets:
                base_pid = str(base.get("product_id"))
                companions = [
                    item
                    for item in unique_targets
                    if not (
                        str(item.get("product_id")) == base_pid
                        and self._as_text(item.get("variation_id")) == self._as_text(base.get("variation_id"))
                    )
                ]

                mapped_promotion = dict(promotion_template)
                mapped_promotion["items"] = companions if companions else unique_targets
                promotions_by_product[base_pid].append(mapped_promotion)

        for product_id, items in list(promotions_by_product.items()):
            unique_promotions: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in items:
                marker = str(item)
                if marker in seen:
                    continue
                seen.add(marker)
                unique_promotions.append(item)
            promotions_by_product[product_id] = unique_promotions

        return promotions_by_product, {
            "promotions_with_targets": promotions_with_targets,
            "promotions_without_targets": promotions_without_targets,
        }

    async def _fetch_active_promotions_for_variation(self, row: dict[str, Any]) -> set[str]:
        product_id = self._as_text(row.get("product_id"))
        variation_id = self._as_text(row.get("id"))
        if not product_id or not variation_id:
            return set()

        url = f"{self.base_url}/shops/{self.shop_id}/orders/get_promotion_advance_active"
        item_payload: dict[str, Any] = {
            "product_id": product_id,
            "variation_id": variation_id,
            "quantity": 1,
        }
        retail_price = self._as_float(row.get("retail_price") or row.get("price_at_counter"), 0.0)
        if retail_price > 0:
            item_payload["variation_info"] = {"retail_price": retail_price}

        payload = {
            "order": {
                "shop_id": int(self.shop_id),
                "items": [item_payload],
            }
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    params={"api_key": self.api_key},
                    json=payload,
                )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            self.logger.warning(
                "Unable to evaluate active promotion for product_id=%s variation_id=%s: %s",
                product_id,
                variation_id,
                exc,
            )
            return set()

        promotion_ids: set[str] = set()

        def _walk(value: Any) -> None:
            if isinstance(value, dict):
                promotion_id = self._as_text(value.get("promotion_advance_id") or value.get("promotion_id"))
                if promotion_id:
                    promotion_ids.add(promotion_id)
                for child in value.values():
                    _walk(child)
            elif isinstance(value, list):
                for child in value:
                    _walk(child)

        _walk(data)
        return promotion_ids

    async def _build_active_promotions_by_product(
        self,
        *,
        grouped_rows: dict[str, list[dict[str, Any]]],
        promotion_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        rows_to_check: list[tuple[str, dict[str, Any]]] = []
        for product_id, rows in grouped_rows.items():
            rows_to_check.extend((str(product_id), row) for row in rows)

        semaphore = asyncio.Semaphore(10)

        async def _one(product_id: str, row: dict[str, Any]) -> tuple[str, dict[str, Any], set[str]]:
            async with semaphore:
                found = await self._fetch_active_promotions_for_variation(row)
            return product_id, row, found

        results = await asyncio.gather(*[_one(pid, row) for pid, row in rows_to_check]) if rows_to_check else []

        by_product: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

        for product_id, row, promotion_ids in results:
            if not promotion_ids:
                continue

            variation_id = self._as_text(row.get("id"))
            for promotion_id in promotion_ids:
                base = dict(promotion_by_id.get(promotion_id) or {"id": promotion_id, "name": f"Promotion {promotion_id}"})
                items = base.get("items") if isinstance(base.get("items"), list) else []
                item_marker = {
                    "product_id": product_id,
                    "variation_id": variation_id,
                    "quantity": 1,
                }
                items = self._merge_unique_dict_lists(items, [item_marker])
                base["items"] = items
                by_product[product_id][promotion_id] = base

        normalized: dict[str, list[dict[str, Any]]] = {}
        for product_id, promotions in by_product.items():
            normalized[product_id] = list(promotions.values())
        return normalized

    def _build_combo_items_by_product(
        self,
        *,
        combo_products: list[dict[str, Any]],
        grouped_rows: dict[str, list[dict[str, Any]]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Map combo definitions to each source product id.

        Returned structure is merged into each product `pancake_payload` so
        public API can build storefront `comboOffers`.
        """
        variation_to_product_id: dict[str, str] = {}
        for product_id, rows in grouped_rows.items():
            for row in rows:
                variation_id = self._as_text(row.get("id"))
                if variation_id:
                    variation_to_product_id[variation_id] = product_id

        combo_items_by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for raw_combo in combo_products:
            combo_obj = raw_combo.get("combo_product") if isinstance(raw_combo.get("combo_product"), dict) else raw_combo

            combo_name = self._as_text(combo_obj.get("name")) or self._as_text(raw_combo.get("name"))
            combo_id = (
                self._as_text(combo_obj.get("id"))
                or self._as_text(raw_combo.get("id"))
                or self._as_text(raw_combo.get("combo_product_id"))
            )

            variations = combo_obj.get("variations")
            if not isinstance(variations, list):
                continue

            normalized_targets: list[dict[str, Any]] = []
            for item in variations:
                if not isinstance(item, dict):
                    continue
                product_id = self._as_text(item.get("product_id"))
                variation_id = self._as_text(item.get("variation_id"))
                if not product_id and variation_id:
                    product_id = variation_to_product_id.get(variation_id)
                if not product_id:
                    continue
                normalized_targets.append(
                    {
                        "product_id": product_id,
                        "variation_id": variation_id,
                        "quantity": self._as_int(item.get("count"), 1) or 1,
                    }
                )

            if len(normalized_targets) < 2:
                continue

            for base in normalized_targets:
                base_pid = str(base.get("product_id"))
                for companion in normalized_targets:
                    companion_pid = str(companion.get("product_id"))
                    if companion_pid == base_pid:
                        continue
                    combo_item = {
                        "product_id": companion_pid,
                        "variation_id": companion.get("variation_id"),
                        "quantity": self._as_int(companion.get("quantity"), 1) or 1,
                    }
                    if combo_name:
                        combo_item["combo_name"] = combo_name
                    if combo_id:
                        combo_item["combo_id"] = combo_id
                    combo_items_by_product[base_pid].append(combo_item)

        # De-duplicate repeated companion rows that may appear across source payloads.
        for product_id, items in list(combo_items_by_product.items()):
            unique: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in items:
                marker = str(
                    (
                        item.get("combo_id"),
                        item.get("product_id"),
                        item.get("variation_id"),
                        item.get("quantity"),
                    )
                )
                if marker in seen:
                    continue
                seen.add(marker)
                unique.append(item)
            combo_items_by_product[product_id] = unique

        return combo_items_by_product

    async def _fetch_variations_page(self, *, page: int, page_size: int) -> dict[str, Any]:
        url = f"{self.base_url}/shops/{self.shop_id}/products/variations"
        params = {
            "api_key": self.api_key,
            "page": page,
            "page_size": page_size,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text if exc.response is not None else str(exc)
            raise PancakeProductSyncError(f"Pancake products API returned an error: {detail}") from exc
        except Exception as exc:
            raise PancakeProductSyncError(f"Failed to fetch Pancake products: {exc}") from exc

        if not isinstance(payload, dict):
            raise PancakeProductSyncError("Unexpected Pancake response format for products")
        if payload.get("success") is False:
            raise PancakeProductSyncError(str(payload.get("error") or payload.get("message") or "Pancake returned success=false"))
        return payload

    async def fetch_variations(self, *, max_pages: int, page_size: int) -> list[dict[str, Any]]:
        variations: list[dict[str, Any]] = []
        page = 1
        while page <= max_pages:
            payload = await self._fetch_variations_page(page=page, page_size=page_size)
            data = payload.get("data") or []
            if not isinstance(data, list):
                raise PancakeProductSyncError("Pancake products data is not a list")

            valid_items = [item for item in data if isinstance(item, dict)]
            variations.extend(valid_items)

            total_pages = self._as_int(payload.get("total_pages"), default=0)
            if len(valid_items) < page_size:
                break
            if total_pages and page >= total_pages:
                break
            page += 1

        return variations

    async def _get_or_create_category(self, db: AsyncSession, name: str) -> Category:
        normalized = (name or "").strip() or "Pancake"
        found = (await db.execute(select(Category).where(Category.name == normalized))).scalar_one_or_none()
        if found:
            return found

        slug_base = f"pancake-{self._slugify(normalized)}"
        slug = slug_base
        suffix = 2
        while (await db.execute(select(Category).where(Category.slug == slug))).scalar_one_or_none() is not None:
            slug = f"{slug_base}-{suffix}"
            suffix += 1

        category = Category(name=normalized, slug=slug, is_active=True)
        db.add(category)
        await db.flush()
        return category

    async def _build_product_slug(
        self,
        db: AsyncSession,
        *,
        name: str,
        pancake_product_id: str,
        code: Optional[str] = None,
        exclude_product_id: Optional[int] = None,
    ) -> str:
        # SEO-first slug: prioritize human-readable product name, then code, finally stable Pancake id.
        base_name = self._slugify(name)
        code_slug = self._slugify(str(code or "")) if code else ""

        candidates: list[str] = []
        if base_name and code_slug:
            candidates.append(f"{base_name}-{code_slug}")
        if base_name:
            candidates.append(base_name)
        if code_slug:
            candidates.append(code_slug)
        candidates.append(f"pancake-{self._slugify(str(pancake_product_id))}")

        for candidate in candidates:
            existing = (await db.execute(select(Product).where(Product.slug == candidate))).scalar_one_or_none()
            if existing is None:
                return candidate
            if exclude_product_id is not None and int(existing.id) == int(exclude_product_id):
                return candidate

        fallback_base = candidates[-1]
        suffix = 2
        while True:
            slug = f"{fallback_base}-{suffix}"
            existing = (await db.execute(select(Product).where(Product.slug == slug))).scalar_one_or_none()
            if existing is None:
                return slug
            if exclude_product_id is not None and int(existing.id) == int(exclude_product_id):
                return slug
            suffix += 1

    async def _upsert_product(
        self,
        db: AsyncSession,
        *,
        pancake_product_id: str,
        rows: list[dict[str, Any]],
        combo_items: Optional[list[dict[str, Any]]] = None,
        promotion_items: Optional[list[dict[str, Any]]] = None,
    ) -> tuple[Product, bool]:
        first = rows[0]
        pinfo = (first.get("product") or {}) if isinstance(first.get("product"), dict) else {}

        name = str(pinfo.get("name") or f"Pancake Product {pancake_product_id}").strip()
        product_code = str(
            pinfo.get("code")
            or pinfo.get("product_code")
            or pinfo.get("barcode")
            or ""
        ).strip() or None

        slug = await self._build_product_slug(
            db,
            name=name,
            pancake_product_id=pancake_product_id,
            code=product_code,
        )

        category_name = "Pancake"
        categories = pinfo.get("categories")
        if isinstance(categories, list) and categories:
            first_cat = categories[0]
            if isinstance(first_cat, dict):
                category_name = str(first_cat.get("name") or first_cat.get("note") or "Pancake")
            elif isinstance(first_cat, str):
                category_name = first_cat

        category = await self._get_or_create_category(db, category_name)

        existing = (
            await db.execute(select(Product).where(Product.pancake_product_id == str(pancake_product_id)))
        ).scalar_one_or_none()
        if existing is None:
            existing = (await db.execute(select(Product).where(Product.slug == slug))).scalar_one_or_none()

        if existing is not None:
            slug = await self._build_product_slug(
                db,
                name=name,
                pancake_product_id=pancake_product_id,
                code=product_code,
                exclude_product_id=int(existing.id),
            )

        prices = [self._as_float(r.get("retail_price"), 0.0) for r in rows]
        stocks = [self._as_int(r.get("remain_quantity"), 0) for r in rows]
        weights = [self._as_float(r.get("weight"), 0.0) for r in rows]

        # Some deployed DBs keep shipping fields as NOT NULL; keep safe defaults.
        shipping_weight = max(weights) if weights else 0.0
        shipping_length = 0.0
        shipping_width = 0.0
        shipping_height = 0.0

        tags_raw = pinfo.get("tags") if isinstance(pinfo.get("tags"), list) else []
        tags = []
        for t in tags_raw:
            if isinstance(t, dict) and t.get("note"):
                tags.append(str(t.get("note")))
            elif isinstance(t, str):
                tags.append(t)

        # Determine product visibility from both variant-level and product-level flags.
        # Some Pancake payloads mark product lock/inactive on `product` object, not each variation row.
        all_hidden = all(self._as_bool(r.get("is_hidden"), False) for r in rows)
        product_hidden = self._as_bool(pinfo.get("is_hidden"), False)
        product_locked = self._as_bool(pinfo.get("is_locked"), False)
        product_is_active_flag = pinfo.get("is_active")
        product_inactive_by_flag = (product_is_active_flag is not None and not self._as_bool(product_is_active_flag, True))
        product_status = str(pinfo.get("status") or "").strip().lower()
        product_inactive_by_status = product_status in {"inactive", "hidden", "locked", "disabled"}

        product_should_inactive = (
            all_hidden
            or product_hidden
            or product_locked
            or product_inactive_by_flag
            or product_inactive_by_status
        )
        status = "inactive" if product_should_inactive else "active"
        is_active = not product_should_inactive

        supplier_name = str(
            pinfo.get("supplier_name")
            or pinfo.get("supplier")
            or pinfo.get("provider_name")
            or ""
        ).strip() or None
        internal_note = str(pinfo.get("internal_note") or pinfo.get("note") or "").strip() or None
        product_description = str(pinfo.get("note_product") or pinfo.get("description") or "").strip() or None

        # Keep the full source payload, and enrich it with consistent helper fields for UI/SEO consumption.
        enriched_payload = dict(pinfo)
        combo_fields = self._collect_combo_fields(pinfo, rows)
        if combo_items:
            combo_fields["combo_products"] = self._merge_unique_dict_lists(
                combo_fields.get("combo_products"),
                combo_items,
            )
        if promotion_items:
            combo_fields["promotions"] = self._merge_unique_dict_lists(
                combo_fields.get("promotions"),
                promotion_items,
            )
        for key, value in combo_fields.items():
            enriched_payload[key] = value
        enriched_payload.setdefault("_seo_slug", slug)
        if product_code:
            enriched_payload.setdefault("_normalized_code", product_code)
        if supplier_name:
            enriched_payload.setdefault("_normalized_supplier", supplier_name)
        if internal_note:
            enriched_payload.setdefault("_normalized_internal_note", internal_note)

        if existing is None:
            product = Product(
                name=name,
                slug=slug,
                short_description=internal_note,
                description=product_description,
                status=status,
                featured=False,
                tags=tags,
                has_variants=len(rows) > 1,
                price=min(prices) if prices else 0.0,
                sku=product_code or f"PK-PROD-{pancake_product_id}",
                pancake_product_id=str(pancake_product_id),
                pancake_payload=enriched_payload,
                is_active=is_active,
                stock=sum(stocks),
                weight=shipping_weight,
                length=shipping_length,
                width=shipping_width,
                height=shipping_height,
                thumbnail=str(pinfo.get("image") or "") or None,
                category_id=category.id,
                currency="VND",
                brand=supplier_name,
            )
            db.add(product)
            await db.flush()
            return product, True

        existing.name = name
        existing.slug = slug
        existing.short_description = internal_note
        existing.description = product_description
        existing.status = status
        existing.is_active = is_active
        existing.tags = tags
        existing.has_variants = len(rows) > 1
        existing.price = min(prices) if prices else 0.0
        if product_code and (not existing.sku or str(existing.sku).startswith("PK-PROD-")):
            existing.sku = product_code
        existing.stock = sum(stocks)
        existing.deleted_at = None
        existing.weight = shipping_weight
        existing.length = shipping_length
        existing.width = shipping_width
        existing.height = shipping_height
        existing.thumbnail = str(pinfo.get("image") or "") or None
        existing.pancake_product_id = str(pancake_product_id)
        existing.pancake_payload = enriched_payload
        existing.category_id = category.id
        existing.currency = "VND"
        existing.brand = supplier_name
        return existing, False

    async def _replace_product_images(self, db: AsyncSession, product: Product, rows: list[dict[str, Any]]) -> None:
        existing_images = (await db.execute(select(ProductImage).where(ProductImage.product_id == product.id))).scalars().all()
        for img in existing_images:
            await db.delete(img)

        urls: list[str] = []
        if product.thumbnail:
            urls.append(product.thumbnail)

        for row in rows:
            imgs = row.get("images")
            if isinstance(imgs, list):
                for u in imgs:
                    if isinstance(u, str) and u.strip():
                        urls.append(u.strip())

        seen = set()
        unique_urls = []
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            unique_urls.append(u)

        for idx, url in enumerate(unique_urls, start=1):
            db.add(
                ProductImage(
                    product_id=product.id,
                    url=url,
                    type="image",
                    sort_order=idx,
                    is_primary=(idx == 1),
                )
            )

    def _build_variant_sku(self, pancake_product_id: str, row: dict[str, Any], idx: int) -> str:
        variation_id = str(row.get("id") or "").strip()
        if variation_id:
            return f"PK-VAR-{variation_id}"

        display_id = str(row.get("display_id") or "").strip()
        if display_id:
            return f"PK-VAR-{pancake_product_id}-{display_id}"

        return f"PK-VAR-{pancake_product_id}-{idx}"

    def _extract_size_color_material(self, row: dict[str, Any]) -> tuple[Optional[str], Optional[str], Optional[str]]:
        size = None
        color = None
        material = None

        fields = row.get("fields")
        if not isinstance(fields, list):
            return size, color, material

        for field in fields:
            if not isinstance(field, dict):
                continue
            name = self._normalize_field_name(str(field.get("name") or ""))
            value = str(field.get("value") or "").strip() or None
            if value is None:
                continue
            if name in ("size", "kich co"):
                size = value
            elif name in ("mau", "color", "colour"):
                color = value
            elif name in ("chat lieu", "material"):
                material = value

        return size, color, material

    def _extract_variant_attributes(self, row: dict[str, Any]) -> Dict[str, str]:
        fields = row.get("fields")
        if not isinstance(fields, list):
            return {}

        attributes: Dict[str, str] = {}
        for field in fields:
            if not isinstance(field, dict):
                continue
            name = str(field.get("name") or "").strip()
            value = str(field.get("value") or "").strip()
            if not name or not value:
                continue
            attributes[name] = value

        return attributes

    @staticmethod
    def _build_variant_display_name(attributes: Dict[str, str], *, fallback_sku: str) -> str:
        if attributes:
            values = [str(v).strip() for v in attributes.values() if str(v).strip()]
            if values:
                return " / ".join(values)
        return fallback_sku

    async def _sync_variant_attribute_values(
        self,
        db: AsyncSession,
        *,
        product: Product,
        variant: ProductVariant,
        attributes: Dict[str, str],
        attribute_by_name: Dict[str, ProductAttribute],
        value_id_by_pair: Dict[tuple[str, str], int],
    ) -> None:
        if variant.id is None:
            await db.flush()

        existing_links = (
            await db.execute(select(VariantAttributeValue).where(VariantAttributeValue.variant_id == variant.id))
        ).scalars().all()
        link_by_attribute_id = {int(link.attribute_id): link for link in existing_links}
        keep_attribute_ids: set[int] = set()

        for attr_name, attr_value in attributes.items():
            attribute = attribute_by_name.get(attr_name)
            if attribute is None:
                attribute = ProductAttribute(product_id=int(product.id), name=attr_name)
                db.add(attribute)
                await db.flush()
                attribute_by_name[attr_name] = attribute

            pair = (attr_name, attr_value)
            value_id = value_id_by_pair.get(pair)
            if value_id is None:
                new_value = ProductAttributeValue(attribute_id=int(attribute.id), value=attr_value)
                db.add(new_value)
                await db.flush()
                value_id = int(new_value.id)
                value_id_by_pair[pair] = value_id

            keep_attribute_ids.add(int(attribute.id))
            existing_link = link_by_attribute_id.get(int(attribute.id))
            if existing_link is None:
                db.add(
                    VariantAttributeValue(
                        variant_id=int(variant.id),
                        attribute_id=int(attribute.id),
                        attribute_value_id=int(value_id),
                    )
                )
            else:
                existing_link.attribute_value_id = int(value_id)

        for existing in existing_links:
            if int(existing.attribute_id) not in keep_attribute_ids:
                await db.delete(existing)

    async def _upsert_variants(
        self,
        db: AsyncSession,
        *,
        product: Product,
        pancake_product_id: str,
        rows: list[dict[str, Any]],
    ) -> tuple[int, int, int]:
        created = 0
        updated = 0
        inactivated = 0
        synced_variant_ids: set[int] = set()

        existing_variants = (
            await db.execute(select(ProductVariant).where(ProductVariant.product_id == product.id))
        ).scalars().all()
        by_sku = {v.sku: v for v in existing_variants}
        by_pancake_variation_id = {
            str(v.pancake_variation_id): v
            for v in existing_variants
            if getattr(v, "pancake_variation_id", None)
        }

        product_attributes = (
            await db.execute(
                select(ProductAttribute)
                .where(ProductAttribute.product_id == int(product.id))
                .options(selectinload(ProductAttribute.values))
            )
        ).scalars().all()
        attribute_by_name: Dict[str, ProductAttribute] = {a.name: a for a in product_attributes}
        value_id_by_pair: Dict[tuple[str, str], int] = {}
        for a in product_attributes:
            for v in a.values:
                value_id_by_pair[(a.name, v.value)] = int(v.id)

        for idx, row in enumerate(rows, start=1):
            sku = self._build_variant_sku(pancake_product_id, row, idx)
            pancake_variation_id = str(row.get("id") or "").strip() or None
            price = self._as_float(row.get("retail_price") or row.get("price_at_counter"), 0.0)
            stock = self._as_int(row.get("remain_quantity"), 0)
            status = "inactive" if bool(row.get("is_hidden")) else "active"
            is_active = status == "active"

            imgs = row.get("images") if isinstance(row.get("images"), list) else []
            image_url = None
            for u in imgs:
                if isinstance(u, str) and u.strip():
                    image_url = u.strip()
                    break

            variant_attributes = self._extract_variant_attributes(row)
            size, color, material = self._extract_size_color_material(row)
            if not size:
                size = variant_attributes.get("Size") or variant_attributes.get("Kích cỡ") or variant_attributes.get("Kich co")
            if not color:
                color = variant_attributes.get("Màu") or variant_attributes.get("Mau") or variant_attributes.get("Color")
            if not material:
                material = variant_attributes.get("Chất liệu") or variant_attributes.get("Chat lieu") or variant_attributes.get("Material")

            variant = by_pancake_variation_id.get(pancake_variation_id) if pancake_variation_id else None
            if variant is None:
                variant = by_sku.get(sku)
            if variant is None:
                # Handle existing variant that might belong to another product to avoid unique constraint crashes.
                if pancake_variation_id:
                    variant = (
                        await db.execute(
                            select(ProductVariant).where(ProductVariant.pancake_variation_id == pancake_variation_id)
                        )
                    ).scalar_one_or_none()
                if variant is None:
                    variant = (await db.execute(select(ProductVariant).where(ProductVariant.sku == sku))).scalar_one_or_none()
                if variant is not None:
                    by_sku[sku] = variant
                    if pancake_variation_id:
                        by_pancake_variation_id[pancake_variation_id] = variant
            if variant is None:
                variant = ProductVariant(
                    product_id=product.id,
                    sku=sku,
                    pancake_variation_id=pancake_variation_id,
                    pancake_payload=row,
                    price=price,
                    stock=stock,
                    status=status,
                    is_active=is_active,
                    manage_stock=True,
                    allow_backorder=bool(
                        row.get("is_sell_negative_variation")
                        or (product.pancake_payload or {}).get("is_sell_negative")
                    ),
                    image_url=image_url,
                    size=size,
                    color=color,
                    material=material,
                )
                db.add(variant)
                created += 1
            else:
                variant.product_id = product.id
                variant.pancake_variation_id = pancake_variation_id
                variant.pancake_payload = row
                variant.price = price
                variant.stock = stock
                variant.status = status
                variant.is_active = is_active
                variant.allow_backorder = bool(
                    row.get("is_sell_negative_variation")
                    or (product.pancake_payload or {}).get("is_sell_negative")
                )
                variant.image_url = image_url
                variant.size = size
                variant.color = color
                variant.material = material
                updated += 1

            await self._sync_variant_attribute_values(
                db,
                product=product,
                variant=variant,
                attributes=variant_attributes,
                attribute_by_name=attribute_by_name,
                value_id_by_pair=value_id_by_pair,
            )

            if variant.id is not None:
                synced_variant_ids.add(int(variant.id))

        # Inactivate stale variants that are no longer returned by Pancake for this product.
        # Hard delete is reserved for product deletion reconciliation.
        for existing in existing_variants:
            if int(existing.id) in synced_variant_ids:
                continue
            existing.status = "inactive"
            existing.is_active = False
            existing.stock = 0
            inactivated += 1

        return created, updated, inactivated

    def _group_by_product(self, variations: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in variations:
            product_id = str(row.get("product_id") or "").strip()
            if not product_id:
                continue
            grouped[product_id].append(row)
        return grouped

    async def _reconcile_removed_products(self, db: AsyncSession, synced_local_product_ids: set[int]) -> int:
        stmt = select(Product).where(Product.deleted_at.is_(None))
        if synced_local_product_ids:
            stmt = stmt.where(~Product.id.in_(list(synced_local_product_ids)))
        products = (await db.execute(stmt)).scalars().all()

        deleted_count = 0
        now = datetime.utcnow()

        for product in products:
            used_count = await db.scalar(
                select(func.count(OrderItem.id)).where(OrderItem.product_id == product.id)
            )
            if used_count and used_count > 0:
                # Preserve historical order integrity while removing product from active web catalog.
                product.deleted_at = now
                product.is_active = False
                product.status = "inactive"
                product.stock = 0
                product.updated_at = now
            else:
                await db.delete(product)
            deleted_count += 1

        return deleted_count

    async def sync(self, *, db: AsyncSession, max_pages: int, page_size: int) -> dict[str, Any]:
        if not self.is_enabled():
            raise PancakeProductSyncError("Pancake sync is disabled")
        if not self.is_configured():
            raise PancakeProductSyncError("Pancake config missing: PANCAKE_API_KEY/PANCAKE_SHOP_ID")

        variations = await self.fetch_variations(max_pages=max_pages, page_size=page_size)
        grouped = self._group_by_product(variations)
        combo_products = await self._fetch_combo_products()
        promotion_products = await self._fetch_promotion_advance(page_size=page_size, max_pages=max_pages)
        combo_items_by_product = self._build_combo_items_by_product(
            combo_products=combo_products,
            grouped_rows=grouped,
        )
        promotion_items_by_product, promotion_debug = self._build_promotions_by_product(
            promotion_products=promotion_products,
            grouped_rows=grouped,
        )

        promotion_by_id: dict[str, dict[str, Any]] = {}
        for promo in promotion_products:
            promo_obj = promo.get("promotion_product") if isinstance(promo.get("promotion_product"), dict) else promo
            if not isinstance(promo_obj, dict):
                continue
            pid = self._as_text(promo_obj.get("id") or promo.get("id") or promo.get("promotion_id"))
            if pid:
                promotion_by_id[pid] = dict(promo_obj)

        active_promotions_by_product = await self._build_active_promotions_by_product(
            grouped_rows=grouped,
            promotion_by_id=promotion_by_id,
        )

        for product_id, active_promotions in active_promotions_by_product.items():
            merged = self._merge_unique_dict_lists(
                promotion_items_by_product.get(product_id),
                active_promotions,
            )
            if merged:
                promotion_items_by_product[product_id] = merged
        synced_local_product_ids: set[int] = set()

        summary = PancakeSyncSummary(
            fetched_variations=len(variations),
            fetched_combos=len(combo_products),
            fetched_promotions=len(promotion_products),
            products_with_combo=len(combo_items_by_product),
            products_with_promotions=len(promotion_items_by_product),
            promotions_with_targets=self._as_int(promotion_debug.get("promotions_with_targets"), 0),
            promotions_without_targets=self._as_int(promotion_debug.get("promotions_without_targets"), 0),
            products_with_active_promotions=len(active_promotions_by_product),
        )
        try:
            for pancake_product_id, rows in grouped.items():
                product, created = await self._upsert_product(
                    db,
                    pancake_product_id=pancake_product_id,
                    rows=rows,
                    combo_items=combo_items_by_product.get(str(pancake_product_id)),
                    promotion_items=promotion_items_by_product.get(str(pancake_product_id)),
                )
                synced_local_product_ids.add(int(product.id))
                if created:
                    summary.created_products += 1
                else:
                    summary.updated_products += 1

                await self._replace_product_images(db, product, rows)
                c_variants, u_variants, i_variants = await self._upsert_variants(
                    db,
                    product=product,
                    pancake_product_id=pancake_product_id,
                    rows=rows,
                )
                summary.created_variants += c_variants
                summary.updated_variants += u_variants
                summary.inactivated_variants += i_variants

            summary.deleted_products = await self._reconcile_removed_products(
                db,
                synced_local_product_ids=synced_local_product_ids,
            )
        except SQLAlchemyError as exc:
            raise PancakeProductSyncError(f"Database error while syncing Pancake products: {exc}") from exc
        except Exception as exc:
            raise PancakeProductSyncError(f"Unexpected error while syncing Pancake products: {exc}") from exc

        return {
            "success": True,
            "summary": {
                "fetched_variations": summary.fetched_variations,
                "fetched_combos": summary.fetched_combos,
                "fetched_promotions": summary.fetched_promotions,
                "products_with_combo": summary.products_with_combo,
                "products_with_promotions": summary.products_with_promotions,
                "promotions_with_targets": summary.promotions_with_targets,
                "promotions_without_targets": summary.promotions_without_targets,
                "products_with_active_promotions": summary.products_with_active_promotions,
                "synced_products": len(grouped),
                "created_products": summary.created_products,
                "updated_products": summary.updated_products,
                "deleted_products": summary.deleted_products,
                "created_variants": summary.created_variants,
                "updated_variants": summary.updated_variants,
                "inactivated_variants": summary.inactivated_variants,
            },
        }
