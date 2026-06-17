from sqlalchemy.dialects import postgresql

from app.core.config import Settings
from app.domain.models.product import Product
from app.presentation.api.public_api.api import PUBLIC_CACHE_CONTROL
from app.presentation.api.public_api.endpoints.categories import _category_has_sellable_product_filter
from app.presentation.api.public_api.endpoints.products import _build_product_search_filter, _sellable_product_filters


def test_db_echo_log_defaults_to_false():
    settings = Settings()

    assert settings.DB_ECHO_LOG is False


def test_public_cache_control_contract():
    assert PUBLIC_CACHE_CONTROL == "no-store"


def test_public_product_search_only_targets_name():
    compiled = str(
        _build_product_search_filter("yanmar").compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert Product.name.name in compiled
    assert Product.sku.name not in compiled
    assert Product.slug.name not in compiled


def test_sellable_product_filters_match_current_schema():
    compiled = " AND ".join(
        str(
            expression.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        for expression in _sellable_product_filters()
    )

    assert "products.stock" in compiled
    assert "product_variants.allow_backorder" in compiled
    assert "products.allow_backorder" not in compiled


def test_public_categories_only_include_sellable_products():
    compiled = str(
        _category_has_sellable_product_filter().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "products.category_id = categories.id" in compiled
    assert "products.status = 'active'" in compiled
    assert "product_variants.allow_backorder" in compiled
