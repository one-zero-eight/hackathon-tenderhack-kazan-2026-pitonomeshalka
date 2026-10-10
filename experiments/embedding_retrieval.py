"""Semantic catalog retrieval through meow-embed; no local model dependencies."""

import base64
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import struct
import tempfile
from threading import Lock
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if __package__:
    from . import classifier_experiments as ce
    from .config import env
else:
    import classifier_experiments as ce
    from config import env


MODEL = env("EMBEDDING_MODEL")
BASE_URL = env("EMBEDDING_BASE_URL").rstrip("/")
QUERY_PROMPT = env("EMBEDDING_QUERY_PROMPT")
DOCUMENT_PROMPT = env("EMBEDDING_DOCUMENT_PROMPT")
logger = logging.getLogger("uvicorn.error")


class EmbeddingError(RuntimeError):
    """Embedding transport, protocol or index failure."""


def unit_vector(values):
    if not isinstance(values, (list, tuple)) or not values:
        raise EmbeddingError("Embedding must be a nonempty vector")
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise EmbeddingError("Embedding contains invalid or nonfinite values")
    norm = math.hypot(*values)
    if not math.isfinite(norm) or norm == 0:
        raise EmbeddingError("Embedding has an invalid norm")
    return [value / norm for value in values]


class MeowEmbedClient:
    def __init__(self, base_url=None, model_id=None, timeout=None):
        self.base_url = (base_url if base_url is not None else env("EMBEDDING_BASE_URL")).rstrip("/")
        self.model_id = model_id if model_id is not None else env("EMBEDDING_MODEL")
        self.timeout = timeout if timeout is not None else float(env("EMBEDDING_TIMEOUT_SECONDS"))
        self.recorder = None

    def health(self):
        """Check connectivity and configured dense model availability without embedding."""
        url = self.base_url + "/models"
        try:
            with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=self.timeout) as response:
                result = json.load(response)
        except HTTPError as error:
            raise EmbeddingError(f"meow-embed HTTP {error.code} at {url}") from error
        except (URLError, OSError, ValueError) as error:
            raise EmbeddingError(f"meow-embed unavailable or invalid response at {url}: {error}") from error
        if not isinstance(result, dict) or not isinstance(result.get("models"), list):
            raise EmbeddingError("Invalid meow-embed /models response: expected models list")
        model = next((item for item in result["models"] if isinstance(item, dict)
                      and item.get("id") == self.model_id and item.get("type") == "dense"), None)
        if model is None:
            raise EmbeddingError(f"Configured dense embedding model {self.model_id} is not available")
        return model

    def embed(self, texts, prompt):
        started = perf_counter()
        call_id = None
        if self.recorder is not None:
            call_id = self.recorder.start_embedding_call(
                {"texts": texts, "dense_model_id": self.model_id, "dense_prompt": prompt}, self.base_url + "/embed")
        logger.info("Embedding request started: model=%s texts=%d url=%s timeout=%ss prompt=%r",
                    self.model_id, len(texts), self.base_url + "/embed", self.timeout, prompt)
        try:
            vectors = self._embed(texts, prompt)
        except EmbeddingError as error:
            if call_id is not None:
                self.recorder.finish_embedding_call(call_id, None, perf_counter() - started, str(error))
            logger.warning("Embedding request failed: model=%s texts=%d elapsed=%.3fs error=%s",
                           self.model_id, len(texts), perf_counter() - started, error)
            raise
        if call_id is not None:
            self.recorder.finish_embedding_call(call_id, len(vectors[0]) if vectors else 0, perf_counter() - started)
        logger.info("Embedding request completed: model=%s texts=%d dimensions=%d elapsed=%.3fs",
                    self.model_id, len(texts), len(vectors[0]) if vectors else 0, perf_counter() - started)
        return vectors

    def _embed(self, texts, prompt):
        body = {"texts": texts, "dense_model_id": self.model_id, "dense_prompt": prompt}
        url = self.base_url + "/embed"
        logger.debug("Embedding payload: %s", json.dumps({"url": url, "request": body}, ensure_ascii=False))
        request = Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except HTTPError as error:
            raise EmbeddingError(f"meow-embed HTTP {error.code}: {error.read().decode(errors='replace')}") from error
        except (URLError, OSError, ValueError) as error:
            raise EmbeddingError(f"meow-embed unavailable or invalid response at {url}: {error}") from error
        try:
            dense = result["dense"]
            rows, dimensions = dense["shape"]
            if (result["texts_count"] != len(texts) or type(rows) is not int or rows != len(texts)
                    or type(dimensions) is not int or dimensions < 1):
                raise ValueError("Embedding shape does not match submitted texts")
            if dense["model_id"] != self.model_id:
                raise ValueError("Embedding model differs from requested model")
            if dense["dtype"] != "float32" or dense["encoding"] != "base64":
                raise ValueError("Expected base64 float32 dense embeddings")
            raw = base64.b64decode(dense["data"], validate=True)
            if len(raw) != rows * dimensions * 4:
                raise ValueError("Embedding byte count does not match shape")
            values = struct.unpack(f"<{rows * dimensions}f", raw)
            return [unit_vector(values[start:start + dimensions])
                    for start in range(0, len(values), dimensions)]
        except (KeyError, TypeError, ValueError, struct.error) as error:
            raise EmbeddingError(f"Invalid meow-embed response: {error}") from error


