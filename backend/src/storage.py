"""One SQLAlchemy engine for typed catalogue queries, imports and run evidence."""

from contextvars import ContextVar
from datetime import date
import hashlib
import json
import logging
from pathlib import Path
import re

from psycopg import sql
from psycopg.types.json import Json, Jsonb
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import selectinload, sessionmaker

from backend.src.models import CatalogueSource, KtruCharacteristic, KtruPosition, KtruValue

logger = logging.getLogger("uvicorn.error")
current_run: ContextVar[str | None] = ContextVar("analysis_run", default=None)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def eligible(import_sha256, scope="all", as_of=None):
    """Current specific positions. Scope definitions retain the backend's rubric policy."""
    today = as_of or date.today()
    conditions = [KtruPosition.import_sha256 == import_sha256,
                  KtruPosition.status == "ACTIVE", KtruPosition.is_template.is_(False),
                  KtruPosition.applies_from <= today,
                  (KtruPosition.applies_to.is_(None) | (KtruPosition.applies_to > today)),
                  (KtruPosition.terminated_on.is_(None) | (KtruPosition.terminated_on > today))]
    if scope == "clothing":
        conditions.append(KtruPosition.rubric_codes.contains(["116"]))
    elif scope == "furniture":
        conditions.append(KtruPosition.rubric_codes.contains(["128"]))
    elif scope == "tools":
        conditions.append(KtruPosition.code.startswith("25.73.") | KtruPosition.code.startswith("28.24."))
    elif scope == "drills":
        conditions.append(KtruPosition.name == "Дрель ручная электрическая")
    elif scope != "all":
        raise ValueError("unsupported catalogue scope")
    return conditions


