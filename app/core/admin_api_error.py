from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AdminAPIError(Exception):
    error_code: str
    message: str
    status_code: int = 400
