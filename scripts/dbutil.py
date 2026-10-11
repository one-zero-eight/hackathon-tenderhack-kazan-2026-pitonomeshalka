"""Helpers shared by the PostgreSQL catalogue loaders."""

import hashlib
import json
import os
from pathlib import Path
import sys

from psycopg import sql

# Direct CLI execution puts scripts/, not the repository, on sys.path.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://tenderhack:tenderhack@localhost:5432/tenderhack")
MAX_VALUE_LENGTH = 500  # longer strings are prose, not enum values
IMPORT_FORMAT_VERSION = 2


def copy(cur, table, columns, rows, *, schema):
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(schema, table), sql.SQL(", ").join(map(sql.Identifier, columns)),
    )
    with cur.copy(statement) as out:
        for row in rows:
            out.write_row(row)


def insert_missing(cur, table, columns, rows, *, schema):
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
        sql.Identifier(schema, table), sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    cur.executemany(statement, rows)


def file_sha256(path):
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def source_manifest(xml_paths, xlsx_paths):
    """Stable identity from file content, relative names and the import format."""
    files = []
    for kind, paths in (("xml", xml_paths), ("xlsx", xlsx_paths)):
        for path in paths:
            files.append({"name": f"{kind}/{path.name}", "sha256": file_sha256(path), "kind": kind})
    metadata = {"format_version": IMPORT_FORMAT_VERSION, "files": sorted(files, key=lambda row: row["name"])}
    encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest(), metadata