class PostgresStore:
    def __init__(self, settings, *, schema="public", catalogue_schema=None):
        self.schema = schema
        self.catalogue_schema = catalogue_schema or ("catalogue" if schema == "public" else schema + "_catalogue")
        for name in (schema, self.catalogue_schema):
            if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
                raise ValueError("Invalid PostgreSQL schema name")
        if self.schema == self.catalogue_schema:
            raise ValueError("evidence and catalogue schemas must be separate")
        url = make_url(settings.database_url).set(drivername="postgresql+psycopg")
        self.engine = create_engine(
            url, pool_size=settings.database_pool_min_size,
            max_overflow=settings.database_pool_max_size - settings.database_pool_min_size,
            pool_timeout=settings.database_pool_timeout_seconds, pool_pre_ping=True,
            connect_args={"connect_timeout": settings.database_connect_timeout_seconds,
                          "options": f"-csearch_path={schema},public"},
            execution_options={"schema_translate_map": {"catalogue": self.catalogue_schema}},
        )
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self):
        try:
            with self.engine.begin() as connection:
                driver = connection.connection.driver_connection
                with driver.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('tenderhack:migrations', 0))")
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
                    cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
                    cur.execute("CREATE TABLE IF NOT EXISTS backend_schema_migrations "
                                "(version integer PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz DEFAULT now())")
                    cur.execute("CREATE TABLE IF NOT EXISTS backend_storage_config (key text PRIMARY KEY, value text NOT NULL)")
                    cur.execute("SELECT value FROM backend_storage_config WHERE key='catalogue_schema'")
                    mapping = cur.fetchone()
                    if mapping and mapping[0] != self.catalogue_schema:
                        raise ValueError("An existing evidence schema cannot be remapped to another catalogue schema")
                    cur.execute("INSERT INTO backend_storage_config(key,value) VALUES ('catalogue_schema',%s) ON CONFLICT DO NOTHING",
                                (self.catalogue_schema,))
                    for path in sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")):
                        version = int(path.name.split("_")[0])
                        body = path.read_text(encoding="utf-8")
                        checksum = hashlib.sha256(body.encode()).hexdigest()
                        cur.execute("SELECT sha256 FROM backend_schema_migrations WHERE version=%s", (version,))
                        existing = cur.fetchone()
                        if existing:
                            if existing[0] != checksum:
                                raise ValueError(f"Applied migration {version} was modified")
                            continue
                        statement = (sql.SQL(body).format(catalogue_schema=sql.Identifier(self.catalogue_schema))
                                     if "{catalogue_schema}" in body else body)
                        cur.execute(statement, prepare=False)
                        cur.execute("INSERT INTO backend_schema_migrations(version,sha256) VALUES (%s,%s)", (version, checksum))
                        logger.info("PostgreSQL migration applied: version=%s", version)
            logger.info("PostgreSQL ready: evidence=%s catalogue=%s", self.schema, self.catalogue_schema)
        except BaseException:
            self.close()
            raise

    def close(self):
        self.engine.dispose()

    def get_active_import(self, key):
        with self.session() as session:
            return session.scalar(select(CatalogueSource.import_sha256).where(CatalogueSource.key == key))

    def get_positions(self, import_sha256, codes):
        with self.session() as session:
            positions = list(session.scalars(
                select(KtruPosition).where(KtruPosition.import_sha256 == import_sha256, KtruPosition.code.in_(codes))
                .options(selectinload(KtruPosition.characteristics).selectinload(KtruCharacteristic.values))
            ))
            # No lazy loading or expired objects may escape into inference.
            session.expunge_all()
            return positions

    def has_embeddings(self, import_sha256, fingerprint):
        with self.session() as session:
            return session.scalar(select(KtruPosition.code).where(
                KtruPosition.import_sha256 == import_sha256,
                KtruPosition.embedding_config == fingerprint,
                KtruPosition.embedding.is_not(None)).limit(1)) is not None

    def search_catalogue(self, import_sha256, query, vector, fingerprint, scope, limit):
        """Field-level nearest neighbours first; rank fusion and diversification afterward."""
        conditions = eligible(import_sha256, scope)
        hits = {}
        with self.session() as session:
            count = session.scalar(select(func.count()).select_from(KtruPosition).where(*conditions))
            # Bound distance-ordered row queries allow HNSW to participate, unlike MAX/GROUP BY scans.
            session.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
            session.execute(text("SET LOCAL hnsw.ef_search = 100"))
            session.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.1"))
            norm = getattr(func, self.catalogue_schema).norm
            for field, model, column in (("position", KtruPosition, KtruPosition.name),
                                          ("characteristic", KtruCharacteristic, KtruCharacteristic.name),
                                          ("value", KtruValue, KtruValue.text)):
                statement = select(KtruPosition.code, KtruPosition.name)
                extra = []
                if model is not KtruPosition:
                    statement = statement.select_from(model).join(KtruPosition,
                        (model.import_sha256 == KtruPosition.import_sha256) &
                        (model.position_code == KtruPosition.code))
                    if model is KtruCharacteristic:
                        extra.append(KtruCharacteristic.actual.is_(True))
                    else:
                        statement = statement.join(KtruCharacteristic,
                            (KtruValue.import_sha256 == KtruCharacteristic.import_sha256) &
                            (KtruValue.position_code == KtruCharacteristic.position_code) &
                            (KtruValue.characteristic_code == KtruCharacteristic.code))
                        extra += [KtruCharacteristic.actual.is_(True), KtruValue.text.is_not(None), KtruValue.issue.is_(None)]
                modes = [("lexical", func.similarity(norm(column), norm(query)),
                          [norm(column).bool_op("%")(norm(query))])]
                if vector is not None:
                    modes.append(("semantic", model.embedding.cosine_distance(vector),
                                  [model.embedding_config == fingerprint, model.embedding.is_not(None)]))
                for mode, score, gate in modes:
                    ranked = statement.add_columns(score.label("score")).where(*conditions, *extra, *gate)
                    ranked = ranked.order_by(score if mode == "semantic" else score.desc())
                    target, row_limit = max(100, limit * 8), max(100, limit * 8)
                    while True:
                        rows = session.execute(ranked.limit(row_limit)).all()
                        unique = {}
                        for row in rows:
                            unique.setdefault(row.code, row)
                        if len(unique) >= target or len(rows) < row_limit or row_limit >= 10000:
                            break
                        row_limit = min(row_limit * 2, 10000)
                    capped = len(rows) == row_limit and row_limit == 10000 and len(unique) < target
                    for rank, row in enumerate(list(unique.values())[:target], 1):
                        signal = 1 - float(row.score) if mode == "semantic" else float(row.score)
                        hit = hits.setdefault(row.code, {"code": row.code, "name": row.name, "score": 0.0, "fields": {}})
                        hit["fields"][field + "_" + mode] = signal
                        hit["score"] += (2 if field == "position" else 1) / (60 + rank)
                        if capped:
                            hit["field_scan_capped"] = True
        # Round-robin name families retains alternative codes instead of returning one arbitrary code.
        groups = {}
        for hit in sorted(hits.values(), key=lambda hit: (-hit["score"], hit["code"])):
            groups.setdefault(hit["name"], []).append(hit)
        chosen = []
        while groups and len(chosen) < limit:
            for name in list(groups):
                chosen.append(groups[name].pop(0))
                if not groups[name]:
                    del groups[name]
                if len(chosen) == limit:
                    break
        positions = {position.code: position for position in self.get_positions(import_sha256, [h["code"] for h in chosen])}
        return [positions[h["code"]] for h in chosen], chosen, count

    def _write(self, statement, parameters):
        with self.engine.begin() as connection:
            connection.exec_driver_sql(statement, parameters)

    def begin_run(self, run_id, request):
        self._write("INSERT INTO analysis_runs(id,status,request) VALUES (%s,'running',%s)", (run_id, Jsonb(request)))

    def save_plan(self, run_id, plan):
        self._write("UPDATE analysis_runs SET catalogue_import_sha256=%s,plan=%s,planned_requests=%s,planned_questions=%s WHERE id=%s",
                    (plan["import_sha256"], Jsonb(plan), len(plan["requests"]), plan["question_count"], run_id))

    def save_artifact(self, run_id, name, payload):
        self._write("INSERT INTO run_artifacts(run_id,name,payload) VALUES (%s,%s,%s) "
                    "ON CONFLICT(run_id,name) DO UPDATE SET payload=EXCLUDED.payload", (run_id, name, Jsonb(payload)))

    def start_model_call(self, run_id, ordinal, outgoing):
        self._write("INSERT INTO model_calls(run_id,ordinal,requested_at,status,request_id,experiment,method,url,request,outgoing) "
                    "VALUES (%s,%s,%s,'running',%s,%s,%s,%s,%s,%s)",
                    (run_id, ordinal, outgoing["logged_at"], outgoing["id"], outgoing["experiment"], outgoing["method"],
                     outgoing["url"], Json(outgoing["request"]), Json(outgoing)))

    def finish_model_call(self, run_id, ordinal, record):
        self._write("UPDATE model_calls SET finished_at=now(),status=%s,response=%s,record=%s,error=%s,elapsed_seconds=%s "
                    "WHERE run_id=%s AND ordinal=%s",
                    ("failed" if "error" in record else "succeeded", Json(record["response"]) if "response" in record else None,
                     Json(record), record.get("error"), record.get("elapsed_seconds"), run_id, ordinal))

    def finish_run(self, run_id, details, result, error=None):
        self._write("UPDATE analysis_runs SET status=%s,finished_at=now(),analysis=%s,result=%s,error=%s WHERE id=%s",
                    ("failed" if error else "completed", Jsonb(details), Jsonb(result), error, run_id))

    def fail_run(self, run_id, error):
        self._write("UPDATE analysis_runs SET status='failed',finished_at=now(),error=%s WHERE id=%s", (str(error), run_id))

    def get_run(self, run_id):
        with self.engine.connect() as connection:
            row = connection.exec_driver_sql("SELECT * FROM analysis_runs WHERE id=%s", (run_id,)).mappings().first()
            return dict(row) if row else None

    def save_connection_checks(self, records):
        for record in records:
            self._write("INSERT INTO connection_checks(checked_at,service,url,payload) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (record["checked_at"], record["service"], record["url"], Jsonb(record)))

    def start_embedding_call(self, request, url):
        with self.engine.begin() as connection:
            return connection.exec_driver_sql(
                "INSERT INTO embedding_calls(run_id,status,request,model,url) VALUES (%s,'running',%s,%s,%s) RETURNING id",
                (current_run.get(), Json(request), request["dense_model_id"], url)).scalar_one()

    def finish_embedding_call(self, call_id, dimensions, elapsed, error=None):
        self._write("UPDATE embedding_calls SET finished_at=now(),status=%s,dimensions=%s,elapsed_seconds=%s,error=%s WHERE id=%s",
                    ("failed" if error else "succeeded", dimensions, elapsed, error, call_id))
