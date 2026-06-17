from fastapi import Response


PUBLIC_CACHE_CONTROL = "no-store"


def apply_public_cache(response: Response) -> None:
    response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL
