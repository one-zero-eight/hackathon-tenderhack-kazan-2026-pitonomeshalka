from dataclasses import dataclass, field
from time import perf_counter

from experiments.embedding_retrieval import DOCUMENT_PROMPT, QUERY_PROMPT, EmbeddingError, unit_vector

from backend.src.models import KtruPosition
from backend.src.storage import digest

DIMENSIONS = 768
DOCUMENT_FORMAT = "ktru-context-v1"


def embedding_config(settings):
    fields = {"model": settings.embedding_model, "dimensions": DIMENSIONS,
              "document_prompt": DOCUMENT_PROMPT, "query_prompt": QUERY_PROMPT,
              "document_format": DOCUMENT_FORMAT}
    return fields | {"fingerprint": digest(fields)}


@dataclass
class Retrieval:
    import_sha256: str
    positions: list[KtruPosition]
    evidence: list[dict]
    scope_positions: int
    truncated: bool
    index: str | None = None
    details: dict = field(default_factory=dict)

    def metadata(self):
        return {"import_sha256": self.import_sha256, "evidence": self.evidence,
                "scope_positions": self.scope_positions, "truncated": self.truncated,
                "index_sha256": self.index, **self.details}


class EmbeddingRetriever:
    def __init__(self, store, settings, client):
        self.store, self.settings, self.client = store, settings, client
        self.config = embedding_config(settings)

    def retrieve(self, text, scope="all", top_k=8):
        started = perf_counter()
        import_id = self.store.get_active_import(self.settings.catalog_key)
        if import_id is None:
            raise ValueError("No active relational catalogue; import and activate XML before searching")
        fingerprint = self.config["fingerprint"]
        ready = self.store.has_embeddings(import_id, fingerprint)
        vector = None
        if ready:
            vectors = self.client.embed([text], self.config["query_prompt"])
            if len(vectors) != 1 or len(vectors[0]) != DIMENSIONS:
                raise EmbeddingError(f"expected one {DIMENSIONS}-dimensional query embedding")
            vector = unit_vector(vectors[0])
        positions, evidence, count = self.store.search_catalogue(
            import_id, text, vector, fingerprint, scope, top_k)
        return Retrieval(import_id, positions, evidence, count, len(positions) < count, fingerprint,
                         {"method": "hybrid" if ready else "lexical", "scope": scope,
                          "semantic": {"ready": ready, "model": self.config["model"],
                                       "note": None if ready else "Prepare embeddings offline to enable semantic retrieval"},
                          "elapsed_seconds": round(perf_counter() - started, 3)})
