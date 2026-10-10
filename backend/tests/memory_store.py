"""In-memory persistence double; real SQL is covered by test_storage.py."""

from copy import deepcopy

from backend.src.storage import digest


class MemoryStore:
    def __init__(self):
        self.catalogs = {}
        self.indexes = {}
        self.runs = {}
        self.artifacts = {}
        self.calls = {}
        self.checks = []

    def initialize(self):
        pass

    def close(self):
        pass

    def get_catalog(self, key):
        return deepcopy(self.catalogs.get(key))

    def save_catalog(self, catalog, key=None):
        if key is not None:
            self.catalogs[key] = deepcopy(catalog)
        return digest(catalog)

    def load_embedding_index(self, fingerprint):
        return deepcopy(self.indexes.get(fingerprint))

    def save_embedding_index(self, fingerprint, metadata, vectors):
        self.indexes[fingerprint] = deepcopy({"metadata": metadata, "vectors": vectors})

    def score_embeddings(self, fingerprint, query, names):
        index = self.indexes[fingerprint]
        return {name: sum(a * b for a, b in zip(query, vector, strict=True))
                for name, vector in zip(index["metadata"]["names"], index["vectors"], strict=True) if name in names}

    def begin_run(self, run_id, request):
        self.runs[run_id] = dict(id=run_id, request=deepcopy(request), status="running", result=None)
        self.calls[run_id] = []
        self.artifacts[run_id] = {}

    def save_plan(self, run_id, plan):
        self.runs[run_id]["plan"] = deepcopy(plan["jobs"])

    def save_artifact(self, run_id, name, payload):
        self.artifacts[run_id][name] = deepcopy(payload)

    def start_model_call(self, run_id, ordinal, outgoing):
        self.calls[run_id].append({"outgoing": deepcopy(outgoing), "status": "running"})

    def finish_model_call(self, run_id, ordinal, record):
        self.calls[run_id][ordinal].update(record=deepcopy(record), status="failed" if "error" in record else "succeeded")

    def finish_run(self, run_id, details, result, error=None):
        self.runs[run_id].update(analysis=deepcopy(details), result=deepcopy(result), error=error,
                                status="failed" if error else "completed")

    def fail_run(self, run_id, error):
        self.runs[run_id].update(status="failed", error=str(error))

    def get_run(self, run_id):
        return deepcopy(self.runs.get(run_id))

    def save_connection_checks(self, records):
        self.checks.extend(deepcopy(records))
