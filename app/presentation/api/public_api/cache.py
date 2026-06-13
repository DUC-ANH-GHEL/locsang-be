from fastapi import Response


PUBLIC_CACHE_CONTROL = "public, max-age=60, stale-while-revalidate=300"


def apply_public_cache(response: Response) -> None:
    response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL
