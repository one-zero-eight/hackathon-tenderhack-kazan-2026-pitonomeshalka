"""Artifact reads on a fake engine; real SQL stays covered by the opt-in Postgres suite."""

from types import SimpleNamespace

from backend.src.storage import PostgresStore


SETTINGS = SimpleNamespace(
    database_url="postgresql://tenderhack:tenderhack@127.0.0.1:5432/tenderhack",
    database_connect_timeout_seconds=1,
    database_pool_min_size=1,
    database_pool_max_size=2,
    database_pool_timeout_seconds=1.0,
)


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def exec_driver_sql(self, statement, parameters=None):
        self.statements.append((statement, parameters))
        return FakeResult(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeEngine:
    def __init__(self, rows):
        self.connection = FakeConnection(rows)

    def connect(self):
        return self.connection


def store_with_rows(rows):
    store = PostgresStore(SETTINGS)
    store.engine = FakeEngine(rows)
    return store


def test_get_artifact_returns_saved_payload():
    payload = {"round": 1, "candidate_codes": ["10", "20"],
               "question_id": "question", "answers": []}
    store = store_with_rows([{"payload": payload}])

    assert store.get_artifact("run-1", "clarification_state.json") == payload

    statement, parameters = store.engine.connection.statements[0]
    assert "run_artifacts" in statement and "payload" in statement
    assert parameters == ("run-1", "clarification_state.json")


def test_get_artifact_returns_none_for_missing_run_or_name():
    store = store_with_rows([])

    assert store.get_artifact("missing-run", "clarification_state.json") is None
