from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import cloudinary.uploader
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.domain.models.home_content import HomeContent
from app.domain.models.user import User
from app.utils.cloudinary_cleanup import collect_cloudinary_urls_from_data, destroy_cloudinary_urls


router = APIRouter(prefix="/home-content", tags=["admin-home-content"])


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
        "secondary_cta_text": "",
        "secondary_cta_link": "",
        "header_brand_name": "Lộc Sang",
        "header_brand_tagline": "Phụ tùng và nhớt Yanmar chính hãng",
        "header_nav_shop_text": "Cửa hàng",
        "header_nav_new_arrivals_text": "Hàng mới về",
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
        "bottom_cta_button_text": "",
        "bottom_cta_button_link": "",
        "delivery_feature_title": "Giao hàng nhanh",
        "delivery_feature_desc": "Đóng gói kỹ và giao theo thông tin đơn hàng trong hệ thống.",
    }


class HomeContentPayload(BaseModel):
    hero_badge: str = Field(default="", max_length=180)
    hero_title: str = Field(default="", max_length=120)
    hero_headline_line1: str = Field(default="", max_length=180)
    hero_headline_line2: str = Field(default="", max_length=180)
    hero_subtitle: str = Field(default="", max_length=240)
    hero_description: str = Field(default="", max_length=1000)
    hero_image_url: str = Field(default="", max_length=1200)
    primary_cta_text: str = Field(default="", max_length=80)
    primary_cta_link: str = Field(default="", max_length=300)
    secondary_cta_text: str = Field(default="", max_length=80)
    secondary_cta_link: str = Field(default="", max_length=300)
    header_brand_name: str = Field(default="", max_length=120)
    header_brand_tagline: str = Field(default="", max_length=240)
    header_nav_shop_text: str = Field(default="", max_length=80)
    header_nav_new_arrivals_text: str = Field(default="", max_length=80)
    header_nav_orders_text: str = Field(default="", max_length=80)
    footer_brand_name: str = Field(default="", max_length=120)
    footer_desktop_caption: str = Field(default="", max_length=260)
    footer_mobile_description: str = Field(default="", max_length=420)
    footer_products_title: str = Field(default="", max_length=80)
    footer_products_item_1: str = Field(default="", max_length=120)
    footer_products_item_2: str = Field(default="", max_length=120)
    footer_products_item_3: str = Field(default="", max_length=120)
    footer_products_item_4: str = Field(default="", max_length=120)
    footer_info_title: str = Field(default="", max_length=80)
    footer_info_item_1: str = Field(default="", max_length=140)
    footer_info_item_2: str = Field(default="", max_length=140)
    footer_info_item_3: str = Field(default="", max_length=140)
    footer_info_item_4: str = Field(default="", max_length=140)
    footer_social_title: str = Field(default="", max_length=80)
    footer_social_item_1: str = Field(default="", max_length=80)
    footer_social_item_2: str = Field(default="", max_length=80)
    footer_social_item_3: str = Field(default="", max_length=80)
    footer_social_item_4: str = Field(default="", max_length=80)
    footer_social_instagram_url: str = Field(default="", max_length=300)
    footer_social_pinterest_url: str = Field(default="", max_length=300)
    footer_social_facebook_url: str = Field(default="", max_length=300)
    footer_social_tiktok_url: str = Field(default="", max_length=300)
    footer_policy_title: str = Field(default="", max_length=80)
    footer_policy_item_1: str = Field(default="", max_length=120)
    footer_policy_item_2: str = Field(default="", max_length=120)
    footer_policy_item_3: str = Field(default="", max_length=120)
    footer_contact_title: str = Field(default="", max_length=80)
    footer_contact_hotline: str = Field(default="", max_length=120)
    footer_contact_email: str = Field(default="", max_length=160)
    footer_copyright_text: str = Field(default="", max_length=260)
    hero_feature_1_title: str = Field(default="", max_length=100)
    hero_feature_1_desc: str = Field(default="", max_length=220)
    hero_feature_2_title: str = Field(default="", max_length=100)
    hero_feature_2_desc: str = Field(default="", max_length=220)
    hero_feature_3_title: str = Field(default="", max_length=100)
    hero_feature_3_desc: str = Field(default="", max_length=220)
    hero_stats_title: str = Field(default="", max_length=140)
    hero_stats_products_label: str = Field(default="", max_length=120)
    hero_stats_categories_label: str = Field(default="", max_length=120)
    hero_stats_price_label: str = Field(default="", max_length=140)
    hero_stats_catalog_link_text: str = Field(default="", max_length=120)
    category_section_title: str = Field(default="", max_length=160)
    category_section_desktop_title: str = Field(default="", max_length=220)
    category_section_desktop_subtitle: str = Field(default="", max_length=320)
    category_section_link_text: str = Field(default="", max_length=180)
    mobile_category_title: str = Field(default="", max_length=180)
    category_section_subtitle: str = Field(default="", max_length=320)
    category_section_view_all_text: str = Field(default="", max_length=120)
    category_section_empty_text: str = Field(default="", max_length=240)
    category_section_loading_text: str = Field(default="", max_length=240)
    new_arrivals_title: str = Field(default="", max_length=160)
    best_seller_section_title: str = Field(default="", max_length=220)
    best_seller_section_subtitle: str = Field(default="", max_length=420)
    best_seller_badge_text: str = Field(default="", max_length=120)
    mobile_best_seller_title: str = Field(default="", max_length=180)
    mobile_view_all_text: str = Field(default="", max_length=120)
    new_arrivals_subtitle: str = Field(default="", max_length=320)
    new_arrivals_live_badge: str = Field(default="", max_length=80)
    new_arrivals_price_prefix: str = Field(default="", max_length=120)
    new_arrivals_empty_text: str = Field(default="", max_length=240)
    bottom_cta_title: str = Field(default="", max_length=180)
    bottom_cta_description: str = Field(default="", max_length=420)
    bottom_cta_button_text: str = Field(default="", max_length=80)
    bottom_cta_button_link: str = Field(default="", max_length=300)
    delivery_feature_title: str = Field(default="", max_length=140)
    delivery_feature_desc: str = Field(default="", max_length=320)


