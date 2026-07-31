"""Qdrant vector store over products and reviews.

Embeddings run locally through fastembed (BAAI/bge-small-en-v1.5) — no
embedding API bill, and the nightly CI job needs no vendor key to index.

Products and reviews live in one collection separated by a `kind` payload
field, so a single similarity search can answer "which competitor product is
closest to this one" and "who else complains about battery life".
"""
from __future__ import annotations

import atexit
from functools import lru_cache

from qdrant_client import QdrantClient, models

from app.config import get_settings
from app.contract import Product


class VectorStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.collection = settings.qdrant_collection

        location = settings.qdrant_location
        if location.startswith("http"):
            self.client = QdrantClient(url=location)
        elif location == ":memory:":
            self.client = QdrantClient(location=":memory:")
        else:
            self.client = QdrantClient(path=location)

        self.client.set_model(settings.embedding_model)
        atexit.register(self._safe_close)

    def _safe_close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass

    def index_products(self, products: list[Product]) -> int:
        """Index one document per product plus one per review."""
        documents: list[str] = []
        metadata: list[dict] = []
        ids: list[str] = []

        for p in products:
            documents.append(f"{p.title}. {p.description}".strip())
            metadata.append(
                {
                    "kind": "product",
                    "product_id": p.id,
                    "product_title": p.title,
                    "brand": p.brand,
                    "category": p.category,
                    "source": p.source,
                    "price": p.price.amount,
                    "currency": p.price.currency,
                }
            )
            ids.append(_point_id(p.id))

            for r in p.reviews:
                if not r.body.strip():
                    continue
                documents.append(r.body)
                metadata.append(
                    {
                        "kind": "review",
                        "review_id": r.id,
                        "product_id": p.id,
                        "product_title": p.title,
                        "brand": p.brand,
                        "category": p.category,
                        "source": p.source,
                        "rating": r.rating,
                    }
                )
                ids.append(_point_id(r.id))

        if not documents:
            return 0

        self.client.add(
            collection_name=self.collection,
            documents=documents,
            metadata=metadata,
            ids=ids,
        )
        return len(documents)

    def search(
        self,
        query: str,
        top_k: int = 5,
        kind: str | None = None,
        category: str | None = None,
        brand: str | None = None,
    ) -> list[dict]:
        conditions = [
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in (("kind", kind), ("category", category), ("brand", brand))
            if value
        ]
        results = self.client.query(
            collection_name=self.collection,
            query_text=query,
            query_filter=models.Filter(must=conditions) if conditions else None,
            limit=top_k,
        )
        return [
            {
                "text": r.document or r.metadata.get("document", ""),
                "score": round(r.score, 4),
                **{k: v for k, v in r.metadata.items() if k != "document"},
            }
            for r in results
        ]

    def count(self) -> int:
        try:
            return self.client.count(self.collection).count
        except Exception:
            return 0


def _point_id(natural_id: str) -> str:
    """Qdrant point ids must be a UUID or an unsigned int.

    Our ids are strings like "dummyjson:31#956e647f5b", so hash them into a
    deterministic UUID — same product on the next crawl overwrites its point
    instead of adding a duplicate.
    """
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, natural_id))


@lru_cache
def get_vector_store() -> VectorStore:
    return VectorStore()
