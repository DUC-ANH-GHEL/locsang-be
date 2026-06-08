from __future__ import annotations

import re
from typing import Any, Iterable, Set
from urllib.parse import urlparse

import cloudinary.uploader


_CLOUDINARY_HOST_PART = "res.cloudinary.com"
_ALLOWED_PREFIXES = ("tips", "customer-stories", "home-content")


def _is_cloudinary_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return False
    return _CLOUDINARY_HOST_PART in (parsed.netloc or "")


def extract_cloudinary_public_id(url: str) -> str | None:
    value = str(url or "").strip()
    if not value or not _is_cloudinary_url(value):
        return None

    path = urlparse(value).path or ""
    marker = "/upload/"
    if marker not in path:
        return None

    tail = path.split(marker, 1)[1].lstrip("/")
    if not tail:
        return None

    # Typical Cloudinary URL format includes /upload/<transform>/v123456/path/file.ext
    match = re.search(r"(?:^|/)v\d+/(.+)$", tail)
    public_with_ext = match.group(1) if match else tail

    if "." in public_with_ext:
        public_id = public_with_ext.rsplit(".", 1)[0]
    else:
        public_id = public_with_ext

    public_id = public_id.strip("/")
    if not public_id:
        return None

    if not any(public_id == prefix or public_id.startswith(f"{prefix}/") for prefix in _ALLOWED_PREFIXES):
        return None

    return public_id


def destroy_cloudinary_url(url: str) -> bool:
    public_id = extract_cloudinary_public_id(url)
    if not public_id:
        return False

    try:
        cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)
        return True
    except Exception:
        return False


def destroy_cloudinary_urls(urls: Iterable[str]) -> int:
    count = 0
    for item in set(str(x or "").strip() for x in urls if str(x or "").strip()):
        if destroy_cloudinary_url(item):
            count += 1
    return count


def collect_cloudinary_urls_from_data(data: Any) -> Set[str]:
    urls: Set[str] = set()

    def _walk(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text and _is_cloudinary_url(text):
                urls.add(text)
            return
        if isinstance(value, dict):
            for nested in value.values():
                _walk(nested)
            return
        if isinstance(value, (list, tuple, set)):
            for nested in value:
                _walk(nested)

    _walk(data)
    return urls