class EmbeddingRetriever:
    def __init__(self, catalog, client, cache_path, batch_size=None, max_names=None, *, cache_store=None):
        self.catalog = catalog
        self.client = client
        self.cache_store = cache_store
        self.cache_path = Path(cache_path) if cache_store is None else "postgresql"
        self.batch_size = batch_size if batch_size is not None else int(env("EMBEDDING_BATCH_SIZE"))
        self.max_names = max_names if max_names is not None else int(env("EMBEDDING_MAX_NAMES"))
        self._lock = Lock()
        self._fingerprint = None
        self._vectors = {}
        if self.batch_size < 1:
            raise ValueError("Embedding batch size must be positive")
        if self.max_names < 1:
            raise ValueError("Embedding maximum distinct names must be positive")

    def _ensure_index(self):
        started = perf_counter()
        with self._lock:
            names = sorted({ce.normalize(p["name"]) for p in self.catalog["positions"]})
            metadata = {"format": 1, "model": self.client.model_id,
                        "document_prompt": DOCUMENT_PROMPT, "query_prompt": QUERY_PROMPT, "names": names}
            fingerprint = hashlib.sha256(json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if fingerprint == self._fingerprint:
                logger.info("Embedding index reused from memory: names=%d cache=%s", len(names), self.cache_path)
                return {"status": "memory", "names": len(names),
                        "dimensions": len(next(iter(self._vectors.values()), [])),
                        "elapsed_seconds": round(perf_counter() - started, 3)}
            vectors = None
            if self.cache_store is not None or self.cache_path.exists():
                try:
                    cached = (self.cache_store.load_embedding_index(fingerprint) if self.cache_store is not None
                              else json.loads(self.cache_path.read_text(encoding="utf-8")))
                    if cached is not None and cached["metadata"] == metadata:
                        vectors = [unit_vector(vector) for vector in cached["vectors"]]
                        if len(vectors) != len(names) or len({len(v) for v in vectors}) > 1:
                            vectors = None
                            logger.warning("Embedding cache has inconsistent vectors; rebuilding %s", self.cache_path)
                    elif cached is not None:
                        logger.info("Embedding cache metadata changed; rebuilding %s", self.cache_path)
                except (OSError, ValueError, KeyError, TypeError, EmbeddingError) as error:
                    logger.warning("Embedding cache cannot be reused: cache=%s error=%s", self.cache_path, error)
                    vectors = None
            cache_status = ("postgresql" if self.cache_store is not None else "disk") if vectors is not None else "built"
            if vectors is None:
                logger.info("Embedding index build started: model=%s names=%d batch_size=%d cache=%s",
                            self.client.model_id, len(names), self.batch_size, self.cache_path)
                vectors = []
                for start in range(0, len(names), self.batch_size):
                    batch = names[start:start + self.batch_size]
                    logger.info("Embedding catalog batch: names=%d–%d/%d", start + 1, start + len(batch), len(names))
                    incoming = self.client.embed(batch, DOCUMENT_PROMPT)
                    if len(incoming) != len(batch):
                        raise EmbeddingError("Embedding batch did not return every catalog name")
                    vectors.extend(unit_vector(vector) for vector in incoming)
                if len({len(v) for v in vectors}) > 1:
                    raise EmbeddingError("Catalog embedding dimensions differ between batches")
                temporary = None
                try:
                    if self.cache_store is not None:
                        self.cache_store.save_embedding_index(fingerprint, metadata, vectors)
                    else:
                        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache_path.parent,
                                                         delete=False) as output:
                            temporary = Path(output.name)
                            json.dump({"metadata": metadata, "vectors": vectors}, output, ensure_ascii=False)
                            output.write("\n")
                        os.replace(temporary, self.cache_path)
                except OSError as error:
                    logger.warning("Embedding cache save failed: cache=%s error=%s", self.cache_path, error)
                    raise EmbeddingError(f"Cannot save embedding cache {self.cache_path}: {error}") from error
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
            self._vectors = dict(zip(names, vectors, strict=True))
            self._fingerprint = fingerprint
            elapsed = round(perf_counter() - started, 3)
            dimensions = len(vectors[0]) if vectors else 0
            logger.info("Embedding index ready: source=%s names=%d dimensions=%d elapsed=%.3fs cache=%s",
                        cache_status, len(names), dimensions, elapsed, self.cache_path)
            return {"status": cache_status, "names": len(names), "dimensions": dimensions, "elapsed_seconds": elapsed}

    def retrieve(self, catalog, text, scope="all", top_k=8):
        started = perf_counter()
        try:
            return self._retrieve(catalog, text, scope, top_k)
        except EmbeddingError as error:
            logger.warning("Embedding search failed: model=%s scope=%s elapsed=%.3fs error=%s",
                           self.client.model_id, scope, perf_counter() - started, error)
            raise

    def _retrieve(self, catalog, text, scope, top_k):
        started = perf_counter()
        positions = ce.select_scope(catalog, scope)
        logger.info("Embedding search started: model=%s scope=%s positions=%d top_k=%d description_characters=%d",
                    self.client.model_id, scope, len(positions), top_k, len(text))
        evidence = []
        selected = []
        fingerprint = None
        index_info = None
        query_seconds = 0
        if positions:
            index_info = self._ensure_index()
            query_started = perf_counter()
            query = unit_vector(self.client.embed([text], QUERY_PROMPT)[0])
            query_seconds = round(perf_counter() - query_started, 3)
            groups = {}
            for position in positions:
                groups.setdefault(ce.normalize(position["name"]), []).append(position)
            scores = {}
            for name in groups:
                vector = self._vectors[name]
                if len(query) != len(vector):
                    raise EmbeddingError("Query and catalog embedding dimensions differ; rebuild the cache if the model changed")
                scores[name] = sum(a * b for a, b in zip(query, vector, strict=True))
            if self.cache_store is not None:
                scores = self.cache_store.score_embeddings(self._fingerprint, query, list(groups))
            # Reserve room for code/version alternatives of the closest names.
            closest = sorted(groups, key=lambda name: (-scores[name], name))[:min(self.max_names, top_k)]
            groups = {name: sorted(groups[name], key=lambda p: p["key"]) for name in closest}
            depth = 0
            while len(selected) < top_k:
                added = False
                for name, alternatives in groups.items():
                    if depth < len(alternatives) and len(selected) < top_k:
                        position = alternatives[depth]
                        selected.append(position)
                        evidence.append({"key": position["key"], "score": round(scores[name], 6)})
                        added = True
                if not added:
                    break
                depth += 1
            fingerprint = self._fingerprint
        else:
            logger.info("Embedding search skipped: scope=%s has no catalog positions", scope)
        elapsed = round(perf_counter() - started, 3)
        logger.info("Embedding search completed: scope=%s candidates=%d index_source=%s query_elapsed=%.3fs total_elapsed=%.3fs",
                    scope, len(selected), index_info["status"] if index_info else "none", query_seconds, elapsed)
        return {"positions": selected, "evidence": evidence, "method": "embedding",
                "model": self.client.model_id, "metric": "cosine", "query": text,
                "query_prompt": QUERY_PROMPT, "document_prompt": DOCUMENT_PROMPT,
                "index_sha256": fingerprint, "scope_positions": len(positions),
                "index": index_info, "query_elapsed_seconds": query_seconds, "elapsed_seconds": elapsed,
                "truncated": len(selected) < len(positions),
                "note": f"Nearest catalog names without a lexical gate or acceptance cutoff. Up to {self.max_names} distinct names, preserving code/version alternatives. Similarity is not a match probability; classifier checks product identity and catalog rules separately."}
