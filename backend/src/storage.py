"""Transactional PostgreSQL persistence for catalog, vectors and inference evidence."""

from contextvars import ContextVar
import hashlib
import json
import logging
from pathlib import Path
import re

from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json, Jsonb
from psycopg_pool import ConnectionPool

logger = logging.getLogger("uvicorn.error")
current_run = ContextVar("analysis_run", default=None)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def vector_literal(values):
    return "[" + ",".join(str(float(value)) for value in values) + "]"


class PostgresStore:
    def __init__(self, settings, *, schema="public"):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", schema):
            raise ValueError("Invalid PostgreSQL schema name")
        self.schema = schema
        self.pool = ConnectionPool(
            settings.database_url, open=False,
            min_size=settings.database_pool_min_size, max_size=settings.database_pool_max_size,
            timeout=settings.database_pool_timeout_seconds,
            kwargs={"connect_timeout": settings.database_connect_timeout_seconds,
                    "options": f"-csearch_path={schema},public", "row_factory": dict_row},
            check=ConnectionPool.check_connection,
        )
        self.timeout = settings.database_pool_timeout_seconds

    def initialize(self):
        try:
            self.pool.open(wait=True, timeout=self.timeout)
            with self.pool.connection() as conn:
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('tenderhack:migrations', 0))")
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
                conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
                conn.execute("CREATE TABLE IF NOT EXISTS backend_schema_migrations "
                             "(version integer PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz DEFAULT now())")
                for path in sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")):
                    version = int(path.name.split("_")[0])
                    body = path.read_text(encoding="utf-8")
                    checksum = hashlib.sha256(body.encode()).hexdigest()
                    existing = conn.execute("SELECT sha256 FROM backend_schema_migrations WHERE version=%s", (version,)).fetchone()
                    if existing:
                        if existing["sha256"] != checksum:
                            raise ValueError(f"Applied migration {version} was modified")
                        continue
                    conn.execute(body, prepare=False)
                    conn.execute("INSERT INTO backend_schema_migrations(version, sha256) VALUES (%s,%s)", (version, checksum))
                    logger.info("PostgreSQL migration applied: version=%s", version)
            logger.info("PostgreSQL connection OK; schema=%s", self.schema)
        except BaseException:
            self.close()
            raise

    def close(self):
        self.pool.close()

    def get_catalog(self, key):
        with self.pool.connection() as conn:
            row = conn.execute("SELECT c.payload FROM catalog_snapshots c JOIN catalog_sources s "
                               "ON s.snapshot_sha256=c.sha256 WHERE s.key=%s", (key,)).fetchone()
            return row["payload"] if row else None

    def save_catalog(self, catalog, key=None):
        fingerprint = digest(catalog)
        with self.pool.connection() as conn:
            inserted = conn.execute("INSERT INTO catalog_snapshots(sha256,payload) VALUES (%s,%s) "
                                    "ON CONFLICT DO NOTHING RETURNING sha256", (fingerprint, Jsonb(catalog))).fetchone()
            if inserted:
                with conn.cursor() as cur:
                    cur.executemany("INSERT INTO catalog_positions(snapshot_sha256,key,code,version,name,domains,payload) "
                                    "VALUES (%s,%s,%s,%s,%s,%s,%s)", [
                        (fingerprint, p["key"], p["code"], p["version"], p["name"], p["domains"], Jsonb(p))
                        for p in catalog["positions"]])
                    cur.executemany("INSERT INTO catalog_facts(snapshot_sha256,id,name,value,unit_code,payload) "
                                    "VALUES (%s,%s,%s,%s,%s,%s)", [
                        (fingerprint, f["id"], f["name"], f["value"], f["unit_code"], Jsonb(f)) for f in catalog["facts"]])
            if key is not None:
                conn.execute("INSERT INTO catalog_sources(key,snapshot_sha256) VALUES (%s,%s) "
                             "ON CONFLICT(key) DO UPDATE SET snapshot_sha256=EXCLUDED.snapshot_sha256", (key, fingerprint))
        return fingerprint

    def load_embedding_index(self, fingerprint):
        with self.pool.connection() as conn:
            index = conn.execute("SELECT i.metadata, ARRAY(SELECT e.embedding::text FROM catalog_embeddings e "
                                 "WHERE e.fingerprint=i.fingerprint ORDER BY e.ordinal) AS vectors "
                                 "FROM embedding_indexes i WHERE i.fingerprint=%s", (fingerprint,)).fetchone()
            if index is None:
                return None
        return {"metadata": index["metadata"], "vectors": [json.loads(value) for value in index["vectors"]]}

    def save_embedding_index(self, fingerprint, metadata, vectors):
        if not vectors or len(vectors) != len(metadata["names"]) or len({len(v) for v in vectors}) != 1:
            raise ValueError("Incomplete embedding index")
        with self.pool.connection() as conn:
            conn.execute("INSERT INTO embedding_indexes(fingerprint,model,dimensions,metadata) VALUES (%s,%s,%s,%s) "
                         "ON CONFLICT(fingerprint) DO UPDATE SET metadata=EXCLUDED.metadata,dimensions=EXCLUDED.dimensions",
                         (fingerprint, metadata["model"], len(vectors[0]), Jsonb(metadata)))
            conn.execute("DELETE FROM catalog_embeddings WHERE fingerprint=%s", (fingerprint,))
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO catalog_embeddings(fingerprint,name,ordinal,embedding) VALUES (%s,%s,%s,%s::public.vector)",
                                [(fingerprint, name, index, vector_literal(vector))
                                 for index, (name, vector) in enumerate(zip(metadata["names"], vectors, strict=True))])

    def score_embeddings(self, fingerprint, query, names):
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT name, 1 - (embedding <=> %s::public.vector) AS score "
                                "FROM catalog_embeddings WHERE fingerprint=%s AND name=ANY(%s)",
                                (vector_literal(query), fingerprint, names)).fetchall()
        return {row["name"]: row["score"] for row in rows}

    def begin_run(self, run_id, request):
        with self.pool.connection() as conn:
            conn.execute("INSERT INTO analysis_runs(id,status,request) VALUES (%s,'running',%s)", (run_id, Jsonb(request)))

    def save_plan(self, run_id, plan):
        with self.pool.connection() as conn:
            conn.execute("UPDATE analysis_runs SET catalog_sha256=%s, plan=%s, planned_requests=%s, planned_questions=%s WHERE id=%s",
                         (plan["catalog_sha256"], Jsonb(plan["requests"]), len(plan["requests"]), plan["question_count"], run_id))

    def save_artifact(self, run_id, name, payload):
        with self.pool.connection() as conn:
            conn.execute("INSERT INTO run_artifacts(run_id,name,payload) VALUES (%s,%s,%s) "
                         "ON CONFLICT(run_id,name) DO UPDATE SET payload=EXCLUDED.payload", (run_id, name, Jsonb(payload)))

    def start_model_call(self, run_id, ordinal, outgoing):
        with self.pool.connection() as conn:
            conn.execute("INSERT INTO model_calls(run_id,ordinal,requested_at,status,request_id,experiment,method,url,request,outgoing) "
                         "VALUES (%s,%s,%s,'running',%s,%s,%s,%s,%s,%s)",
                         (run_id, ordinal, outgoing["logged_at"], outgoing["id"], outgoing["experiment"], outgoing["method"],
                          outgoing["url"], Json(outgoing["request"]), Json(outgoing)))

    def finish_model_call(self, run_id, ordinal, record):
        with self.pool.connection() as conn:
            conn.execute("UPDATE model_calls SET finished_at=now(),status=%s,response=%s,record=%s,error=%s,elapsed_seconds=%s "
                         "WHERE run_id=%s AND ordinal=%s",
                         ("failed" if "error" in record else "succeeded", Json(record["response"]) if "response" in record else None,
                          Json(record), record.get("error"), record.get("elapsed_seconds"), run_id, ordinal))

    def finish_run(self, run_id, details, result, error=None):
        with self.pool.connection() as conn:
            conn.execute("UPDATE analysis_runs SET status=%s,finished_at=now(),analysis=%s,result=%s,error=%s WHERE id=%s",
                         ("failed" if error else "completed", Jsonb(details), Jsonb(result), error, run_id))

    def fail_run(self, run_id, error):
        with self.pool.connection() as conn:
            conn.execute("UPDATE analysis_runs SET status='failed',finished_at=now(),error=%s WHERE id=%s", (str(error), run_id))

    def get_run(self, run_id):
        with self.pool.connection() as conn:
            return conn.execute("SELECT * FROM analysis_runs WHERE id=%s", (run_id,)).fetchone()

    def save_connection_checks(self, records):
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.executemany("INSERT INTO connection_checks(checked_at,service,url,payload) VALUES (%s,%s,%s,%s) "
                            "ON CONFLICT DO NOTHING", [(r["checked_at"], r["service"], r["url"], Jsonb(r)) for r in records])

    def start_embedding_call(self, request, url):
        with self.pool.connection() as conn:
            return conn.execute("INSERT INTO embedding_calls(run_id,status,request,model,url) VALUES (%s,'running',%s,%s,%s) RETURNING id",
                                (current_run.get(), Json(request), request["dense_model_id"], url)).fetchone()["id"]

    def finish_embedding_call(self, call_id, dimensions, elapsed, error=None):
        with self.pool.connection() as conn:
            conn.execute("UPDATE embedding_calls SET finished_at=now(),status=%s,dimensions=%s,elapsed_seconds=%s,error=%s WHERE id=%s",
                         ("failed" if error else "succeeded", dimensions, elapsed, error, call_id))
