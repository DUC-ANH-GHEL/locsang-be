from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.core.config import Settings
from app.core.deps import get_current_user
from app.main import app


def _route(path: str, method: str) -> APIRoute:
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path == path and method.upper() in route.methods:
            return route
    raise AssertionError(f"Route {method.upper()} {path} not found")


def _has_dependency(route: APIRoute, dependency) -> bool:
    pending = list(route.dependant.dependencies)
    while pending:
        item = pending.pop()
        if item.call is dependency:
            return True
        pending.extend(item.dependencies)
    return False


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/products"),
        ("PUT", "/api/products/{id}"),
        ("DELETE", "/api/products/{id}"),
        ("POST", "/api/v1/users/"),
        ("GET", "/api/v1/users/{user_id}"),
        ("PUT", "/api/v1/users/{user_id}"),
        ("DELETE", "/api/v1/users/{user_id}"),
        ("POST", "/api/v1/categories/"),
        ("PUT", "/api/v1/categories/{category_id}"),
        ("DELETE", "/api/v1/categories/{category_id}"),
    ],
)
def test_legacy_write_routes_require_admin_auth(method, path):
    assert _has_dependency(_route(path, method), get_current_user)


def test_gemini_route_is_not_mounted():
    mounted_paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert not any(path.startswith("/api/v1/gemini") for path in mounted_paths)


def test_password_reset_token_is_not_exposed_by_default():
    assert Settings().AUTH_DEBUG_EXPOSE_PASSWORD_RESET_TOKEN is False


def test_production_rejects_placeholder_secret():
    with pytest.raises(RuntimeError):
        Settings(VERCEL_ENV="production", SECRET_KEY="your-secret-key-here")


def test_cors_does_not_allow_wildcard_cgnn_subdomains():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "allow_origin_regex" not in source


def test_no_gemini_secret_is_hardcoded():
    sources = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in Path("app").rglob("*.py")
    )
    assert "AIza" not in sources
