from sqlalchemy.dialects import postgresql

from app.core.config import Settings
from app.domain.models.product import Product
from app.presentation.api.public_api.api import PUBLIC_CACHE_CONTROL
from app.presentation.api.public_api.endpoints.products import _build_product_search_filter


def test_db_echo_log_defaults_to_false():
    settings = Settings()

    assert settings.DB_ECHO_LOG is False


def test_public_cache_control_contract():
    assert PUBLIC_CACHE_CONTROL == "public, max-age=60, stale-while-revalidate=300"


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
