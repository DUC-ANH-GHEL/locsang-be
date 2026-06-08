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
        "hero_badge": "Bộ sưu tập mới mỗi tuần",
        "hero_title": "Lộc Sang",
        "hero_headline_line1": "Sản Phẩm Chọn Lọc -",
        "hero_headline_line2": "Bé Yêu Lung Linh",
        "hero_subtitle": "Mặc đẹp cho bé cưng, thoải mái cả ngày",
        "hero_description": "Mỗi mẫu đều được chọn kỹ về chất liệu và phom dáng để bé cưng mặc êm, dễ chịu và lên hình xinh xắn.",
        "hero_image_url": "https://images.unsplash.com/photo-1548199973-03cce0bbc87b?auto=format&fit=crop&w=1900&q=80",
        "primary_cta_text": "Mua ngay",
        "primary_cta_link": "/products",
        "secondary_cta_text": "Tư vấn chọn cỡ",
        "secondary_cta_link": "/contact",
        "header_brand_name": "Lộc Sang",
        "header_brand_tagline": "Mua sắm chọn lọc, giao nhanh toàn quốc",
        "header_nav_shop_text": "Cửa hàng",
        "header_nav_new_arrivals_text": "Hàng mới về",
        "header_nav_tips_text": "Mẹo chăm sóc",
        "header_nav_shorts_text": "Lộc Sang Shorts",
        "header_nav_orders_text": "Đơn hàng",
        "footer_brand_name": "Lộc Sang",
        "footer_desktop_caption": "© 2024 Lộc Sang. Mua sắm tiện lợi, giao nhanh toàn quốc.",
        "footer_mobile_description": "Nơi hội tụ những sản phẩm thiết thực, đẹp và dễ mua cho mọi gia đình.",
        "footer_products_title": "sản phẩm",
        "footer_products_item_1": "Sản Phẩm Mới",
        "footer_products_item_2": "Ưu Đãi Nổi Bật",
        "footer_products_item_3": "Đồ Chơi Bé Yêu",
        "footer_products_item_4": "Giường & Nệm",
        "footer_info_title": "thông tin",
        "footer_info_item_1": "Thông tin giao hàng",
        "footer_info_item_2": "Chính sách đổi trả",
        "footer_info_item_3": "Hướng dẫn chọn size",
        "footer_info_item_4": "Liên hệ về chúng mình",
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
        "footer_contact_hotline": "Hotline: 1900 8888",
        "footer_contact_email": "Email: hello@locsang.shop",
        "footer_copyright_text": "© 2024 Lộc Sang. All rights reserved.",
        "hero_feature_1_title": "Chất liệu êm",
        "hero_feature_1_desc": "Chọn lọc kỹ, dùng bền đẹp.",
        "hero_feature_2_title": "Giao nhanh",
        "hero_feature_2_desc": "Đóng gói gọn gàng, gửi liền tay.",
        "hero_feature_3_title": "Hàng đang bán",
        "hero_feature_3_desc": "Hiển thị theo dữ liệu sản phẩm active.",
        "hero_stats_title": "Số liệu nhanh tại cửa hàng",
        "hero_stats_products_label": "Sản phẩm active",
        "hero_stats_categories_label": "Danh mục nổi bật",
        "hero_stats_price_label": "Khoảng giá hiện tại",
        "hero_stats_catalog_link_text": "Xem toàn bộ catalog",
        "category_section_title": "Danh mục đang chạy tốt",
        "category_section_desktop_title": "Mua sắm theo danh mục sản phẩm",
        "category_section_desktop_subtitle": "Khám phá những món đồ thiết yếu cho bé yêu",
        "category_section_link_text": "Xem toàn bộ cửa hàng",
        "mobile_category_title": "Khám Phá Theo Loại",
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
        "bottom_cta_title": "Cần tư vấn size nhanh?",
        "bottom_cta_description": "Lộc Sang hỗ trợ tư vấn nhanh để bạn chọn đúng sản phẩm ngay từ lần đầu.",
        "bottom_cta_button_text": "Liên hệ ngay",
        "bottom_cta_button_link": "/contact",
        "shorts_section_title": "Lộc Sang Shorts",
        "shorts_section_subtitle": "Lướt nhanh video sản phẩm mới nhất",
        "shorts_section_link_text": "Xem Shorts",
        "shorts_items": [],
        "community_section_title": "Cộng Đồng #LocSang",
        "community_section_subtitle": "Chia sẻ khoảnh khắc hạnh phúc của bé yêu cùng chúng mình nhé!",
        "testimonial_section_title": "Câu chuyện từ khách hàng",
        "delivery_feature_title": "Giao Hàng Nhanh",
        "delivery_feature_desc": "Vận chuyển hỏa tốc đến tận tay bé yêu để niềm vui không phải chờ.",
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