class HomeContentReadResponse(BaseModel):
    draft: HomeContentPayload
    published: HomeContentPayload
    published_at: datetime | None = None


class HomeContentDraftUpdateRequest(BaseModel):
    content: HomeContentPayload


class HomeContentImageUploadResponse(BaseModel):
    url: str


async def _get_or_create_content(db: AsyncSession) -> HomeContent:
    row = (await db.execute(select(HomeContent).limit(1))).scalar_one_or_none()
    if row:
        return row

    defaults = _default_home_payload()
    row = HomeContent(draft_content=defaults, published_content=defaults)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("", response_model=HomeContentReadResponse)
async def get_home_content_admin(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = await _get_or_create_content(db)
    defaults = _default_home_payload()
    draft = {**defaults, **(row.draft_content or {})}
    published = {**defaults, **(row.published_content or {})}
    return HomeContentReadResponse(draft=draft, published=published, published_at=row.published_at)


@router.put("/draft", response_model=HomeContentReadResponse)
async def update_home_content_draft(
    body: HomeContentDraftUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await _get_or_create_content(db)
    old_draft_urls = collect_cloudinary_urls_from_data(row.draft_content or {})
    old_published_urls = collect_cloudinary_urls_from_data(row.published_content or {})

    row.draft_content = body.content.model_dump()
    row.updated_by = getattr(current_user, "id", None)
    row.updated_at = datetime.utcnow()

    new_draft_urls = collect_cloudinary_urls_from_data(row.draft_content or {})
    removed_urls = old_draft_urls - (new_draft_urls | old_published_urls)

    await db.commit()
    await db.refresh(row)

    if removed_urls:
        destroy_cloudinary_urls(removed_urls)

    defaults = _default_home_payload()
    draft = {**defaults, **(row.draft_content or {})}
    published = {**defaults, **(row.published_content or {})}
    return HomeContentReadResponse(draft=draft, published=published, published_at=row.published_at)


@router.post("/publish", response_model=HomeContentReadResponse)
async def publish_home_content(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = await _get_or_create_content(db)
    old_published_urls = collect_cloudinary_urls_from_data(row.published_content or {})
    draft_urls = collect_cloudinary_urls_from_data(row.draft_content or {})

    row.published_content = dict(row.draft_content or _default_home_payload())
    row.published_by = getattr(current_user, "id", None)
    row.published_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()

    removed_urls = old_published_urls - draft_urls

    await db.commit()
    await db.refresh(row)

    if removed_urls:
        destroy_cloudinary_urls(removed_urls)

    defaults = _default_home_payload()
    draft = {**defaults, **(row.draft_content or {})}
    published = {**defaults, **(row.published_content or {})}
    return HomeContentReadResponse(draft=draft, published=published, published_at=row.published_at)


@router.post("/upload-image", response_model=HomeContentImageUploadResponse)
async def upload_home_image(
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
):
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File tải lên phải là ảnh.",
        )

    try:
        data = await file.read()
        if not data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File ảnh rỗng.",
            )

        max_size = 10 * 1024 * 1024
        if len(data) > max_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ảnh vượt quá 10MB. Vui lòng chọn ảnh nhỏ hơn.",
            )

        result = cloudinary.uploader.upload(
            data,
            folder="home-content",
            resource_type="image",
            overwrite=False,
            use_filename=True,
        )
        secure_url = (result or {}).get("secure_url")
        if not secure_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Upload ảnh thất bại, không nhận được URL.",
            )

        return HomeContentImageUploadResponse(url=secure_url)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload ảnh thất bại: {str(exc)}",
        )
