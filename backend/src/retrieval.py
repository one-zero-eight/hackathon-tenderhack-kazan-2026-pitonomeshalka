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
    families: list[dict] = field(default_factory=list)

    def metadata(self):
        return {"import_sha256": self.import_sha256, "evidence": self.evidence,
                "scope_positions": self.scope_positions, "truncated": self.truncated,
                "index_sha256": self.index, "families": self.families, **self.details}


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
        families = self.store.get_family_splits(import_id, positions, scope)
        by_parent = {(family["code"], family["version"]): family for family in families}
        codes = [position.code for position in positions]
        for position in positions:
            family = by_parent.get((position.parent_code, position.parent_version))
            siblings = [child["code"] for child in family["children"]] if family else []
            additions = [code for code in siblings if code not in codes]
            if len(codes) + len(additions) <= top_k:
                codes.extend(additions)
        loaded = {position.code: position for position in positions}
        missing = [code for code in codes if code not in loaded]
        if missing:
            loaded.update({position.code: position for position in self.store.get_positions(import_id, missing)})
        positions = [loaded[code] for code in codes]
        parents = {(p.parent_code, p.parent_version) for p in positions}
        families = [family for family in families if (family["code"], family["version"]) in parents]
        by_code = {hit["code"]: hit for hit in evidence}
        evidence = [by_code.get(p.code, {"code": p.code, "name": p.name,
                    "method": "family_sibling", "parent_code": p.parent_code}) for p in positions]
        return Retrieval(import_id, positions, evidence, count, len(positions) < count, fingerprint,
                         {"method": "hybrid" if ready else "lexical", "scope": scope,
                          "semantic": {"ready": ready, "model": self.config["model"],
                                       "note": None if ready else "Prepare embeddings offline to enable semantic retrieval"},
                          "elapsed_seconds": round(perf_counter() - started, 3)}, families=families)
