from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.domain.models.home_content import HomeContent


router = APIRouter(prefix="/home-content", tags=["Public Home Content"])


def _default_home_payload() -> Dict[str, Any]:
    return {
        "hero_badge": "Yanmar Lộc Sang chính hãng",
        "hero_title": "Lộc Sang",
        "hero_headline_line1": "Phụ tùng & nhớt",
        "hero_headline_line2": "chính hãng Yanmar",
        "hero_subtitle": "Phụ tùng, lọc nhớt, lọc gió và dầu nhớt Yanmar",
        "hero_description": "Catalog hiển thị trực tiếp từ dữ liệu sản phẩm đang bán trong admin Lộc Sang.",
        "hero_image_url": "/locsang-assets/hero-yanmar.svg",
        "primary_cta_text": "Mua ngay",
        "primary_cta_link": "/products",
        "secondary_cta_text": "Liên hệ tư vấn",
        "secondary_cta_link": "/contact",
        "header_brand_name": "Lộc Sang",
        "header_brand_tagline": "Phụ tùng và nhớt Yanmar chính hãng",
        "header_nav_shop_text": "Cửa hàng",
        "header_nav_new_arrivals_text": "Hàng mới về",
        "header_nav_tips_text": "Cẩm nang",
        "header_nav_shorts_text": "Lộc Sang Shorts",
        "header_nav_orders_text": "Đơn hàng",
        "footer_brand_name": "Lộc Sang",
        "footer_desktop_caption": "Phụ tùng và nhớt Yanmar chính hãng, quản lý trực tiếp bởi Lộc Sang.",
        "footer_mobile_description": "Phụ tùng, lọc nhớt, lọc gió và dầu nhớt Yanmar chính hãng.",
        "footer_products_title": "sản phẩm",
        "footer_products_item_1": "Phụ tùng Yanmar",
        "footer_products_item_2": "Nhớt động cơ",
        "footer_products_item_3": "Lọc gió & lọc nhớt",
        "footer_products_item_4": "Dây curoa",
        "footer_info_title": "thông tin",
        "footer_info_item_1": "Thông tin giao hàng",
        "footer_info_item_2": "Chính sách đổi trả",
        "footer_info_item_3": "Hướng dẫn chọn phụ tùng",
        "footer_info_item_4": "Liên hệ Lộc Sang",
        "footer_social_title": "mạng xã hội",
        "footer_social_item_1": "Instagram",
        "footer_social_item_2": "Pinterest",
        "footer_social_item_3": "Facebook",
        "footer_social_item_4": "TikTok",
        "footer_social_instagram_url": "#",
        "footer_social_pinterest_url": "#",
        "footer_social_facebook_url": "#",
        "footer_social_tiktok_url": "#",
        "footer_policy_title": "Chính sách",
        "footer_policy_item_1": "Đổi trả 7 ngày",
        "footer_policy_item_2": "Bảo hành 6 tháng",
        "footer_policy_item_3": "Vận chuyển",
        "footer_contact_title": "Liên hệ",
        "footer_contact_hotline": "Hotline: 0966 201 140",
        "footer_contact_email": "Email: locsang@cgnn.vn",
        "footer_copyright_text": "© 2024 Lộc Sang. All rights reserved.",
        "hero_feature_1_title": "Chính hãng",
        "hero_feature_1_desc": "Sản phẩm Yanmar nhập và quản lý trực tiếp.",
        "hero_feature_2_title": "Dễ đặt hàng",
        "hero_feature_2_desc": "Khách chọn sản phẩm, admin xử lý đơn trong hệ thống.",
        "hero_feature_3_title": "Tồn kho rõ",
        "hero_feature_3_desc": "Hiển thị theo dữ liệu sản phẩm active.",
        "hero_stats_title": "Số liệu nhanh tại cửa hàng",
        "hero_stats_products_label": "Sản phẩm active",
        "hero_stats_categories_label": "Danh mục nổi bật",
        "hero_stats_price_label": "Khoảng giá hiện tại",
        "hero_stats_catalog_link_text": "Xem toàn bộ catalog",
        "category_section_title": "Danh mục đang chạy tốt",
        "category_section_desktop_title": "Mua sắm theo danh mục sản phẩm",
        "category_section_desktop_subtitle": "Danh mục lấy trực tiếp từ admin Lộc Sang",
        "category_section_link_text": "Xem toàn bộ cửa hàng",
        "mobile_category_title": "Danh mục",
        "category_section_subtitle": "Tự động gom từ dữ liệu sản phẩm active hiện tại.",
        "category_section_view_all_text": "Xem tất cả",
        "category_section_empty_text": "Chưa có dữ liệu danh mục từ hệ thống.",
        "category_section_loading_text": "Đang tải dữ liệu trang chủ...",
        "new_arrivals_title": "Sản phẩm mới lên kệ",
        "best_seller_section_title": "Sản Phẩm Bán Chạy",
        "best_seller_section_subtitle": "Những sản phẩm được khách hàng yêu thích nhất tại Lộc Sang.",
        "best_seller_badge_text": "Bán chạy nhất",
        "mobile_best_seller_title": "Bán Chạy Nhất",
        "mobile_view_all_text": "Xem tất cả",
        "new_arrivals_subtitle": "Hiển thị realtime theo dữ liệu public API.",
        "new_arrivals_live_badge": "Live data",
        "new_arrivals_price_prefix": "Mức giá hiện có từ",
        "new_arrivals_empty_text": "Chưa có sản phẩm active để hiển thị.",
        "bottom_cta_title": "Cần tư vấn phụ tùng?",
        "bottom_cta_description": "Lộc Sang hỗ trợ chọn đúng mã phụ tùng, nhớt và lọc phù hợp.",
        "bottom_cta_button_text": "Liên hệ ngay",
        "bottom_cta_button_link": "/contact",
        "shorts_section_title": "Lộc Sang Shorts",
        "shorts_section_subtitle": "Lướt nhanh video sản phẩm mới nhất",
        "shorts_section_link_text": "Xem Shorts",
        "shorts_items": [],
        "community_section_title": "Cộng Đồng #LocSang",
        "community_section_subtitle": "Cập nhật hình ảnh sản phẩm và phản hồi khách hàng Lộc Sang.",
        "testimonial_section_title": "Câu chuyện từ khách hàng",
        "delivery_feature_title": "Giao hàng nhanh",
        "delivery_feature_desc": "Đóng gói kỹ và giao theo thông tin đơn hàng trong hệ thống.",
        "community_items": [],
    }


class PublicHomeContentResponse(BaseModel):
    content: dict = Field(default_factory=dict)
    published_at: datetime | None = None


@router.get("", response_model=PublicHomeContentResponse)
async def get_public_home_content(
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(HomeContent).limit(1))).scalar_one_or_none()
    defaults = _default_home_payload()

    if not row:
        return PublicHomeContentResponse(content=defaults, published_at=None)

    return PublicHomeContentResponse(
        content={**defaults, **(row.published_content or {})},
        published_at=row.published_at,
    )
