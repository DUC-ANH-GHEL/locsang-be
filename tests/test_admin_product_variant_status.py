from app.presentation.api.admin.endpoints.products import (
    _product_status_to_variant_status,
    _should_sync_variant_status,
    _variant_status_for_product,
)


def test_product_status_maps_to_variant_visibility_status():
    assert _product_status_to_variant_status("active") == "active"
    assert _product_status_to_variant_status("draft") == "inactive"
    assert _product_status_to_variant_status("discontinued") == "inactive"


def test_default_variant_status_follows_product_status():
    assert _should_sync_variant_status(product_has_variants=False, variant_count=1, status_str="active")
    assert _should_sync_variant_status(product_has_variants=True, variant_count=1, status_str="active")
    assert _should_sync_variant_status(product_has_variants=True, variant_count=3, status_str="discontinued")


def test_multi_variant_product_keeps_variant_visibility_when_activated():
    assert not _should_sync_variant_status(product_has_variants=True, variant_count=3, status_str="active")


def test_simple_product_forces_default_variant_to_product_status():
    assert _variant_status_for_product(False, "active", "inactive") == "active"
    assert _variant_status_for_product(False, "draft", "active") == "inactive"


def test_multi_variant_product_keeps_requested_variant_status():
    assert _variant_status_for_product(True, "active", "inactive") == "inactive"
