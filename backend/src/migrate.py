"""Apply database migrations and optionally import legacy backend files."""

import argparse
from datetime import datetime, timezone
import json
import logging
import re

from psycopg.types.json import Json, Jsonb

from backend.src.service import load_catalog
from backend.src.settings import Settings
from backend.src.storage import PostgresStore, digest
from experiments.embedding_retrieval import unit_vector

logger = logging.getLogger("uvicorn.error")
RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{12}Z_[0-9a-f]{32}$")


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def import_run(store, directory):
    """Import one complete legacy directory atomically; repeated imports are harmless."""
    artifacts = {path.name: json.loads(path.read_text(encoding="utf-8")) for path in directory.glob("*.json")}
    outgoing = read_lines(directory / "model_requests.jsonl")
    records = read_lines(directory / "requests.jsonl")
    details = artifacts.get("analysis.json")
    result = artifacts.get("response.json")
    plan = artifacts.get("request_plan.json", [])
    manifest = artifacts.get("manifest.json", {})
    query = (details or {}).get("analysis", {}).get("retrieval", {}).get("query")
    request = {"text": query, "scope": manifest.get("scope"), "threshold": manifest.get("threshold_uncalibrated"),
               "imported_from_files": True}
    created = datetime.strptime(directory.name.split("_")[0], "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
    error = artifacts.get("startup_error.json", {}).get("error") or next((r["error"] for r in records if "error" in r), None)
    status = "failed" if error else "completed" if result else "interrupted"
    with store.pool.connection() as conn:
        inserted = conn.execute(
            "INSERT INTO analysis_runs(id,created_at,finished_at,status,request,plan,planned_requests,planned_questions,error,result,analysis) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
            (directory.name, created, datetime.fromtimestamp(directory.stat().st_mtime, timezone.utc) if result or error else None,
             status, Jsonb(request), Jsonb(plan), (details or {}).get("planned_requests", manifest.get("planned_requests")),
             (details or {}).get("planned_questions"), error, Jsonb(result) if result is not None else None,
             Jsonb(details) if details is not None else None),
        ).fetchone()
        if not inserted:
            return False
        fingerprint = (details or {}).get("catalog_sha256", manifest.get("catalog_sha256"))
        conn.execute("UPDATE analysis_runs SET catalog_sha256=(SELECT sha256 FROM catalog_snapshots WHERE sha256=%s) WHERE id=%s",
                     (fingerprint, directory.name))
        for name, payload in artifacts.items():
            conn.execute("INSERT INTO run_artifacts(run_id,name,payload) VALUES (%s,%s,%s)", (directory.name, name, Jsonb(payload)))
        # Older logs may have completed records without a pre-dispatch log.
        if not outgoing:
            outgoing = [{"id": r["id"], "experiment": r["experiment"], "method": "POST",
                         "url": manifest.get("base_url", "").rstrip("/") + "/v1/systemone", "request": r["request"],
                         "logged_at": created.isoformat(), "timestamp_source": "run_id"} for r in records]
        for index, entry in enumerate(outgoing):
            record = records[index] if index < len(records) else None
            if record is not None and record["id"] != entry["id"]:
                raise ValueError(f"Request/response order differs in {directory.name}")
            call_status = "failed" if record and "error" in record else "succeeded" if record else "running"
            conn.execute(
                "INSERT INTO model_calls(run_id,ordinal,requested_at,status,request_id,experiment,method,url,request,outgoing,response,record,error,elapsed_seconds) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (directory.name, index, entry["logged_at"], call_status, entry["id"], entry["experiment"], entry["method"], entry["url"],
                 Json(entry["request"]), Json(entry), Json(record["response"]) if record and "response" in record else None,
                 Json(record) if record else None, (record or {}).get("error"), (record or {}).get("elapsed_seconds")),
            )
    return True


def import_files(store, settings):
    counts = {"catalogs": 0, "embedding_indexes": 0, "runs": 0}
    if store.get_catalog(settings.catalog_key) is None:
        catalog = load_catalog(settings)
        store.save_catalog(catalog, settings.catalog_key)
        counts["catalogs"] = 1
    if settings.embedding_cache_path.exists():
        cache = json.loads(settings.embedding_cache_path.read_text(encoding="utf-8"))
        fingerprint = digest(cache["metadata"])
        if store.load_embedding_index(fingerprint) is None:
            store.save_embedding_index(fingerprint, cache["metadata"], [unit_vector(v) for v in cache["vectors"]])
            counts["embedding_indexes"] = 1
    if settings.results_dir.exists():
        for directory in sorted(settings.results_dir.iterdir()):
            if directory.is_dir() and RUN_ID.fullmatch(directory.name):
                counts["runs"] += import_run(store, directory)
    store.save_connection_checks(read_lines(settings.startup_log_path))
    logger.info("Legacy import completed: %s", counts)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-files", action="store_true", help="Import existing catalog, embeddings, runs and startup logs; preserve source files")
    args = parser.parse_args()
    settings = Settings.from_environment()
    logging.basicConfig(level=settings.log_level.upper())
    store = PostgresStore(settings)
    try:
        store.initialize()
        if args.import_files:
            import_files(store, settings)
    finally:
        store.close()


if __name__ == "__main__":
    main()
