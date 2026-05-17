from __future__ import annotations

from typing import Any


def paginate_rows(
    rows: list[dict[str, Any]],
    *,
    page: int | None,
    page_size: int | None,
    total_key: str,
    returned_key: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    total = len(rows)
    if page is None and page_size is None:
        returned_rows = rows
        pagination = {
            "mode": "all",
            "page": None,
            "pageSize": None,
            "total": total,
            "totalPages": 1 if total else 0,
            "returned": total,
            "offset": 0,
            "rangeStart": 1 if total else 0,
            "rangeEnd": total,
            "hasPrevious": False,
            "hasNext": False,
        }
    else:
        effective_page = page or 1
        effective_page_size = page_size or 100
        start = (effective_page - 1) * effective_page_size
        end = start + effective_page_size
        returned_rows = rows[start:end] if start < total else []
        returned_count = len(returned_rows)
        pagination = {
            "mode": "page",
            "page": effective_page,
            "pageSize": effective_page_size,
            "total": total,
            "totalPages": (total + effective_page_size - 1) // effective_page_size if total else 0,
            "returned": returned_count,
            "offset": start,
            "rangeStart": start + 1 if returned_count else 0,
            "rangeEnd": start + returned_count if returned_count else 0,
            "hasPrevious": effective_page > 1 and total > 0,
            "hasNext": end < total,
        }
    pagination[total_key] = pagination["total"]
    pagination[returned_key] = pagination["returned"]
    return returned_rows, pagination
