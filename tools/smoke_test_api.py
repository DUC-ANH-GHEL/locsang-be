from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from typing import Any

import httpx

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8001").rstrip("/")
LOGIN_PATH = "/api/v1/users/login"
LOGIN_EMAIL = os.getenv("SMOKE_TEST_EMAIL", "")
LOGIN_PASSWORD = os.getenv("SMOKE_TEST_PASSWORD", "")

# Status codes that are acceptable for a smoke test without providing full payloads.
OK_STATUSES = {200, 201, 202, 204, 400, 401, 403, 404, 405, 409, 415, 422}


@dataclass
class Failure:
    method: str
    path: str
    url: str
    status_code: int | None
    detail: str


def _fill_path_params(path: str) -> str:
    # Best-effort replacements for common path params.
    replacements = {
        "{user_id}": "1",
        "{order_id}": "1",
        "{product_id}": "1",
        "{image_id}": "1",
        "{category_id}": "1",
        "{sku}": "test-sku",
    }
    for k, v in replacements.items():
        path = path.replace(k, v)

    # Generic fallback: replace any remaining {param} with "1".
    while "{" in path and "}" in path:
        start = path.index("{")
        end = path.index("}", start)
        path = path[:start] + "1" + path[end + 1 :]
    return path


async def _get_token(client: httpx.AsyncClient) -> str:
    if not LOGIN_EMAIL or not LOGIN_PASSWORD:
        raise RuntimeError(
            "Missing credentials: set SMOKE_TEST_EMAIL and SMOKE_TEST_PASSWORD (and optionally BASE_URL)."
        )
    resp = await client.post(
        f"{BASE_URL}{LOGIN_PATH}",
        json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD},
        headers={"accept": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["access_token"]


def _iter_operations(openapi: dict[str, Any]):
    paths: dict[str, Any] = openapi.get("paths", {})
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            yield path, method.upper(), op or {}


async def main() -> int:
    failures: list[Failure] = []

    async with httpx.AsyncClient(follow_redirects=True) as client:
        # Get token first (also validates login works)
        token = await _get_token(client)
        auth_header = {"Authorization": f"Bearer {token}"}

        openapi = (await client.get(f"{BASE_URL}/openapi.json", timeout=10)).json()

        total = 0
        for raw_path, method, op in _iter_operations(openapi):
            total += 1
            path = _fill_path_params(raw_path)
            url = f"{BASE_URL}{path}"

            # Reduce side effects:
            # - For GET: include auth to exercise protected endpoints.
            # - For mutating methods: do NOT include auth by default, to avoid creating/deleting data.
            headers: dict[str, str] = {"accept": "application/json"}
            if method == "GET" and path != LOGIN_PATH:
                headers.update(auth_header)

            # Minimal body strategy: if JSON is accepted, send empty object to provoke 422 rather than 500.
            request_kwargs: dict[str, Any] = {"headers": headers, "timeout": 15}
            content_types = (op.get("requestBody", {}) or {}).get("content", {}) if isinstance(op, dict) else {}
            if method in {"POST", "PUT", "PATCH"} and isinstance(content_types, dict) and "application/json" in content_types:
                request_kwargs["json"] = {}

            try:
                resp = await client.request(method, url, **request_kwargs)
                if resp.status_code not in OK_STATUSES:
                    failures.append(
                        Failure(
                            method=method,
                            path=raw_path,
                            url=url,
                            status_code=resp.status_code,
                            detail=(resp.text[:500] or "<empty response>"),
                        )
                    )
            except Exception as exc:
                failures.append(
                    Failure(
                        method=method,
                        path=raw_path,
                        url=url,
                        status_code=None,
                        detail=str(exc),
                    )
                )

    print(f"Base URL: {BASE_URL}")
    print(f"Checked operations: {total}")
    print(f"Failures: {len(failures)}")

    if failures:
        print("\n--- FAILURES (only non-expected statuses / exceptions) ---")
        for f in failures:
            sc = "EXC" if f.status_code is None else str(f.status_code)
            print(f"[{sc}] {f.method} {f.path} -> {f.url}")
            if f.detail:
                print(f"  {f.detail.replace('\n', ' ')[:500]}")

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
