"""Shared pagination envelope used by every list endpoint that can grow
large in a real deployment (leads, quotes, contracts, jobs, invoices,
customers, audit log)."""
from typing import Generic, TypeVar
from pydantic import BaseModel
from sqlalchemy.orm import Query

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


def paginate(query: Query, page: int = 1, page_size: int = 25) -> tuple[list, int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def apply_sort(query: Query, model, sort_by: str | None, sort_dir: str = "desc"):
    if not sort_by or not hasattr(model, sort_by):
        return query
    column = getattr(model, sort_by)
    return query.order_by(column.desc() if sort_dir == "desc" else column.asc())
