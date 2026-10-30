"""Paginación por cursor nativo para el hito M08."""

from .pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    InvalidCursorError,
    query_by_type_page,
)

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "InvalidCursorError",
    "query_by_type_page",
]
