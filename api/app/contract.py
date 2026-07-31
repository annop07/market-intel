"""The wire contract with the Go collector.

These models mirror scraper/internal/model/model.go field for field. The Go
side owns the shape; this side validates it — a malformed crawl fails here at
the door instead of poisoning the analysis three steps later.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class Price(BaseModel):
    amount: float = Field(ge=0)
    currency: str = "USD"

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return (v or "USD").upper()


class Review(BaseModel):
    id: str
    product_id: str
    rating: float | None = None
    title: str = ""
    body: str
    author: str = ""
    posted_at: datetime | None = None


class Product(BaseModel):
    id: str
    source: str
    url: str = ""
    title: str
    brand: str = "(unbranded)"
    category: str = ""
    price: Price
    list_price: Price | None = None
    rating: float | None = None
    rating_count: int = 0
    in_stock: bool = True
    description: str = ""
    features: dict[str, str] = Field(default_factory=dict)
    reviews: list[Review] = Field(default_factory=list)
    collected_at: datetime | None = None


class IngestRequest(BaseModel):
    products: list[Product]


class IngestResponse(BaseModel):
    products_upserted: int
    reviews_upserted: int
    vectors_indexed: int
    catalogue_size: int
